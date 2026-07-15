"""PDF 输出模块（PyMuPDF 双层 PDF）。

使用 PyMuPDF TextWriter 生成真正的双层 PDF：
- 保留原 PDF 矢量层
- 透明文本层: render_mode=3, 不可见但可选/可复制/可搜索
- 红色文本层: render_mode=0 + color=(1,0,0), 可见红色文字
- 按行组织文本，支持按行选择/复制

依赖:
    PyMuPDF (fitz): PDF 读写与 TextWriter 文本叠加。
    PyQt5.QtCore: QThread 子线程化生成流程。
"""

import os

import fitz  # PyMuPDF
from PyQt5.QtCore import QThread, pyqtSignal

from models.data_models import flatten_bbox, FONT_SIZE_GRADES, match_font_grade, font_name_for_char
from native import batch_match_font_grade


class PDFOutputGenerator:
    """PDF 输出生成器（PyMuPDF 双层 PDF）。

    保留原 PDF 矢量层，在页面上叠加不可见或红色文本层。
    每个字符通过独立的 TextWriter 写入，使每个字符成为 PDF 内容流中
    独立的 BT/ET 文本对象，从而支持逐字选择与复制。

    依赖:
        fitz (PyMuPDF): 打开原 PDF、创建 TextWriter、写入文本层。
    """

    def generate(self, corrected_chars, output_path, pdf_path,
                 text_color="red", progress_callback=None):
        """生成双层 PDF。

        打开原始 PDF 保留其矢量层，按 page_num + line_id 将校对字符分组，
        逐字符通过独立的 TextWriter 叠加文本层，分别支持不可见或红色两种模式。
        每个字符在 PDF 内容流中生成独立的 BT/ET 文本对象。

        Args:
            corrected_chars: CharSlice/CorrectedChar 对象列表，每个对象需
                包含 page_num、bbox、text、ignored、line_id 属性。
            output_path (str): 输出 PDF 文件保存路径。
            pdf_path (str): 原始 PDF 文件路径（用于打开保留矢量层）。
            text_color (str): "red" 可见红色 / "transparent" 不可见但可选可复制。
                默认为 "red"。
            progress_callback (callable, optional): 进度回调，
                签名为 (current_page, total_pages)。默认为 None。

        Raises:
            RuntimeError: 当缺少原始 PDF 路径或文件不存在时抛出。

        调用关系:
            被 PDFOutputWorker.run 调用。
        """
        if not pdf_path or not os.path.exists(pdf_path):
            raise RuntimeError("缺少原始 PDF 路径，无法生成双层 PDF")

        # 1. 打开原 PDF，保留矢量层
        doc = fitz.open(pdf_path)
        total_pages = doc.page_count

        # 2. 按 page_num 分组字符（过滤被忽略的字符）
        chars_by_page = {}
        for char in corrected_chars:
            if char.ignored:
                continue
            page = char.page_num
            if page not in chars_by_page:
                chars_by_page[page] = []
            chars_by_page[page].append(char)

        # 3. DPI（与 software1 OCR 一致，ocr_dpi=300）
        ocr_dpi = 300
        scale = 72.0 / ocr_dpi

        # 4. 逐页处理
        for page_idx in range(total_pages):
            page = doc[page_idx]
            page_chars = chars_by_page.get(page_idx, [])

            if page_chars:
                # 按 y 基线分组（CorrectedChar 无 line_id，用 y 中心聚类）
                line_groups = self._group_by_baseline(page_chars)

                # 批量收集所有行的行框高度（先排序+过滤空文本，与原逐行逻辑一致）
                batch_lines = []  # [(line_chars, bboxes)]
                all_heights = []
                for line_chars in line_groups:
                    line_chars = sorted(
                        line_chars,
                        key=lambda c: flatten_bbox(c.bbox)[0],
                    )
                    # 跳过空文本字符
                    line_chars = [c for c in line_chars if c.text]
                    if not line_chars:
                        continue

                    bboxes = [flatten_bbox(c.bbox) for c in line_chars]

                    # 判断行方向：行框并集 高>宽 则为竖排
                    if bboxes:
                        line_x1 = min(b[0] for b in bboxes)
                        line_y1 = min(b[1] for b in bboxes)
                        line_x2 = max(b[2] for b in bboxes)
                        line_y2 = max(b[3] for b in bboxes)
                        is_vertical = (line_y2 - line_y1) > (line_x2 - line_x1)
                    else:
                        is_vertical = False

                    # 字号: 竖排用字符框宽度（短边），横排用高度 → 磅值
                    if is_vertical:
                        sizes = [b[2] - b[0] for b in bboxes]
                    else:
                        sizes = [b[3] - b[1] for b in bboxes]
                    line_height_pt = sorted(sizes)[len(sizes) // 2] * scale
                    batch_lines.append((line_chars, bboxes))
                    all_heights.append(line_height_pt)

                # 批量匹配档位（H6 native 加速；缺失时回退逐行 match_font_grade）
                grades = batch_match_font_grade(all_heights)
                if grades is None:
                    grades = [match_font_grade(h) for h in all_heights]

                for (line_chars, bboxes), grade in zip(batch_lines, grades):
                    font_size_pt = FONT_SIZE_GRADES[grade]
                    if font_size_pt < 1:
                        font_size_pt = 1

                    # 逐字符居中定位：水平居中 + 垂直居中
                    # per-char 字体选择：ASCII 字母/数字 → Times New Roman
                    for c, b in zip(line_chars, bboxes):
                        # 优先尊重字符自定义 font_family（RefineTextItem 可能有该属性，
                        # CharSlice/CorrectedChar 无此属性，需安全获取）
                        char_family = getattr(c, 'font_family', None)
                        if char_family:
                            char_font = self._get_font_by_name(char_family, grade)
                        else:
                            char_font = self._get_font_for_char(c.text, grade)
                        # per-char baseline 计算（不同字体的 ascender/descender 不同）
                        # ascender/descender 为属性，非方法
                        char_ascender = char_font.ascender
                        char_descender = char_font.descender
                        char_baseline_offset = (
                            (char_ascender + char_descender) / 2.0 * font_size_pt
                        )
                        # 计算文字宽度（磅值）
                        try:
                            char_w_pt = char_font.text_length(c.text, font_size_pt)
                        except Exception:
                            char_w_pt = 0.0
                        bbox_w_pt = (b[2] - b[0]) * scale
                        bbox_h_pt = (b[3] - b[1]) * scale
                        # 水平居中：pos_x = bbox左边界 + (bbox宽 - 文字宽)/2
                        pos_x = b[0] * scale + (bbox_w_pt - char_w_pt) / 2
                        # 垂直居中：基线 = bbox中心 - 字符视觉中心相对基线偏移
                        pos_y = b[1] * scale + bbox_h_pt / 2 + char_baseline_offset
                        # 每字独立 TextWriter + write_text，
                        # 使每个字符成为 PDF 内容流中独立的 BT/ET 文本对象
                        char_tw = fitz.TextWriter(page.rect)
                        try:
                            char_tw.append(
                                (pos_x, pos_y), c.text,
                                font=char_font, fontsize=font_size_pt,
                            )
                            if text_color == "transparent":
                                char_tw.write_text(page, render_mode=3)
                            else:
                                char_tw.write_text(page, render_mode=0, color=(1, 0, 0))
                        except Exception:
                            # 跳过无法写入的文本（如越界或字形缺失）
                            pass

            if progress_callback:
                progress_callback(page_idx + 1, total_pages)

        # 5. 保存
        doc.save(output_path)
        doc.close()

    def _group_by_baseline(self, chars):
        """按 y 基线将字符分组为行。

        CorrectedChar 无 line_id 属性，此处用 y 中心近似聚类：
        按 y 中心排序后，相邻字符 y 中心差 > 中位行高 × 0.3 则分行。

        Args:
            chars: 同页的 CorrectedChar 列表。

        Returns:
            list[list]: 每个元素为一行字符列表（未按 x 排序）。
        """
        if not chars:
            return []

        bboxes = [flatten_bbox(c.bbox) for c in chars]
        y_centers = [(b[1] + b[3]) / 2 for b in bboxes]
        heights = [b[3] - b[1] for b in bboxes if b[3] > b[1]]
        median_h = sorted(heights)[len(heights) // 2] if heights else 20.0
        threshold = max(median_h * 0.3, 5.0)

        # 按 y 中心排序
        indexed = sorted(range(len(chars)), key=lambda i: y_centers[i])

        groups = []
        current = [chars[indexed[0]]]
        current_y = y_centers[indexed[0]]

        for idx in indexed[1:]:
            yc = y_centers[idx]
            if abs(yc - current_y) <= threshold:
                current.append(chars[idx])
            else:
                groups.append(current)
                current = [chars[idx]]
                current_y = yc
        groups.append(current)
        return groups

    def _get_font(self, grade=3):
        """根据字号档位加载中文字体，缓存实例避免重复加载。

        三/四/五号档位加载书宋体（simsun.ttc / STSONG.TTF），一/二号档位加载黑体（simhei.ttf）。
        字体文件不存在时回退到
        PyMuPDF 内置的简体中文字体（china-ss / china-s）。

        Args:
            grade: 字号档位号（1-5），默认 3。

        Returns:
            fitz.Font: 字体对象。
        """
        # 实例级缓存：按档位缓存 Font 实例
        if not hasattr(self, '_font_cache'):
            self._font_cache = {}
        if grade in self._font_cache:
            return self._font_cache[grade]

        windir = os.environ.get('WINDIR', 'C:\\Windows')
        font = None

        if grade in (3, 4, 5):
            # 三/四/五号：书宋体
            candidates = ['simsun.ttc', 'STSONG.TTF']
            builtin_fallbacks = ['china-ss', 'china-s']
        else:
            # 一/二号：黑体
            candidates = ['simhei.ttf']
            builtin_fallbacks = ['china-s']

        # 尝试从系统字体目录加载
        for name in candidates:
            font_path = os.path.join(windir, 'Fonts', name)
            if os.path.exists(font_path):
                try:
                    font = fitz.Font(fontfile=font_path)
                    break
                except Exception:
                    continue

        # 回退到内置 CJK 字体
        if font is None:
            for fb in builtin_fallbacks:
                try:
                    font = fitz.Font(fb)
                    break
                except Exception:
                    continue
            # 最终回退
            if font is None:
                font = fitz.Font('china-s')

        self._font_cache[grade] = font
        return font

    def _get_latin_font(self):
        """加载 Times New Roman 字体（ASCII 字母/数字专用），缓存实例。

        优先从系统字体目录加载 times.ttf；失败时回退到
        PyMuPDF 内置的 'Times-Roman'（PDF Base-14 字体）。

        Returns:
            fitz.Font: Times New Roman 字体对象。
        """
        if not hasattr(self, '_latin_font_cache'):
            self._latin_font_cache = None
        if self._latin_font_cache is not None:
            return self._latin_font_cache

        windir = os.environ.get('WINDIR', 'C:\\Windows')
        font_path = os.path.join(windir, 'Fonts', 'times.ttf')
        font = None
        if os.path.exists(font_path):
            try:
                font = fitz.Font(fontfile=font_path)
            except Exception:
                font = None
        if font is None:
            try:
                font = fitz.Font('Times-Roman')
            except Exception:
                font = fitz.Font('helv')  # 最终回退 Helvetica
        self._latin_font_cache = font
        return font

    def _get_font_for_char(self, text, grade):
        """根据字符内容选择字体：ASCII 字母/数字用 Times New Roman，其他用中文字体。

        Args:
            text: 字符文本（预期为单字符）。
            grade: 字号档位号（1-5）。

        Returns:
            fitz.Font: 字体对象。
        """
        if text and len(text) == 1:
            c = text[0]
            if ('0' <= c <= '9') or ('a' <= c <= 'z') or ('A' <= c <= 'Z'):
                return self._get_latin_font()
        return self._get_font(grade)

    def _get_font_by_name(self, font_family, grade=3):
        """根据字体族名加载对应的 fitz.Font，缓存实例避免重复加载。

        支持常见中文字体名映射：
            - "SimSun" / "宋体" / "书宋" → simsun.ttc
            - "SimHei" / "黑体" → simhei.ttf
            - "Times New Roman" → times.ttf
            - "KaiTi" / "楷体" → simkai.ttf
            - "FangSong" / "仿宋" → simfang.ttf
            - 其他 → 回退到档位默认字体

        用于尊重 RefineTextItem.font_family 自定义字体族。未匹配或加载失败时
        回退到档位默认中文字体（_get_font(grade)）。

        Args:
            font_family: 字体族名（如 "SimSun"、"宋体"、"Times New Roman"）。
            grade: 字号档位号（1-5），用于回退默认字体，默认 3。

        Returns:
            fitz.Font: 字体对象。
        """
        if not hasattr(self, '_font_by_name_cache'):
            self._font_by_name_cache = {}

        key = (font_family or '').strip()
        if not key:
            return self._get_font(grade)
        if key in self._font_by_name_cache:
            return self._font_by_name_cache[key]

        # 字体族名 → 系统字体文件名映射
        name_to_file = {
            'SimSun': 'simsun.ttc',
            '宋体': 'simsun.ttc',
            '书宋': 'simsun.ttc',
            'SimHei': 'simhei.ttf',
            '黑体': 'simhei.ttf',
            'Times New Roman': 'times.ttf',
            'KaiTi': 'simkai.ttf',
            '楷体': 'simkai.ttf',
            'FangSong': 'simfang.ttf',
            '仿宋': 'simfang.ttf',
        }

        font = None
        windir = os.environ.get('WINDIR', 'C:\\Windows')

        file_name = name_to_file.get(key)
        if file_name is None:
            # 模糊匹配：键中包含映射名（容错别名变体，如 "宋体 (SimSun)"）
            for map_key, map_file in name_to_file.items():
                if map_key in key or key in map_key:
                    file_name = map_file
                    break

        if file_name:
            font_path = os.path.join(windir, 'Fonts', file_name)
            if os.path.exists(font_path):
                try:
                    font = fitz.Font(fontfile=font_path)
                except Exception:
                    font = None

        # 回退到档位默认字体
        if font is None:
            font = self._get_font(grade)

        self._font_by_name_cache[key] = font
        return font


class PDFOutputWorker(QThread):
    """PDF 输出工作线程。

    在子线程中依次生成红色文字版和透明文字版两份 PDF 文件，
    通过信号实时报告生成进度，避免阻塞主线程 UI。

    信号:
        progress_signal(int, str): 进度百分比(0-100)和描述文字。
        finished_signal(): 两份 PDF 全部生成成功完成。
        error_signal(str): 生成过程中出现错误，携带错误信息。

    依赖:
        PDFOutputGenerator: 实际执行 PDF 生成的生成器实例。
    """

    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, generator, corrected_chars, red_path, transparent_path,
                 pdf_path=None):
        """初始化 PDF 输出工作线程。

        参数:
            generator: PDFOutputGenerator 实例，用于执行 PDF 生成。
            corrected_chars: 校对后的字符对象列表。
            red_path: 红色文字版 PDF 的输出路径。
            transparent_path: 透明文字版 PDF 的输出路径。
            pdf_path: 原始 PDF 文件路径（必需，用于打开保留矢量层）。
                默认为 None。
        """
        super().__init__()
        self._generator = generator
        self._corrected_chars = corrected_chars
        self._red_path = red_path
        self._transparent_path = transparent_path
        self._pdf_path = pdf_path

    def run(self):
        """执行 PDF 生成任务。

        依次生成红色文字版和透明文字版 PDF，每完成一页通过
        progress_signal 报告进度。全部完成后发射 finished_signal，
        出错时发射 error_signal。
        """
        try:
            total_steps = 2

            def on_red_progress(current, total):
                percent = int(current / total / total_steps * 100)
                self.progress_signal.emit(percent, f"红色版 {current}/{total} 页")

            self._generator.generate(
                self._corrected_chars, self._red_path, self._pdf_path,
                text_color="red", progress_callback=on_red_progress,
            )

            def on_transparent_progress(current, total):
                percent = int((1 + current / total) / total_steps * 100)
                self.progress_signal.emit(percent, f"透明版 {current}/{total} 页")

            self._generator.generate(
                self._corrected_chars, self._transparent_path, self._pdf_path,
                text_color="transparent", progress_callback=on_transparent_progress,
            )

            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))
