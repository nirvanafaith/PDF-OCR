import json
import os
import tempfile
from pathlib import Path

from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

from models.data_models import CharSlice, LineSlice, flatten_bbox


def _try_native():
    """尝试加载本地 native 加速模块。

    成功返回 (pixmap_bytes_to_qpixmap_buffer, optimize_char_boxes, batch_crop_qimage)；
    失败返回 (None, None, None)。所有 import 在函数内部完成，不影响模块加载。
    """
    try:
        from native import has_native as _has_native
        if not _has_native():
            return None, None, None
        from native import (
            pixmap_bytes_to_qpixmap_buffer,
            optimize_char_boxes,
            batch_crop_qimage,
        )
        return pixmap_bytes_to_qpixmap_buffer, optimize_char_boxes, batch_crop_qimage
    except Exception:
        return None, None, None


class OCREngine:
    """基于 RapidOCR 的 OCR 识别引擎，提供 PDF 文档的文字识别与结构化处理能力。

    该引擎封装了 RapidOCR（PP-OCRv6 模型 + ONNXRuntime 引擎）的文本检测和文字识别流程，
    支持逐页识别 PDF 并将结果按行、字符两级粒度进行结构化存储。识别结果可
    保存为 JSON 文件，也可从文件加载，并支持按字符文本分组和构建行级数据
    以供后续校对流程使用。

    依赖:
        rapidocr (EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR): OCR 识别引擎
        models.data_models (CharSlice, LineSlice, flatten_bbox): 数据模型

    调用关系:
        被 MainWindow.__init__ 和 OCRPrepareWindow.__init__ 实例化
    """

    def __init__(self):
        """初始化 OCR 引擎实例。

        使用 PP-OCRv6 模型配置检测（Det）和识别（Rec）子模块，
        采用 ONNXRuntime 引擎。GPU 可用时使用 MEDIUM 模型，否则回退到 SMALL 模型。

        依赖:
            rapidocr.EngineType: 引擎类型枚举
            rapidocr.LangDet: 检测模块语言类型枚举
            rapidocr.LangRec: 识别模块语言类型枚举
            rapidocr.ModelType: 模型类型枚举
            rapidocr.OCRVersion: OCR 版本枚举
            rapidocr.RapidOCR: OCR 引擎主类
            onnxruntime: 用于检测 CUDA 可用性

        调用关系:
            被 MainWindow.__init__ 和 OCRPrepareWindow.__init__ 调用
        """
        import onnxruntime as ort
        import sys as _sys

        def _is_cuda_really_available():
            """检测 CUDA 是否真正可用。

            ort.get_available_providers() 可能返回 CUDAExecutionProvider
            即使 CUDA 运行时 DLL 缺失（如 cublasLt64_12.dll），需要额外验证。
            """
            if 'CUDAExecutionProvider' not in ort.get_available_providers():
                return False
            # Windows: 检查关键 CUDA DLL 是否可加载
            if _sys.platform == 'win32':
                import ctypes
                import os as _os
                # 尝试直接加载
                try:
                    ctypes.WinDLL('cublasLt64_12.dll')
                    return True
                except OSError:
                    pass
                # 直接加载失败时，添加 CUDA DLL 搜索路径后重试
                # torch 捆绑的 CUDA DLL 在 torch/lib，通过 CUDA_PATH junction 也可访问
                _dll_dirs = []
                _cuda_path = _os.environ.get('CUDA_PATH', '')
                if _cuda_path:
                    _bin = _os.path.join(_cuda_path, 'bin')
                    if _os.path.isdir(_bin):
                        _dll_dirs.append(_bin)
                try:
                    import torch as _torch
                    _torch_lib = _os.path.join(_os.path.dirname(_torch.__file__), 'lib')
                    if _os.path.isdir(_torch_lib) and _torch_lib not in _dll_dirs:
                        _dll_dirs.append(_torch_lib)
                except (ImportError, OSError):
                    pass
                for _d in _dll_dirs:
                    try:
                        _os.add_dll_directory(_d)
                    except OSError:
                        pass
                try:
                    ctypes.WinDLL('cublasLt64_12.dll')
                    return True
                except OSError:
                    return False
            return True

        # GPU 可用时使用 MEDIUM 模型，否则回退到 SMALL 模型（CPU 上 MEDIUM 过慢）
        _has_cuda = _is_cuda_really_available()
        _model_type = ModelType.MEDIUM if _has_cuda else ModelType.SMALL

        params = {
            "EngineConfig.onnxruntime.use_cuda": _has_cuda,
            # cuDNN 9.9.0 在 sm_86 (RTX 30 系列) 上 EXHAUSTIVE 搜索会触发
            # HEURISTIC_QUERY_FAILED，改为 DEFAULT 避免该 bug 同时保留 GPU 加速
            "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "DEFAULT",
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": _model_type,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            # DBNet 检测参数调优：limit_side_len=2880 匹配 A4@300DPI 高度(约2905-2970px)避免过度缩放导致下半页漏检；降低 box_thresh 和提高 unclip_ratio 以减少漏行
            "Det.box_thresh": 0.4,
            "Det.unclip_ratio": 1.8,
            "Det.max_candidates": 3000,
            "Det.use_dilation": True,
            "Det.limit_side_len": 2880,
            "Det.limit_type": "max",
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.lang_type": LangRec.CH,
            "Rec.model_type": _model_type,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
        }
        self.engine = RapidOCR(params=params)
        self._engine_params = params  # 保留参数供线程局部引擎创建使用
        self.results = None
        self.output_dir = None
        # PDF 渲染 DPI，默认 300（相比 v5 的 200，小字号行高提升 1.5 倍）
        self.dpi = 300

    def _recognize_page(self, page_image, page_idx: int, output_callback=None):
        """识别单页图像，提取行级和字符级识别结果。

        对单页图像执行 OCR 识别，获取每一行的文本、置信度和边界框，
        同时获取每个字符的文本、置信度和边界框。行 ID 和字符 ID
        在本页范围内从 0 开始递增。

        参数:
            page_image: 页面图像，通常为 PIL.Image 对象
            page_idx: 页面索引（从 0 开始），用于进度回调提示
            output_callback: 进度回调函数，接受 str 参数；若为 None 则
                不输出进度信息

        返回:
            tuple[list[dict], list[dict]]: 包含两个列表的元组:
                - lines: 行级识别结果列表，每个元素为字典，包含:
                    - line_id (int): 行 ID
                    - text (str): 行文本内容
                    - score (float): 行识别置信度
                    - box (list | None): 行边界框坐标
                - chars: 字符级识别结果列表，每个元素为字典，包含:
                    - char_id (int): 字符 ID
                    - line_id (int): 所属行 ID
                    - char (str): 字符文本
                    - score (float): 字符识别置信度
                    - box: 字符边界框坐标

        依赖:
            rapidocr.RapidOCR: 底层 OCR 识别引擎

        调用关系:
            被 OCREngine.run_ocr 内部调用（私有方法）
        """
        if output_callback:
            output_callback(f"正在识别第 {page_idx + 1} 页...")

        return self._recognize_page_with_engine(
            self.engine, page_image, page_idx, output_callback
        )

    def _recognize_page_with_engine(self, engine, page_image, page_idx, output_callback=None):
        """使用指定引擎识别单页（供线程局部引擎调用）。

        参数:
            engine: RapidOCR 引擎实例（线程局部创建）
            page_image: 页面图像
            page_idx: 页面索引
            output_callback: 进度回调函数

        返回:
            tuple[list[dict], list[dict]]: (lines, chars)
        """
        if output_callback:
            output_callback(f"正在识别第 {page_idx + 1} 页...")

        result = engine(page_image, return_word_box=True, return_single_char_box=True)

        lines = []
        chars = []
        line_id_counter = 0
        char_id_counter = 0

        num_lines = len(result.txts) if result.txts is not None else 0

        for i in range(num_lines):
            line_id = line_id_counter
            line_id_counter += 1

            line_box = result.boxes[i].tolist() if result.boxes is not None else None
            line_text = result.txts[i] if result.txts else ""
            line_score = float(result.scores[i]) if result.scores is not None else 0.0

            line_record = {
                "line_id": line_id,
                "text": line_text,
                "score": line_score,
                "box": line_box,
            }
            lines.append(line_record)

            if result.word_results is not None and i < len(result.word_results):
                word_line = result.word_results[i]
                for word_txt, word_score, word_box in word_line:
                    char_record = {
                        "char_id": char_id_counter,
                        "line_id": line_id,
                        "char": word_txt,
                        "score": float(word_score),
                        "box": word_box.tolist() if hasattr(word_box, 'tolist') else word_box,
                    }
                    chars.append(char_record)
                    char_id_counter += 1

        return lines, chars

    def _recognize_page_batch(self, page_images_with_idx, output_callback=None):
        """并发识别多页，每个线程使用独立的 RapidOCR 实例。

        RapidOCR 不是线程安全的，共享同一实例会导致 box 坐标污染
        （返回错误页面的坐标）。使用 threading.local() 为每个线程
        创建独立的引擎实例，确保并发安全。

        参数:
            page_images_with_idx: (page_idx, page_image) 元组列表
            output_callback: 进度回调函数

        返回:
            dict: {page_idx: (lines, chars)} 映射
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 线程局部存储：每个线程持有独立的 RapidOCR 实例
        _local = threading.local()

        def _get_thread_engine():
            """获取当前线程的 RapidOCR 实例，首次调用时创建。"""
            if not hasattr(_local, 'engine'):
                _local.engine = RapidOCR(params=self._engine_params)
            return _local.engine

        def _worker(page_image, page_idx):
            """worker 线程函数：使用线程局部引擎识别单页。"""
            engine = _get_thread_engine()
            return self._recognize_page_with_engine(
                engine, page_image, page_idx, None
            )

        results = {}
        try:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {}
                for page_idx, page_image in page_images_with_idx:
                    future = executor.submit(_worker, page_image, page_idx)
                    futures[future] = page_idx

                for future in as_completed(futures):
                    page_idx = futures[future]
                    results[page_idx] = future.result()
                    if output_callback:
                        output_callback(f"第 {page_idx + 1} 页识别完成")
        except Exception:
            # 回退：顺序执行（使用主线程的 self.engine）
            results = {}
            for page_idx, page_image in page_images_with_idx:
                results[page_idx] = self._recognize_page(
                    page_image, page_idx, output_callback
                )

        return results

    def _offset_box(self, box, dx, dy):
        """将边界框坐标偏移 (dx, dy)。"""
        if isinstance(box, list) and len(box) == 4 and all(isinstance(p, list) for p in box):
            return [[p[0] + dx, p[1] + dy] for p in box]
        elif isinstance(box, list) and len(box) == 4:
            return [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]
        return box

    def _boxes_overlap(self, box1_flat, box2_flat):
        """判断两个 [x1, y1, x2, y2] 格式的框是否有交集。"""
        x1 = max(box1_flat[0], box2_flat[0])
        y1 = max(box1_flat[1], box2_flat[1])
        x2 = min(box1_flat[2], box2_flat[2])
        y2 = min(box1_flat[3], box2_flat[3])
        return x1 < x2 and y1 < y2

    def run_ocr(self, pdf_path: str, output_dir: str = None, output_callback=None, regions: dict = None) -> tuple:
        """对 PDF 所有页进行 OCR 识别，并将结果保存为 JSON 文件。

        将 PDF 转换为图像后逐页执行 OCR 识别，对每页的行 ID 和字符 ID
        进行全局偏移以保证跨页唯一性，同时为每条记录添加页码信息。识别
        完成后将行级和字符级结果分别保存为 lines.json 和 chars.json。

        当 regions 参数不为 None 且非空时，仅对指定页面中框选的区域进行
        识别：对每个框区域裁剪页面图像后执行 OCR，并将裁剪图像的识别结果
        坐标映射回整页绝对坐标。不在 regions 中的页面将被跳过。

        参数:
            pdf_path: PDF 文件的路径
            output_dir: 输出目录路径；若为 None 则自动创建临时目录
            output_callback: 进度回调函数，接受 str 参数；若为 None 则
                不输出进度信息
            regions: 区域限制字典，键为页码索引（int），值为该页的框列表，
                每个框为 [x1, y1, x2, y2] 格式的坐标列表；若为 None 或空
                则对全部页面进行整页识别

        DPI 说明:
            使用 self.dpi（默认 300）渲染 PDF 为图像

        返回:
            tuple[list[dict], list[dict]]: 包含两个列表的元组:
                - lines: 全部页面的行级识别结果（含 page_num 字段）
                - chars: 全部页面的字符级识别结果（含 page_num 字段）

        异常:
            无显式异常抛出，但可能因 PDF 文件不存在或图像转换失败而
            由底层依赖抛出异常

        依赖:
            pdf_processor.PDFProcessor: PDF 转图像处理器
            OCREngine._recognize_page: 单页识别方法
            OCREngine._offset_box: 边界框坐标偏移方法

        调用关系:
            被 OCRWorker.run 调用
        """
        from pdf_processor import PDFProcessor

        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="rapidocr_")
        self.output_dir = output_dir

        pdf_processor = PDFProcessor()
        page_images = pdf_processor.convert_to_images(pdf_path, dpi=self.dpi)

        if output_callback:
            output_callback(f"共 {len(page_images)} 页，开始识别...")

        all_lines = []
        all_chars = []
        global_line_offset = 0
        global_char_offset = 0

        pages_to_process = []
        for page_idx, page_image in enumerate(page_images):
            if regions is not None and len(regions) > 0:
                page_regions = regions.get(page_idx, [])
                if not page_regions:
                    continue
            pages_to_process.append((page_idx, page_image))

        batch_results = self._recognize_page_batch(pages_to_process, output_callback)

        for page_idx, page_image in enumerate(page_images):
            if page_idx not in batch_results:
                continue

            page_lines, page_chars = batch_results[page_idx]

            if regions is not None and len(regions) > 0:
                page_regions = regions.get(page_idx, [])

                filtered_lines = []
                filtered_line_ids = set()
                for line in page_lines:
                    line_bbox = flatten_bbox(line.get("box", [0, 0, 0, 0]))
                    for region_bbox in page_regions:
                        if self._boxes_overlap(line_bbox, region_bbox):
                            filtered_lines.append(line)
                            filtered_line_ids.add(line.get("line_id", -1))
                            break

                filtered_chars = []
                for char in page_chars:
                    if char.get("line_id", -1) in filtered_line_ids:
                        filtered_chars.append(char)

                for line in filtered_lines:
                    line["line_id"] += global_line_offset
                for char in filtered_chars:
                    char["line_id"] += global_line_offset
                    char["char_id"] += global_char_offset

                for line in filtered_lines:
                    line["page_num"] = page_idx
                for char in filtered_chars:
                    char["page_num"] = page_idx

                all_lines.extend(filtered_lines)
                all_chars.extend(filtered_chars)

                if filtered_lines:
                    global_line_offset += max(l["line_id"] for l in filtered_lines) + 1
                if filtered_chars:
                    global_char_offset += max(c["char_id"] for c in filtered_chars) + 1
            else:
                for line in page_lines:
                    line["line_id"] += global_line_offset
                for char in page_chars:
                    char["line_id"] += global_line_offset
                    char["char_id"] += global_char_offset

                for line in page_lines:
                    line["page_num"] = page_idx
                for char in page_chars:
                    char["page_num"] = page_idx

                all_lines.extend(page_lines)
                all_chars.extend(page_chars)

                if page_lines:
                    global_line_offset += max(l["line_id"] for l in page_lines) + 1
                if page_chars:
                    global_char_offset += max(c["char_id"] for c in page_chars) + 1

        # 行合并后处理：DBSCAN 同基线合并，修复空格导致的行分割
        try:
            from ocr_engine.line_merger import merge_lines
            if output_callback:
                output_callback("正在执行行合并后处理...")
            all_lines, all_chars = merge_lines(all_lines, all_chars)
            if output_callback:
                output_callback(f"行合并完成，共 {len(all_lines)} 行 {len(all_chars)} 字符")
        except Exception as e:
            if output_callback:
                output_callback(f"行合并失败，跳过: {e}")

        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        json_dir = os.path.join(output_dir, pdf_basename)
        os.makedirs(json_dir, exist_ok=True)

        lines_path = os.path.join(json_dir, "lines.json")
        chars_path = os.path.join(json_dir, "chars.json")

        with open(lines_path, "w", encoding="utf-8") as f:
            json.dump(all_lines, f, ensure_ascii=False, indent=2)
        with open(chars_path, "w", encoding="utf-8") as f:
            json.dump(all_chars, f, ensure_ascii=False)

        self.results = (all_lines, all_chars)

        # 优化字符边界框，保存为 newchar.json
        if output_callback:
            output_callback("正在优化字符边界框...")
        try:
            self._optimize_char_boxes(page_images, all_chars, json_dir)
            if output_callback:
                output_callback("字符边界框优化完成，已保存为 newchar.json")
        except Exception as e:
            if output_callback:
                output_callback(f"字符边界框优化失败: {e}")

        if output_callback:
            # 复制原PDF到JSON输出文件夹
            try:
                import shutil
                shutil.copy2(pdf_path, os.path.join(json_dir, os.path.basename(pdf_path)))
            except Exception:
                pass
            output_callback(f"识别完成！结果已保存至: {json_dir}")

        return self.results

    def _optimize_char_boxes(self, page_images, all_chars, json_dir):
        """优化字符边界框，使四边尽量经过纯白区域。

        对每个字符框的四条边独立优化，在±0.5倍边长范围内寻找
        非白像素最少的位置，避免截断文字或多截相邻字。

        结果保存为 newchar.json。
        """
        import numpy as np

        if not all_chars:
            return

        # 按页分组
        chars_by_page = {}
        for char in all_chars:
            page = char.get("page_num", 0)
            if page not in chars_by_page:
                chars_by_page[page] = []
            chars_by_page[page].append(char)

        WHITE_THRESHOLD = 200

        for page_num, chars_on_page in chars_by_page.items():
            if page_num >= len(page_images):
                continue

            img = page_images[page_num]
            img_array = np.array(img)
            img_h, img_w = img_array.shape[:2]
            mask = np.any(img_array < WHITE_THRESHOLD, axis=2)

            # H2: 尝试 native 批量优化
            native_results = None
            try:
                _, optimize_char_boxes_native, _ = _try_native()
                if optimize_char_boxes_native is not None:
                    native_results = optimize_char_boxes_native(
                        mask.astype(np.uint8), chars_on_page
                    )
            except Exception:
                native_results = None

            if native_results is not None and len(native_results) == len(chars_on_page):
                # 使用 native 结果更新 box（valid 时 box 已是 4 角点格式）
                for char, res in zip(chars_on_page, native_results):
                    if res.get("valid"):
                        char["box"] = res.get("box")
            else:
                # Fallback: 原有 numpy 逐字符优化
                for char in chars_on_page:
                    box = char.get("box", [])
                    if len(box) != 4:
                        continue

                    # 展平为 [x1, y1, x2, y2]
                    xs = [pt[0] for pt in box]
                    ys = [pt[1] for pt in box]
                    x1, y1 = min(xs), min(ys)
                    x2, y2 = max(xs), max(ys)

                    w = x2 - x1
                    h = y2 - y1
                    if w <= 0 or h <= 0:
                        continue

                    # 裁剪到图像边界
                    x1_c = max(0, int(round(x1)))
                    y1_c = max(0, int(round(y1)))
                    x2_c = min(img_w, int(round(x2)))
                    y2_c = min(img_h, int(round(y2)))

                    # 优化四条边
                    new_x1 = self._optimize_edge_x(mask, x1, y1_c, y2_c, w, img_w)
                    new_x2 = self._optimize_edge_x(mask, x2, y1_c, y2_c, w, img_w)
                    new_y1 = self._optimize_edge_y(mask, y1, x1_c, x2_c, h, img_h)
                    new_y2 = self._optimize_edge_y(mask, y2, x1_c, x2_c, h, img_h)

                    # 验证有效性
                    if new_x1 >= new_x2 or new_y1 >= new_y2:
                        continue

                    # 转回4角点格式
                    char["box"] = [
                        [new_x1, new_y1],
                        [new_x2, new_y1],
                        [new_x2, new_y2],
                        [new_x1, new_y2],
                    ]

        # 保存为 newchar.json
        newchar_path = os.path.join(json_dir, "newchar.json")
        with open(newchar_path, "w", encoding="utf-8") as f:
            json.dump(all_chars, f, ensure_ascii=False)

    def _optimize_edge_x(self, mask, orig_x, y1, y2, edge_len, img_w):
        """优化垂直边（左/右边）的x位置。

        在 orig_x ± 0.5*edge_len 范围内搜索，找到经过非白像素最少的列位置。

        参数:
            mask: 非白像素掩码（2D布尔数组）
            orig_x: 原始x坐标
            y1, y2: 边的y范围（已裁剪到图像边界）
            edge_len: 边长（用于计算搜索范围）
            img_w: 图像宽度

        返回:
            优化后的x坐标
        """
        import numpy as np

        half = edge_len / 2
        search_start = max(0, int(orig_x - half))
        search_end = min(img_w, int(orig_x + half) + 1)

        if search_end <= search_start or y2 <= y1:
            return orig_x

        # 向量化计算：一次性获取所有候选列的非白像素数
        col_sums = mask[y1:y2, search_start:search_end].sum(axis=0)

        orig_idx = int(round(orig_x)) - search_start
        if orig_idx < 0:
            orig_idx = 0
        elif orig_idx >= len(col_sums):
            orig_idx = len(col_sums) - 1

        min_count = col_sums.min()

        # 原始位置已是最优则保持
        if col_sums[orig_idx] == min_count:
            return orig_x

        # 找所有最小值位置，选最接近原始位置的
        min_indices = np.where(col_sums == min_count)[0]
        best_idx = min_indices[np.argmin(np.abs(min_indices - orig_idx))]

        return float(search_start + best_idx)

    def _optimize_edge_y(self, mask, orig_y, x1, x2, edge_len, img_h):
        """优化水平边（上/下边）的y位置。

        在 orig_y ± 0.5*edge_len 范围内搜索，找到经过非白像素最少的行位置。

        参数:
            mask: 非白像素掩码（2D布尔数组）
            orig_y: 原始y坐标
            x1, x2: 边的x范围（已裁剪到图像边界）
            edge_len: 边长（用于计算搜索范围）
            img_h: 图像高度

        返回:
            优化后的y坐标
        """
        import numpy as np

        half = edge_len / 2
        search_start = max(0, int(orig_y - half))
        search_end = min(img_h, int(orig_y + half) + 1)

        if search_end <= search_start or x2 <= x1:
            return orig_y

        # 向量化计算：一次性获取所有候选行的非白像素数
        row_sums = mask[search_start:search_end, x1:x2].sum(axis=1)

        orig_idx = int(round(orig_y)) - search_start
        if orig_idx < 0:
            orig_idx = 0
        elif orig_idx >= len(row_sums):
            orig_idx = len(row_sums) - 1

        min_count = row_sums.min()

        if row_sums[orig_idx] == min_count:
            return orig_y

        min_indices = np.where(row_sums == min_count)[0]
        best_idx = min_indices[np.argmin(np.abs(min_indices - orig_idx))]

        return float(search_start + best_idx)

    def load_results_from_file(self, lines_json_path: str, chars_json_path: str = None) -> tuple:
        """从 JSON 文件加载 OCR 识别结果。

        读取之前保存的 lines.json 和 chars.json 文件，将结果加载到
        内存并缓存至 self.results。若未指定字符结果文件路径，则自动
        从行结果文件的同级目录下查找 chars.json。

        参数:
            lines_json_path: 行级结果文件（lines.json）的路径
            chars_json_path: 字符级结果文件（chars.json）的路径；若为
                None 则自动推断为 lines_json_path 同目录下的 chars.json

        返回:
            tuple[list[dict], list[dict]]: 包含两个列表的元组:
                - lines: 行级识别结果列表
                - chars: 字符级识别结果列表

        异常:
            RuntimeError: 当指定的 JSON 文件不存在时抛出

        依赖:
            无外部依赖，仅使用标准库 json 和 os

        调用关系:
            被 DataLoadWorker.run 调用
        """
        if not os.path.exists(lines_json_path):
            raise RuntimeError(f"lines.json 不存在: {lines_json_path}")

        if chars_json_path is None:
            dir_path = os.path.dirname(lines_json_path)
            chars_json_path = os.path.join(dir_path, "chars.json")

        if not os.path.exists(chars_json_path):
            raise RuntimeError(f"chars.json 不存在: {chars_json_path}")

        with open(lines_json_path, "r", encoding="utf-8") as f:
            lines = json.load(f)
        with open(chars_json_path, "r", encoding="utf-8") as f:
            chars = json.load(f)

        self.results = (lines, chars)
        return self.results

    def parse_and_group(self, results: tuple, page_images: list) -> dict:
        """将 OCR 结果按字符文本分组，构建字符切片映射。

        遍历 OCR 识别结果中的所有字符，将每个字符的边界框转换为扁平
        格式，从对应页面图像中裁剪出字符区域（带 6 像素边距），并按
        字符文本内容进行分组，生成 CharSlice 对象映射。

        参数:
            results: OCR 识别结果元组 (lines, chars)，由 run_ocr 或
                load_results_from_file 返回
            page_images: 页面图像列表，索引与 results 中的 page_num
                对应，通常为 PIL.Image 对象列表

        返回:
            dict[str, list[CharSlice]]: 以字符文本为键、CharSlice 列表
                为值的字典。每个 CharSlice 包含页码、边界框、裁剪图像、
                文本内容、行 ID 和字符 ID。

        依赖:
            models.data_models.CharSlice: 字符切片数据模型
            models.data_models.flatten_bbox: 边界框坐标扁平化工具

        调用关系:
            被 DataLoadWorker.run 调用
        """
        lines, chars = results
        grouped = {}
        padding = 6

        # 第一遍：收集每个字符的裁切信息
        char_infos = []
        for char_data in chars:
            char_text = char_data.get("char", "")
            if not char_text:
                char_infos.append(None)
                continue

            page_num = char_data.get("page_num", 0)
            bbox = char_data.get("box", [0, 0, 0, 0])
            line_id = char_data.get("line_id", -1)
            char_id = char_data.get("char_id", -1)

            bbox_flat = flatten_bbox(bbox)

            page_image = page_images[page_num] if page_num < len(page_images) else None
            img_width, img_height = page_image.size if page_image else (0, 0)

            crop_x1 = max(0, int(round(bbox_flat[0])) - padding)
            crop_y1 = max(0, int(round(bbox_flat[1])) - padding)
            crop_x2 = min(img_width, int(round(bbox_flat[2])) + padding)
            crop_y2 = min(img_height, int(round(bbox_flat[3])) + padding)

            char_infos.append({
                "char_text": char_text,
                "page_num": page_num,
                "bbox_flat": bbox_flat,
                "line_id": line_id,
                "char_id": char_id,
                "page_image": page_image,
                "crop": (crop_x1, crop_y1, crop_x2, crop_y2),
                "valid": bool(page_image and crop_x2 > crop_x1 and crop_y2 > crop_y1),
                "image": None,
            })

        # 第二遍：按页批量裁切（H3 native，失败则逐个 PIL crop）
        page_groups = {}
        for i, info in enumerate(char_infos):
            if info is not None and info["valid"]:
                page_groups.setdefault(info["page_num"], []).append(i)

        for page_num, indices in page_groups.items():
            page_image = char_infos[indices[0]]["page_image"]
            native_images = None
            try:
                _, _, batch_crop_qimage = _try_native()
                if batch_crop_qimage is not None and page_image is not None:
                    w, h = page_image.size
                    if page_image.mode == "RGBA":
                        page_rgba = page_image.tobytes("raw", "RGBA")
                    else:
                        page_rgba = page_image.convert("RGBA").tobytes("raw", "RGBA")
                    bboxes = []
                    for i in indices:
                        bf = char_infos[i]["bbox_flat"]
                        bboxes.append([
                            int(round(bf[0])), int(round(bf[1])),
                            int(round(bf[2])), int(round(bf[3])),
                        ])
                    native_results = batch_crop_qimage(page_rgba, w, h, bboxes, padding)
                    if native_results is not None and len(native_results) == len(indices):
                        from PIL import Image as _PILImage
                        native_images = []
                        for j, buf in enumerate(native_results):
                            i = indices[j]
                            cx1, cy1, cx2, cy2 = char_infos[i]["crop"]
                            cw, ch = cx2 - cx1, cy2 - cy1
                            if buf:
                                try:
                                    img = _PILImage.frombytes("RGBA", (cw, ch), buf)
                                    if img.mode != page_image.mode:
                                        img = img.convert(page_image.mode)
                                    native_images.append(img)
                                except Exception:
                                    native_images.append(None)
                            else:
                                native_images.append(None)
            except Exception:
                native_images = None

            # 分配裁切结果（native 失败或单张为空时回落到 PIL crop）
            for j, i in enumerate(indices):
                if native_images is not None and native_images[j] is not None:
                    char_infos[i]["image"] = native_images[j]
                else:
                    char_infos[i]["image"] = char_infos[i]["page_image"].crop(
                        char_infos[i]["crop"]
                    )

        # 第三遍：构建 CharSlice 并分组（保持原序）
        for info in char_infos:
            if info is None:
                continue
            cropped_image = info["image"] if info["valid"] else None
            char_slice = CharSlice(
                page_num=info["page_num"],
                bbox=list(info["bbox_flat"]),
                image=cropped_image,
                text=info["char_text"],
                line_id=info["line_id"],
                char_id=info["char_id"],
            )

            if info["char_text"] not in grouped:
                grouped[info["char_text"]] = []
            grouped[info["char_text"]].append(char_slice)

        return grouped

    def build_line_data(self, results: tuple, page_images: list, char_slices: dict = None) -> dict:
        """构建纵校所需的行级数据结构。

        将 OCR 识别结果按页面和行进行组织，为每一行构建 LineSlice 对象。
        若提供了 char_slices 参数，则使用其中已校对的字符数据更新行内
        字符列表和行文本；否则使用原始 OCR 识别结果。同时从页面图像中
        裁剪出每行的图像区域。

        参数:
            results: OCR 识别结果元组 (lines, chars)，由 run_ocr 或
                load_results_from_file 返回
            page_images: 页面图像列表，索引与 results 中的 page_num
                对应，通常为 PIL.Image 对象列表
            char_slices: 按字符文本分组的 CharSlice 映射，由
                parse_and_group 方法返回；若为 None 则使用原始 OCR
                字符数据

        返回:
            dict[int, list[LineSlice]]: 以页码为键、LineSlice 列表为值
                的字典。每个 LineSlice 包含页码、边界框、多边形坐标、
                行文本、置信度、字符列表和行图像。

        依赖:
            models.data_models.LineSlice: 行切片数据模型
            models.data_models.flatten_bbox: 边界框坐标扁平化工具

        调用关系:
            被 MainWindow._on_vertical_finished 调用
        """
        lines, chars = results
        char_lookup = {}
        if char_slices:
            for char_text, slices in char_slices.items():
                for cs in slices:
                    key = (cs.page_num, cs.line_id, cs.char_id)
                    char_lookup[key] = cs

        page_lines = {}

        line_chars_map = {}
        for char_data in chars:
            line_id = char_data.get("line_id", -1)
            if line_id not in line_chars_map:
                line_chars_map[line_id] = []
            line_chars_map[line_id].append(char_data)

        page_lines_map = {}
        for line in lines:
            page_num = line.get("page_num", 0)
            if page_num not in page_lines_map:
                page_lines_map[page_num] = []
            page_lines_map[page_num].append(line)

        for page_num, page_lines_list in page_lines_map.items():
            page_image = page_images[page_num] if page_num < len(page_images) else None
            lines_result = []

            # H3: 预计算行 bbox 与裁切坐标，批量裁切
            line_bboxes_flat = []
            line_crop_coords = []
            for line in page_lines_list:
                line_box = line.get("box", [0, 0, 0, 0])
                line_bbox = flatten_bbox(line_box)
                line_bboxes_flat.append(line_bbox)
                if page_image:
                    x1 = max(0, int(round(line_bbox[0])))
                    y1 = max(0, int(round(line_bbox[1])))
                    x2 = min(page_image.size[0], int(round(line_bbox[2])))
                    y2 = min(page_image.size[1], int(round(line_bbox[3])))
                else:
                    x1 = y1 = x2 = y2 = 0
                line_crop_coords.append((x1, y1, x2, y2))

            # 尝试 native 批量裁切（padding=0）
            line_images_native = None
            try:
                _, _, batch_crop_qimage = _try_native()
                if batch_crop_qimage is not None and page_image is not None:
                    w, h = page_image.size
                    if page_image.mode == "RGBA":
                        page_rgba = page_image.tobytes("raw", "RGBA")
                    else:
                        page_rgba = page_image.convert("RGBA").tobytes("raw", "RGBA")
                    valid_bboxes = []
                    valid_indices = []
                    for idx, (x1, y1, x2, y2) in enumerate(line_crop_coords):
                        if x2 > x1 and y2 > y1:
                            lb = line_bboxes_flat[idx]
                            valid_bboxes.append([
                                int(round(lb[0])), int(round(lb[1])),
                                int(round(lb[2])), int(round(lb[3])),
                            ])
                            valid_indices.append(idx)
                    if valid_bboxes:
                        native_results = batch_crop_qimage(page_rgba, w, h, valid_bboxes, 0)
                        if native_results is not None and len(native_results) == len(valid_bboxes):
                            from PIL import Image as _PILImage
                            line_images_native = {}
                            for j, buf in enumerate(native_results):
                                idx = valid_indices[j]
                                x1, y1, x2, y2 = line_crop_coords[idx]
                                cw, ch = x2 - x1, y2 - y1
                                if buf:
                                    try:
                                        img = _PILImage.frombytes("RGBA", (cw, ch), buf)
                                        if img.mode != page_image.mode:
                                            img = img.convert(page_image.mode)
                                        line_images_native[idx] = img
                                    except Exception:
                                        line_images_native[idx] = None
                                else:
                                    line_images_native[idx] = None
            except Exception:
                line_images_native = None

            for line_idx, line in enumerate(page_lines_list):
                line_id = line.get("line_id", -1)
                line_text = line.get("text", "")
                line_score = line.get("score", 0)

                line_bbox = line_bboxes_flat[line_idx]

                updated_chars = []
                updated_text_parts = []
                line_char_list = line_chars_map.get(line_id, [])

                for char_data in line_char_list:
                    key = (page_num, line_id, char_data.get("char_id", -1))
                    if key in char_lookup:
                        cs = char_lookup[key]
                        updated_chars.append({
                            "text": cs.text,
                            "bbox": cs.bbox,
                            "bbox_valid": True,
                        })
                        if cs.text:
                            updated_text_parts.append(cs.text)
                    else:
                        char_bbox = char_data.get("box", [0, 0, 0, 0])
                        char_bbox_flat = flatten_bbox(char_bbox)

                        updated_chars.append({
                            "text": char_data.get("char", ""),
                            "bbox": char_bbox_flat,
                            "bbox_valid": True,
                        })
                        if char_data.get("char", ""):
                            updated_text_parts.append(char_data["char"])

                if char_slices:
                    line_text = "".join(updated_text_parts)

                # 行图像裁切：优先 native，失败则 PIL crop
                x1, y1, x2, y2 = line_crop_coords[line_idx]
                line_image = None
                if page_image and x2 > x1 and y2 > y1:
                    if (line_images_native is not None
                            and line_idx in line_images_native
                            and line_images_native[line_idx] is not None):
                        line_image = line_images_native[line_idx]
                    else:
                        line_image = page_image.crop((x1, y1, x2, y2))

                line_slice = LineSlice(
                    page_num=page_num,
                    bbox=list(line_bbox),
                    polygon=[],
                    text=line_text,
                    confidence=line_score,
                    chars=updated_chars,
                    image=line_image,
                )
                lines_result.append(line_slice)

            page_lines[page_num] = lines_result

        return page_lines
