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

from models.data_models import flatten_bbox


class PDFOutputGenerator:
    """PDF 输出生成器（PyMuPDF 双层 PDF）。

    保留原 PDF 矢量层，在页面上叠加不可见或红色文本层。
    文本按行组织，每行通过一次 TextWriter.append 写入整行文本，
    从而支持按行选择与复制。

    依赖:
        fitz (PyMuPDF): 打开原 PDF、创建 TextWriter、写入文本层。
    """

    def generate(self, corrected_chars, output_path, pdf_path,
                 text_color="red", progress_callback=None):
        """生成双层 PDF。

        打开原始 PDF 保留其矢量层，按 page_num + line_id 将校对字符分组，
        整行拼接后通过 TextWriter 叠加文本层，分别支持不可见或红色两种模式。

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

        # 3. 加载中文字体
        font = self._get_font()

        # 4. DPI（与 software1 OCR 一致，ocr_dpi=300）
        ocr_dpi = 300
        scale = 72.0 / ocr_dpi

        # 5. 逐页处理
        for page_idx in range(total_pages):
            page = doc[page_idx]
            page_chars = chars_by_page.get(page_idx, [])

            if page_chars:
                # 按 y 基线分组（CorrectedChar 无 line_id，用 y 中心聚类）
                line_groups = self._group_by_baseline(page_chars)

                tw = fitz.TextWriter(page.rect)

                for line_chars in line_groups:
                    line_chars = sorted(
                        line_chars,
                        key=lambda c: flatten_bbox(c.bbox)[0],
                    )

                    # 整行文本拼接（中文不需要额外空格分隔）
                    line_text = ''.join(c.text for c in line_chars)
                    if not line_text:
                        continue

                    # 行起始坐标与字号
                    bboxes = [flatten_bbox(c.bbox) for c in line_chars]
                    pdf_x = bboxes[0][0] * scale
                    # y: 取行内 y1 的中位数作为基线起点（PyMuPDF 左上角原点，y 向下增长）
                    y1s = [b[1] for b in bboxes]
                    pdf_y = sorted(y1s)[len(y1s) // 2] * scale

                    # 字号: 行内高度中位数
                    heights = [b[3] - b[1] for b in bboxes]
                    font_size = sorted(heights)[len(heights) // 2] * scale
                    if font_size < 1:
                        font_size = 1

                    try:
                        tw.append(
                            (pdf_x, pdf_y), line_text,
                            font=font, fontsize=font_size,
                        )
                    except Exception:
                        # 跳过无法写入的文本（如越界或字形缺失）
                        pass

                # 写入页面
                if text_color == "transparent":
                    tw.write_text(page, render_mode=3)
                else:
                    tw.write_text(page, render_mode=0, color=(1, 0, 0))

            if progress_callback:
                progress_callback(page_idx + 1, total_pages)

        # 6. 保存
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

    def _get_font(self):
        """加载中文字体，优先微软雅黑，回退到内置 CJK。

        尝试从系统字体目录加载 msyh.ttc（微软雅黑），失败时回退到
        PyMuPDF 内置的简体中文字体 'china-s'，以确保中文可正常渲染。

        Returns:
            fitz.Font: 字体对象。
        """
        font_path = os.path.join(
            os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'msyh.ttc'
        )
        if os.path.exists(font_path):
            try:
                return fitz.Font(fontfile=font_path)
            except Exception:
                pass
        # 回退到内置简体中文
        return fitz.Font('china-s')


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
