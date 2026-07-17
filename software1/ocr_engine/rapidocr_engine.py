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

        # 抑制 ONNX Runtime 默认日志器的 WARNING 级别输出
        # LOGS_DEFAULT 宏不受 session 级别 log_severity_level 控制，需单独设置
        # 0=VERBOSE, 1=INFO, 2=WARNING, 3=ERROR, 4=FATAL
        ort.set_default_logger_severity(3)

        def _is_cuda_really_available():
            """检测 CUDA 是否真正可用。

            ort.get_available_providers() 可能返回 CUDAExecutionProvider
            即使 CUDA 运行时 DLL 缺失（如 cublasLt64_12.dll），需要额外验证。
            """
            if 'CUDAExecutionProvider' not in ort.get_available_providers():
                return False
            # Windows: 确保 CUDA DLL 路径已设置后检查关键 DLL 是否可加载
            if _sys.platform == 'win32':
                import ctypes
                from cuda_dll_setup import setup_cuda_dll_paths
                setup_cuda_dll_paths()
                try:
                    ctypes.WinDLL('cublasLt64_12.dll')
                    return True
                except OSError:
                    return False
            return True

        # GPU 可用时使用 MEDIUM 模型，否则回退到 SMALL 模型（CPU 上 MEDIUM 过慢）
        _has_cuda = _is_cuda_really_available()
        _model_type = ModelType.MEDIUM if _has_cuda else ModelType.SMALL
        self._has_cuda = _has_cuda
        self._model_type = _model_type
        self._model_type_name = "MEDIUM" if _has_cuda else "SMALL"

        params = {
            "EngineConfig.onnxruntime.use_cuda": _has_cuda,
            # cuDNN 9.10.02 在 sm_86 (RTX 30 系列) 上：
            # - EXHAUSTIVE (HeurMode_t::B) 会触发 HEURISTIC_QUERY_FAILED
            # - DEFAULT (HeurMode_t::FALLBACK) 会触发 Fallback mode 警告且性能差
            # - HEURISTIC (HeurMode_t::A) 轻量启发式搜索，避免上述两个问题
            "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC",
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": _model_type,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            # DBNet 检测参数调优：limit_side_len=2880 匹配 A4@300DPI 高度(约2905-2970px)避免过度缩放导致下半页漏检；降低 box_thresh 以减少漏行
            # box_thresh 0.4→0.3：提高 DBNet 检测召回率，修复"组合 1.pdf"第12页整行漏检问题
            # unclip_ratio 1.8→1.5：1.8 会导致 DBNet 在竖排页旋转后将相邻列合并为一个检测框，
            # 整列文本被"吞掉"。1.5 是 PaddleOCR 官方默认值，调试证明能正确分离相邻列，
            # 修复"2.pdf"第1页"五，管理局財務會計處..."和"9.回數客票..."整列漏检问题。
            "Det.box_thresh": 0.3,
            "Det.unclip_ratio": 1.5,
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

    @staticmethod
    def _rotate_box_back(box, orig_w: int):
        """将旋转后图像上的 bbox 坐标逆变换回原坐标系。

        逆时针旋转 90 度的逆变换（PIL rotate(90, expand=True)）：
          原图尺寸 W×H，旋转后尺寸 H×W
          前向: 原图点 (x, y) → 旋转后点 (y, W-1-x)
          逆变换: 旋转后点 (x', y') → 原图点 (W-1-y', x')
          旋转后 bbox [x1',y1',x2',y2'] → 原图 [W-1-y2', x1', W-1-y1', x2']

        支持 4 角点格式 [[x1,y1],[x2,y1],[x2,y2],[x1,y2]] 和扁平 [x1,y1,x2,y2]。

        Args:
            box: 旋转后图像上的 bbox（4 角点 list 或扁平 list）
            orig_w: 原图宽度（旋转后图像高度）

        Returns:
            原坐标系下的同格式 bbox
        """
        if not box or len(box) == 0:
            return box

        # 4 角点格式 [[x,y],...]
        if isinstance(box[0], (list, tuple)) and len(box[0]) >= 2:
            rotated = []
            for pt in box:
                x, y = pt[0], pt[1]
                # 旋转后 (x',y') → 原图 (W-1-y', x')
                rotated.append([float(orig_w - 1 - y), float(x)])
            return rotated

        # 扁平格式 [x1,y1,x2,y2]
        if len(box) >= 4:
            x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
            return [float(orig_w - 1 - y2), float(x1), float(orig_w - 1 - y1), float(x2)]

        return box

    def _is_vertical_page_by_boxes(self, result) -> bool:
        """根据 OCR 结果的行 bbox 判断页面是否为竖排。

        统计 h>w 的 bbox 数量，若 >50% 则为竖排页。

        Args:
            result: RapidOCR 输出对象（含 boxes 属性）

        Returns:
            bool: 竖排页返回 True
        """
        if result.boxes is None or len(result.boxes) == 0:
            return False
        vert_count = 0
        total = len(result.boxes)
        for i in range(total):
            box = result.boxes[i]
            try:
                pts = box.tolist()
            except AttributeError:
                pts = box
            if not pts or len(pts) < 4:
                continue
            # 4 角点格式
            if isinstance(pts[0], (list, tuple)):
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                w = max(xs) - min(xs)
                h = max(ys) - min(ys)
            else:
                # 扁平格式
                w = pts[2] - pts[0]
                h = pts[3] - pts[1]
            if h > w:
                vert_count += 1
        return vert_count > total * 0.5

    def _detect_missed_in_rotated_chunks(self, engine, rotated_image, initial_result,
                                          output_callback=None, page_idx=0):
        """对旋转后图像进行分块 OCR 补检，检测主 OCR 漏检的文本行。

        DBNet 在整页旋转图像上可能漏检某些文本行（尤其竖排列转换为横排行后
        的某些区域）。将旋转后图像按 y 方向分成 2 个重叠块，分别 OCR，
        合并不与已有结果重叠的新检测。

        根因：DBNet 在大图上的检测召回率低于小图裁切，分块 OCR 能补检漏行。

        参数:
            engine: RapidOCR 引擎实例
            rotated_image: 整页逆时针旋转 90° 后的 PIL 图像
            initial_result: 主 OCR 的结果对象（旋转后坐标系）
            output_callback: 进度回调函数
            page_idx: 页面索引（用于日志）

        返回:
            list: [(text, score, box_in_rotated_coords, word_results_in_rotated_coords), ...]
                坐标均为旋转后页面坐标（未做 _rotate_box_back 逆变换）
        """
        import numpy as np
        from models.data_models import flatten_bbox

        if not initial_result or initial_result.boxes is None or len(initial_result.boxes) == 0:
            return []

        # 收集已有结果的扁平 bbox（旋转后坐标系），用于去重
        existing_flats = []
        for i in range(len(initial_result.boxes)):
            box = initial_result.boxes[i]
            try:
                box = box.tolist()
            except AttributeError:
                pass
            flat = flatten_bbox(box)
            if flat and len(flat) >= 4:
                existing_flats.append(flat)

        try:
            rotated_array = np.array(rotated_image)
        except Exception:
            return []

        rotated_h = rotated_array.shape[0]  # 旋转后图像高度 = 原图宽度

        # 分块策略：2 块，每块覆盖 60% 高度，中间 20% 重叠
        # 旋转后 y 方向对应原图 x 方向（列），分块即按列分区域补检
        chunk_count = 2
        overlap_ratio = 0.2
        chunk_height = int(rotated_h / chunk_count * (1 + overlap_ratio))

        from PIL import Image

        extra_results = []

        for c in range(chunk_count):
            if chunk_count == 1:
                y_start = 0
                y_end = rotated_h
            else:
                y_start = int(c * (rotated_h - chunk_height) / (chunk_count - 1))
                y_end = min(rotated_h, y_start + chunk_height)

            if y_end - y_start < 100:
                continue

            chunk_img = rotated_array[y_start:y_end, :]
            if chunk_img.size == 0:
                continue

            try:
                chunk_pil = Image.fromarray(chunk_img)
            except Exception:
                continue

            try:
                chunk_result = engine(
                    chunk_pil,
                    return_word_box=True,
                    return_single_char_box=True,
                )
            except Exception:
                continue

            if not chunk_result or not chunk_result.txts:
                continue

            for j in range(len(chunk_result.txts)):
                chunk_box = (
                    chunk_result.boxes[j].tolist()
                    if chunk_result.boxes is not None and j < len(chunk_result.boxes)
                    else None
                )
                if chunk_box is None:
                    continue

                # 转换到旋转后页面坐标（加 y 偏移）
                rotated_box = self._convert_gap_box_to_page(chunk_box, 0, y_start)
                rotated_flat = flatten_bbox(rotated_box)

                # 与已有结果去重（IoU > 0.5 视为重复）
                if self._is_duplicate_line(rotated_flat, existing_flats):
                    continue

                # 加入已有列表，避免后续块重复添加
                existing_flats.append(rotated_flat)

                # 收集 word_results（也转换到旋转后页面坐标）
                word_results_rotated = []
                if (chunk_result.word_results is not None
                        and j < len(chunk_result.word_results)):
                    for word_txt, word_score, word_box in chunk_result.word_results[j]:
                        wb = (
                            word_box.tolist()
                            if hasattr(word_box, "tolist")
                            else word_box
                        )
                        wb = self._convert_gap_box_to_page(wb, 0, y_start)
                        word_results_rotated.append((word_txt, word_score, wb))

                extra_results.append((
                    chunk_result.txts[j],
                    float(chunk_result.scores[j])
                    if chunk_result.scores is not None and j < len(chunk_result.scores)
                    else 0.5,
                    rotated_box,
                    word_results_rotated,
                ))

        if extra_results and output_callback:
            output_callback(
                f"第 {page_idx + 1} 页分块补检发现 {len(extra_results)} 行漏检文本"
            )

        return extra_results

    def _recognize_page_with_engine(self, engine, page_image, page_idx, output_callback=None):
        """使用指定引擎识别单页（供线程局部引擎调用）。

        对竖排页面（首次 OCR 检测到 h>w bbox 占多数）执行旋转 90 度预处理：
        将图像逆时针旋转后重新 OCR，坐标逆变换回原坐标系，让 DBNet 在横排
        文本上检测恢复正常召回率。横排页只 OCR 一次，无性能损失。

        竖排页额外执行分块补检：将旋转后图像按 y 方向分成 2 个重叠块分别 OCR，
        合并不与已有结果重叠的新检测，修复 DBNet 在大图上漏检整列文本的问题。

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

        # 竖排页面旋转预处理：DBNet 为横排设计，竖排页检测召回率低
        is_vertical = self._is_vertical_page_by_boxes(result)
        orig_w = 0
        extra_chunk_results = []
        if is_vertical:
            try:
                from PIL import Image as _PILImage
                orig_w, orig_h = page_image.size
                # 逆时针旋转 90 度（PIL rotate(90)）：原图左边变成上边，
                # 竖排列从右到左变成横排行从上到下（第一列在顶部，符合阅读顺序）
                rotated_image = page_image.rotate(90, expand=True)
                if output_callback:
                    output_callback(f"第 {page_idx + 1} 页检测为竖排，旋转后重新 OCR...")
                result = engine(rotated_image, return_word_box=True, return_single_char_box=True)
                # 标记需要在结果解析时做坐标逆变换
                _need_rotate_back = True

                # 分块补检：DBNet 在整页旋转图像上可能漏检某些列
                # 将旋转后图像按 y 分块分别 OCR，合并不重叠的新检测
                extra_chunk_results = self._detect_missed_in_rotated_chunks(
                    engine, rotated_image, result, output_callback, page_idx
                )
            except Exception as e:
                if output_callback:
                    output_callback(f"第 {page_idx + 1} 页旋转预处理失败: {e}，使用首次结果")
                # 旋转失败，重新 OCR 获取原始 result（上面已被覆盖）
                result = engine(page_image, return_word_box=True, return_single_char_box=True)
                _need_rotate_back = False
        else:
            _need_rotate_back = False

        lines = []
        chars = []
        line_id_counter = 0
        char_id_counter = 0

        num_lines = len(result.txts) if result.txts is not None else 0

        for i in range(num_lines):
            line_id = line_id_counter
            line_id_counter += 1

            line_box = result.boxes[i].tolist() if result.boxes is not None else None
            if _need_rotate_back and line_box is not None:
                line_box = self._rotate_box_back(line_box, orig_w)
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
                    wb = word_box.tolist() if hasattr(word_box, 'tolist') else word_box
                    if _need_rotate_back and wb is not None:
                        wb = self._rotate_box_back(wb, orig_w)
                    char_record = {
                        "char_id": char_id_counter,
                        "line_id": line_id,
                        "char": word_txt,
                        "score": float(word_score),
                        "box": wb,
                    }
                    chars.append(char_record)
                    char_id_counter += 1

        # 处理分块补检的额外结果（竖排页）
        # extra_chunk_results 中的 box 和 word_box 已在旋转后页面坐标系，
        # 需要通过 _rotate_box_back 逆变换回原图坐标系
        for text, score, rotated_box, rotated_word_results in extra_chunk_results:
            line_id = line_id_counter
            line_id_counter += 1

            line_box = (
                self._rotate_box_back(rotated_box, orig_w)
                if _need_rotate_back else rotated_box
            )
            line_record = {
                "line_id": line_id,
                "text": text,
                "score": score,
                "box": line_box,
            }
            lines.append(line_record)

            for word_txt, word_score, word_box in rotated_word_results:
                wb = (
                    self._rotate_box_back(word_box, orig_w)
                    if _need_rotate_back else word_box
                )
                char_record = {
                    "char_id": char_id_counter,
                    "line_id": line_id,
                    "char": word_txt,
                    "score": float(word_score),
                    "box": wb,
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

    def _convert_gap_box_to_page(self, gap_box, offset_x, offset_y):
        """将 gap 区域内的 box 坐标转换回页面坐标。

        gap_box 可能是多边形 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        或扁平格式 [x1, y1, x2, y2]。原样保持格式，仅做坐标偏移。

        参数:
            gap_box: gap 区域内识别出的边界框
            offset_x: x 方向偏移量（gap 区域左上角 x）
            offset_y: y 方向偏移量（gap 区域左上角 y）

        返回:
            偏移后的边界框，格式与输入一致
        """
        if gap_box is None:
            return None
        # 四点多边形格式
        if (isinstance(gap_box, list) and len(gap_box) == 4
                and all(isinstance(p, (list, tuple)) for p in gap_box)):
            return [[p[0] + offset_x, p[1] + offset_y] for p in gap_box]
        # 扁平格式 [x1, y1, x2, y2]
        if isinstance(gap_box, list) and len(gap_box) == 4:
            return [
                gap_box[0] + offset_x, gap_box[1] + offset_y,
                gap_box[2] + offset_x, gap_box[3] + offset_y,
            ]
        return gap_box

    def _is_duplicate_line(self, new_flat, existing_flats, iou_threshold=0.5):
        """判断新行的 bbox 是否与已有行显著重叠。

        参数:
            new_flat: 新行的扁平 bbox [x1, y1, x2, y2]
            existing_flats: 已有行的扁平 bbox 列表
            iou_threshold: IoU 阈值，超过则视为重复

        返回:
            bool: True 表示重复，应跳过
        """
        if not new_flat or len(new_flat) < 4:
            return False
        nx1, ny1, nx2, ny2 = new_flat[:4]
        narea = max(0, nx2 - nx1) * max(0, ny2 - ny1)
        if narea <= 0:
            return False
        for ef in existing_flats:
            if not ef or len(ef) < 4:
                continue
            ex1, ey1, ex2, ey2 = ef[:4]
            # 交集
            ix1 = max(nx1, ex1)
            iy1 = max(ny1, ey1)
            ix2 = min(nx2, ex2)
            iy2 = min(ny2, ey2)
            iw = max(0, ix2 - ix1)
            ih = max(0, iy2 - iy1)
            if iw <= 0 or ih <= 0:
                continue
            inter = iw * ih
            earea = max(0, ex2 - ex1) * max(0, ey2 - ey1)
            if earea <= 0:
                continue
            union = narea + earea - inter
            if union <= 0:
                continue
            iou = inter / union
            if iou > iou_threshold:
                return True
        return False

    def _detect_in_gap_region(self, img_array, gap_y1, gap_y2, gap_x1, gap_x2,
                               offset_x, offset_y, page_num, engine,
                               max_line_id, max_char_id, existing_flats,
                               is_vertical_page=False, rotated_page_array=None,
                               orig_w=0):
        """在指定 gap 区域裁切图像并重新 OCR 识别。

        辅助方法，被 _detect_and_fill_gaps 的页内间隙和边界间隙检测复用。
        对裁切区域调用 RapidOCR，将结果坐标转换回页面坐标，并与已有行去重。

        竖排页采用两种裁切策略：
        - **整页旋转后裁切**（推荐）：当 rotated_page_array 提供时使用。先将整页
          逆时针旋转 90°，再从旋转后图像裁切 gap 区域。产生与主 OCR 流程一致的
          像素，DBNet 检测召回率高。
        - **裁切后旋转**（回退）：未提供 rotated_page_array 时使用。先从原图裁切
          gap 区域，再逆时针旋转 90°。由于 PIL 裁切边界和插值差异，产生与整页
          旋转不同的像素，DBNet 可能漏检。

        参数:
            img_array: 页面图像 numpy 数组（原图）
            gap_y1, gap_y2: gap 区域的 y 范围（页面坐标）
            gap_x1, gap_x2: gap 区域的 x 范围（页面坐标）
            offset_x, offset_y: 坐标偏移量（通常等于 gap_x1, gap_y1）
            page_num: 当前页码
            engine: RapidOCR 引擎实例
            max_line_id: 当前最大 line_id（会被更新）
            max_char_id: 当前最大 char_id（会被更新）
            existing_flats: 已有行的扁平 bbox 列表，用于去重
            is_vertical_page: 是否为竖排页
            rotated_page_array: 整页逆时针旋转 90° 后的 numpy 数组（竖排页推荐提供）
            orig_w: 原图宽度（旋转后图像的高度），用于坐标逆变换

        返回:
            tuple: (new_lines, new_chars, max_line_id, max_char_id)
        """
        from PIL import Image
        from models.data_models import flatten_bbox

        if gap_y2 <= gap_y1 or gap_x2 <= gap_x1:
            return [], [], max_line_id, max_char_id

        # 竖排页且提供了旋转后整页图像：使用"整页旋转后裁切"方式
        # 该方式比"裁切后旋转"产生更准确的像素，DBNet 检测召回率更高
        # 根因：PIL 裁切边界和插值差异导致两种方式产生 21% 像素差异
        if is_vertical_page and rotated_page_array is not None and orig_w > 0:
            # 计算 gap 区域在旋转后图像中的坐标
            # 正向变换: 原图 (x, y) → 旋转后 (y, orig_w-1-x)
            # gap [gap_x1, gap_y1, gap_x2, gap_y2] →
            #   旋转后 x 范围: [gap_y1, gap_y2]
            #   旋转后 y 范围: [orig_w-1-gap_x2, orig_w-1-gap_x1]
            rot_x1 = int(gap_y1)
            rot_x2 = int(gap_y2)
            rot_y1 = max(0, int(orig_w - 1 - gap_x2))
            rot_y2 = min(rotated_page_array.shape[0],
                         max(0, int(orig_w - 1 - gap_x1)))

            if rot_y2 <= rot_y1 or rot_x2 <= rot_x1:
                return [], [], max_line_id, max_char_id

            gap_crop = rotated_page_array[rot_y1:rot_y2, rot_x1:rot_x2]
            if gap_crop.size == 0 or gap_crop.shape[0] < 5 or gap_crop.shape[1] < 5:
                return [], [], max_line_id, max_char_id

            try:
                gap_pil = Image.fromarray(gap_crop)
            except Exception as e:
                print(f"[GapDetect] 页面 {page_num} gap 图像创建失败: {e}")
                return [], [], max_line_id, max_char_id

            # 不需要额外旋转——裁切区域已是横排方向
            # 坐标变换链: OCR box → +(rot_x1, rot_y1) → 旋转后页面坐标
            #           → _rotate_box_back(box, orig_w) → 原图页面坐标
            _use_rotate_then_crop = True
        else:
            # 原有方式（横排页或回退）：裁切原图 → 旋转 → OCR
            gap_img = img_array[gap_y1:gap_y2, gap_x1:gap_x2]
            if gap_img.size == 0 or gap_img.shape[0] < 5 or gap_img.shape[1] < 5:
                return [], [], max_line_id, max_char_id

            try:
                gap_pil = Image.fromarray(gap_img)
            except Exception as e:
                print(f"[GapDetect] 页面 {page_num} gap 图像创建失败: {e}")
                return [], [], max_line_id, max_char_id

            gap_orig_w = gap_pil.size[0]
            if is_vertical_page:
                gap_pil = gap_pil.rotate(90, expand=True)  # 逆时针 90°

            _use_rotate_then_crop = False

        try:
            result = engine(
                gap_pil,
                return_word_box=True,
                return_single_char_box=True,
            )
        except Exception as e:
            print(f"[GapDetect] 页面 {page_num} 补检识别失败: {e}")
            return [], [], max_line_id, max_char_id

        if not result or not result.txts:
            return [], [], max_line_id, max_char_id

        new_lines = []
        new_chars = []

        for j in range(len(result.txts)):
            text = result.txts[j]
            score = (
                float(result.scores[j])
                if result.scores is not None and j < len(result.scores)
                else 0.5
            )
            box = (
                result.boxes[j].tolist()
                if result.boxes is not None and j < len(result.boxes)
                else None
            )

            if _use_rotate_then_crop:
                # 旋转后裁切方式: crop coords → +rotated offset → rotated page coords
                #              → _rotate_box_back → original page coords
                if box is not None:
                    box = self._convert_gap_box_to_page(box, rot_x1, rot_y1)
                    box = self._rotate_box_back(box, orig_w)
                page_box = box
            else:
                # 原有方式: crop coords → _rotate_box_back (if vertical) → +offset → page coords
                if is_vertical_page:
                    box = self._rotate_box_back(box, gap_orig_w)
                page_box = self._convert_gap_box_to_page(box, offset_x, offset_y)

            # 去重：计算与已有行的 IoU，超过 0.5 则跳过
            new_flat = flatten_bbox(page_box)
            if self._is_duplicate_line(new_flat, existing_flats):
                continue

            max_line_id += 1
            new_line = {
                "line_id": max_line_id,
                "page_num": page_num,
                "text": text,
                "score": score,
                "box": page_box,
            }
            new_lines.append(new_line)

            if result.word_results is not None and j < len(result.word_results):
                word_line = result.word_results[j]
                for word_txt, word_score, word_box in word_line:
                    wb = (
                        word_box.tolist()
                        if hasattr(word_box, "tolist")
                        else word_box
                    )
                    if _use_rotate_then_crop:
                        if wb is not None:
                            wb = self._convert_gap_box_to_page(wb, rot_x1, rot_y1)
                            wb = self._rotate_box_back(wb, orig_w)
                        page_word_box = wb
                    else:
                        if is_vertical_page:
                            wb = self._rotate_box_back(wb, gap_orig_w)
                        page_word_box = self._convert_gap_box_to_page(
                            wb, offset_x, offset_y
                        )
                    max_char_id += 1
                    new_chars.append({
                        "char_id": max_char_id,
                        "line_id": max_line_id,
                        "page_num": page_num,
                        "char": word_txt,
                        "score": float(word_score),
                        "box": page_word_box,
                    })

        return new_lines, new_chars, max_line_id, max_char_id

    def _detect_and_fill_gaps(self, page_image, lines_data, chars_data, page_num, engine, regions=None):
        """检测行间隙异常并补检漏行。

        当同页相邻行的 y 间隙大于 1.5 倍中位行高时，
        裁切间隙区域图像重新调用 RapidOCR 识别。

        同时检查"页面顶部到第一行"和"最后一行到页面底部"的边界间隙，
        避免页首/页尾漏行未被补检。

        用于修复 DBNet 在某些行上检测失败导致的整行漏识别问题。
        补检失败不影响主流程（try-except 包裹）。

        参数:
            page_image: 页面图像 (PIL.Image)
            lines_data: 全部行列表（会被原地扩展）
            chars_data: 全部字符列表（会被原地扩展）
            page_num: 当前页码
            engine: RapidOCR 引擎实例

        返回:
            tuple[list, list]: (lines_data, chars_data) 更新后的列表
        """
        import numpy as np
        from models.data_models import flatten_bbox

        if not lines_data or len(lines_data) < 2:
            return lines_data, chars_data

        # 提取当前页的行
        page_lines = [l for l in lines_data if l.get("page_num") == page_num]
        if len(page_lines) < 2:
            return lines_data, chars_data

        # 计算每行的扁平 bbox，便于几何运算（行 box 可能是 4 角点格式）
        line_flats = [flatten_bbox(l.get("box", [0, 0, 0, 0])) for l in page_lines]

        # 检测页面是否为竖排（高瘦行占多数：行高 > 行宽）
        vert_count = sum(1 for b in line_flats if (b[3] - b[1]) > (b[2] - b[0]))
        is_vertical_page = vert_count > len(line_flats) * 0.5 if line_flats else False

        # 当前最大 line_id / char_id，用于新增分配（两分支共用）
        max_line_id = max((l.get("line_id", 0) for l in lines_data), default=0)
        max_char_id = max((c.get("char_id", 0) for c in chars_data), default=0)

        new_lines = []
        new_chars = []

        # 页面图像转 numpy 一次复用（两分支共用）
        try:
            img_array = np.array(page_image)
        except Exception as e:
            print(f"[GapDetect] 页面 {page_num} 图像转换失败: {e}")
            return lines_data, chars_data

        img_h, img_w = img_array.shape[0], img_array.shape[1]

        if is_vertical_page:
            # === 竖排页分支：按列方向（x）检测列间隙 ===
            # 预计算整页逆时针旋转 90° 后的 numpy 数组，供 _detect_in_gap_region
            # 使用"整页旋转后裁切"方式（比"裁切后旋转"产生更准确的像素）
            try:
                rotated_page_pil = page_image.rotate(90, expand=True)
                rotated_page_array = np.array(rotated_page_pil)
            except Exception as e:
                print(f"[GapDetect] 页面 {page_num} 整页旋转失败: {e}，回退到裁切后旋转")
                rotated_page_array = None
            # orig_w 为原图宽度（旋转后图像的高度），用于坐标逆变换
            gap_orig_w = img_w

            # 按 x 中心排序（列方向）
            sorted_indices = sorted(
                range(len(page_lines)),
                key=lambda i: (line_flats[i][0] + line_flats[i][2]) / 2.0,
            )
            sorted_flats = [line_flats[i] for i in sorted_indices]

            # 计算中位列宽
            widths = [b[2] - b[0] for b in sorted_flats]
            median_width = sorted(widths)[len(widths) // 2]
            if median_width <= 0:
                return lines_data, chars_data

            gap_threshold = median_width * 1.5

            # 全页 y 范围（竖排页裁切用全页高）
            page_y1 = 0
            page_y2 = img_h

            # 边界间隙检测：页面左边到第一列
            first_left = sorted_flats[0][0]
            if first_left > gap_threshold:
                gap_x1 = 0
                gap_x2 = min(img_w, int(first_left) + 5)
                b_lines, b_chars, max_line_id, max_char_id = self._detect_in_gap_region(
                    img_array, page_y1, page_y2, gap_x1, gap_x2,
                    gap_x1, 0, page_num, engine,
                    max_line_id, max_char_id, sorted_flats,
                    is_vertical_page=True,
                    rotated_page_array=rotated_page_array, orig_w=gap_orig_w,
                )
                new_lines.extend(b_lines)
                new_chars.extend(b_chars)

            # 相邻列间隙检测
            for i in range(len(sorted_flats) - 1):
                curr_right = sorted_flats[i][2]
                next_left = sorted_flats[i + 1][0]
                gap = next_left - curr_right
                if gap <= gap_threshold:
                    continue
                gap_x1 = max(0, int(curr_right) - 5)
                gap_x2 = min(img_w, int(next_left) + 5)
                g_lines, g_chars, max_line_id, max_char_id = self._detect_in_gap_region(
                    img_array, page_y1, page_y2, gap_x1, gap_x2,
                    gap_x1, 0, page_num, engine,
                    max_line_id, max_char_id, sorted_flats,
                    is_vertical_page=True,
                    rotated_page_array=rotated_page_array, orig_w=gap_orig_w,
                )
                new_lines.extend(g_lines)
                new_chars.extend(g_chars)

            # 边界间隙检测：最后一列到页面右边
            last_right = sorted_flats[-1][2]
            right_gap = img_w - last_right
            if right_gap > gap_threshold:
                gap_x1 = max(0, int(last_right) - 5)
                gap_x2 = img_w
                b_lines, b_chars, max_line_id, max_char_id = self._detect_in_gap_region(
                    img_array, page_y1, page_y2, gap_x1, gap_x2,
                    gap_x1, 0, page_num, engine,
                    max_line_id, max_char_id, sorted_flats,
                    is_vertical_page=True,
                    rotated_page_array=rotated_page_array, orig_w=gap_orig_w,
                )
                new_lines.extend(b_lines)
                new_chars.extend(b_chars)

            if new_lines:
                # 按 regions 过滤补检新行（仅保留与用户画框有重叠的行）
                if regions:
                    page_regions = regions.get(page_num, [])
                    if page_regions:
                        from models.data_models import flatten_bbox as _flatten_bbox
                        filtered_new_lines = []
                        filtered_new_line_ids = set()
                        for nl in new_lines:
                            nl_bbox = _flatten_bbox(nl.get("box", [0, 0, 0, 0]))
                            for region_bbox in page_regions:
                                if self._boxes_overlap(nl_bbox, region_bbox):
                                    filtered_new_lines.append(nl)
                                    filtered_new_line_ids.add(nl.get("line_id", -1))
                                    break
                        new_lines = filtered_new_lines
                        new_chars = [nc for nc in new_chars if nc.get("line_id", -1) in filtered_new_line_ids]

                if new_lines:
                    lines_data.extend(new_lines)
                    chars_data.extend(new_chars)
                    # 稳定排序按页分组（不改变其他页内顺序），再仅对当前页按 x 中心排序
                    def _x_center(l):
                        b = flatten_bbox(l.get("box", [0, 0, 0, 0]))
                        return (b[0] + b[2]) / 2.0
                    lines_data.sort(key=lambda l: l.get("page_num", 0))
                    current_indices = [i for i, l in enumerate(lines_data) if l.get("page_num", 0) == page_num]
                    current_lines = [lines_data[i] for i in current_indices]
                    current_lines.sort(key=_x_center)
                    for idx, sorted_line in zip(current_indices, current_lines):
                        lines_data[idx] = sorted_line
                    print(
                        f"[GapDetect] 页 {page_num} 竖排补检 {len(new_lines)} 行 "
                        f"{len(new_chars)} 字符"
                    )

        else:
            # === 横排页分支：原有逻辑，按行方向（y）检测行间隙 ===
            # 按 y 中心排序
            sorted_indices = sorted(
                range(len(page_lines)),
                key=lambda i: (line_flats[i][1] + line_flats[i][3]) / 2.0,
            )
            sorted_flats = [line_flats[i] for i in sorted_indices]

            # 计算中位行高
            heights = [b[3] - b[1] for b in sorted_flats]
            median_height = sorted(heights)[len(heights) // 2]
            if median_height <= 0:
                return lines_data, chars_data

            gap_threshold = median_height * 1.5

            # 全页 x 范围（用于裁切 gap 区域的横向范围）
            page_x1 = max(0, int(min(b[0] for b in sorted_flats)))
            page_x2 = min(img_w, int(max(b[2] for b in sorted_flats)))

            # 边界间隙检测：页面顶部到第一行
            first_top = sorted_flats[0][1]
            if first_top > gap_threshold:
                bg_y1 = 0
                bg_y2 = min(img_h, int(first_top) + 5)
                b_lines, b_chars, max_line_id, max_char_id = self._detect_in_gap_region(
                    img_array, bg_y1, bg_y2, page_x1, page_x2,
                    page_x1, bg_y1, page_num, engine,
                    max_line_id, max_char_id, sorted_flats,
                    is_vertical_page=False,
                )
                new_lines.extend(b_lines)
                new_chars.extend(b_chars)

            for i in range(len(sorted_flats) - 1):
                curr_bottom = sorted_flats[i][3]
                next_top = sorted_flats[i + 1][1]
                gap = next_top - curr_bottom
                if gap <= gap_threshold:
                    continue
                gap_y1 = max(0, int(curr_bottom) - 5)
                gap_y2 = min(img_h, int(next_top) + 5)
                g_lines, g_chars, max_line_id, max_char_id = self._detect_in_gap_region(
                    img_array, gap_y1, gap_y2, page_x1, page_x2,
                    page_x1, gap_y1, page_num, engine,
                    max_line_id, max_char_id, sorted_flats,
                    is_vertical_page=False,
                )
                new_lines.extend(g_lines)
                new_chars.extend(g_chars)

            # 边界间隙检测：最后一行到页面底部
            last_bottom = sorted_flats[-1][3]
            bottom_gap = img_h - last_bottom
            if bottom_gap > gap_threshold:
                bg_y1 = max(0, int(last_bottom) - 5)
                bg_y2 = img_h
                b_lines, b_chars, max_line_id, max_char_id = self._detect_in_gap_region(
                    img_array, bg_y1, bg_y2, page_x1, page_x2,
                    page_x1, bg_y1, page_num, engine,
                    max_line_id, max_char_id, sorted_flats,
                    is_vertical_page=False,
                )
                new_lines.extend(b_lines)
                new_chars.extend(b_chars)

            if new_lines:
                # 按 regions 过滤补检新行（仅保留与用户画框有重叠的行）
                if regions:
                    page_regions = regions.get(page_num, [])
                    if page_regions:
                        from models.data_models import flatten_bbox as _flatten_bbox
                        filtered_new_lines = []
                        filtered_new_line_ids = set()
                        for nl in new_lines:
                            nl_bbox = _flatten_bbox(nl.get("box", [0, 0, 0, 0]))
                            for region_bbox in page_regions:
                                if self._boxes_overlap(nl_bbox, region_bbox):
                                    filtered_new_lines.append(nl)
                                    filtered_new_line_ids.add(nl.get("line_id", -1))
                                    break
                        new_lines = filtered_new_lines
                        new_chars = [nc for nc in new_chars if nc.get("line_id", -1) in filtered_new_line_ids]

                if new_lines:
                    lines_data.extend(new_lines)
                    chars_data.extend(new_chars)
                    # 稳定排序按页分组（不改变其他页内顺序），再仅对当前页按 y 中心排序
                    def _y_center(l):
                        b = flatten_bbox(l.get("box", [0, 0, 0, 0]))
                        return (b[1] + b[3]) / 2.0
                    lines_data.sort(key=lambda l: l.get("page_num", 0))
                    current_indices = [i for i, l in enumerate(lines_data) if l.get("page_num", 0) == page_num]
                    current_lines = [lines_data[i] for i in current_indices]
                    current_lines.sort(key=_y_center)
                    for idx, sorted_line in zip(current_indices, current_lines):
                        lines_data[idx] = sorted_line
                    print(
                        f"[GapDetect] 页 {page_num} 补检 {len(new_lines)} 行 "
                        f"{len(new_chars)} 字符"
                    )

        return lines_data, chars_data

    def _detect_missed_in_regions(self, page_image, lines_data, chars_data, page_num, engine, regions):
        """对用户画框 region 裁切后单独 OCR，补检整列漏检。

        竖排书 OCR 中 DBNet 在旋转后整页图像上对某些列可能检测失败，
        即使分块补检和 gap 间隙补检也无法覆盖。本方法对每个用户画框 region
        裁切后单独 OCR，确保 region 内所有列被检出。

        坐标变换链（竖排页）：
          region 裁切图 → 逆时针旋转 90° → OCR → _rotate_box_back(orig_w=region_w)
          → 裁切图坐标 → +(rx1, ry1) 偏移 → 整页坐标
        横排页：region 裁切图 → OCR → +(rx1, ry1) 偏移 → 整页坐标

        参数:
            page_image: 页面图像 (PIL.Image)
            lines_data: 全部行列表（会被扩展）
            chars_data: 全部字符列表（会被扩展）
            page_num: 当前页码
            engine: RapidOCR 引擎实例
            regions: dict，键为页码，值为该页的 region 列表，
                     每个 region 为 [x1, y1, x2, y2] 扁平格式

        返回:
            tuple[list, list]: (lines_data, chars_data) 更新后的列表
        """
        import numpy as np
        from PIL import Image
        from models.data_models import flatten_bbox

        # 取当前页 regions，若空则直接返回
        page_regions = regions.get(page_num, []) if regions else []
        if not page_regions:
            return lines_data, chars_data

        # 提取当前页已有行
        page_lines = [l for l in lines_data if l.get("page_num") == page_num]

        # 判断页面是否竖排：统计 (b[3]-b[1]) > (b[2]-b[0]) 的行数是否过半
        # 复用 _is_vertical_page_by_boxes 的逻辑，但基于 lines_data 而非 RapidOCR result
        line_flats = [flatten_bbox(l.get("box", [0, 0, 0, 0])) for l in page_lines]
        vert_count = sum(1 for b in line_flats if (b[3] - b[1]) > (b[2] - b[0]))
        is_vertical_page = vert_count > len(line_flats) * 0.5 if line_flats else False

        # 已有行的扁平 bbox 列表（用于去重）
        existing_flats = list(line_flats)

        # 当前最大 line_id / char_id，用于新增分配
        max_line_id = max((l.get("line_id", 0) for l in lines_data), default=0)
        max_char_id = max((c.get("char_id", 0) for c in chars_data), default=0)

        # 整页尺寸
        page_w, page_h = page_image.size

        # 页面图像转 numpy 数组（用 numpy 裁切避免 PIL crop 的 RecursionError）
        try:
            page_image.load()
            page_arr = np.array(page_image)
        except Exception as e:
            print(f"[RegionDetect] 页面 {page_num} 图像转换失败: {e}")
            return lines_data, chars_data

        new_lines = []
        new_chars = []

        for region in page_regions:
            try:
                # 带 20px padding 裁切
                rx1 = max(int(region[0]) - 20, 0)
                ry1 = max(int(region[1]) - 20, 0)
                rx2 = min(int(region[2]) + 20, page_w)
                ry2 = min(int(region[3]) + 20, page_h)
                if rx2 <= rx1 or ry2 <= ry1:
                    continue

                # numpy 数组裁切（不用 PIL crop 避免 RecursionError）
                region_arr = page_arr[ry1:ry2, rx1:rx2].copy()
                if region_arr.size == 0 or region_arr.shape[0] < 5 or region_arr.shape[1] < 5:
                    continue
                region_img = Image.fromarray(region_arr)

                # 竖排页：裁切后逆时针旋转 90°，OCR 后逆变换回裁切图坐标
                # 横排页：直接 OCR
                if is_vertical_page:
                    # 竖排页：列投影分析检测列位置，逐列 OCR
                    col_lines, col_chars, max_line_id, max_char_id = self._detect_columns_by_projection(
                        region_img, rx1, ry1, page_num, engine,
                        existing_flats, max_line_id, max_char_id
                    )
                    new_lines.extend(col_lines)
                    new_chars.extend(col_chars)
                    continue
                # 横排页：原逻辑（region 裁切→直接 OCR→+offset 偏移）
                region_orig_w = 0
                region_img_for_ocr = region_img

                # OCR 调用
                result = engine(
                    region_img_for_ocr,
                    return_word_box=True,
                    return_single_char_box=True,
                )

                if not result or not result.txts:
                    continue

                for j in range(len(result.txts)):
                    text = result.txts[j]
                    score = (
                        float(result.scores[j])
                        if result.scores is not None and j < len(result.scores)
                        else 0.5
                    )
                    box = (
                        result.boxes[j].tolist()
                        if result.boxes is not None and j < len(result.boxes)
                        else None
                    )

                    # 坐标变换：旋转图坐标 → 裁切图坐标 → 整页坐标
                    if is_vertical_page and box is not None:
                        # 逆变换回裁切图坐标（orig_w 为裁切图旋转前宽度，非整页宽度）
                        box = self._rotate_box_back(box, region_orig_w)
                    # 偏移到整页坐标
                    if box is not None:
                        box = self._convert_gap_box_to_page(box, rx1, ry1)

                    # 去重：计算与已有行的 IoU，超过 0.5 则跳过
                    new_flat = flatten_bbox(box)
                    if self._is_duplicate_line(new_flat, existing_flats):
                        continue

                    max_line_id += 1
                    new_line = {
                        "line_id": max_line_id,
                        "page_num": page_num,
                        "text": text,
                        "score": score,
                        "box": box,
                    }
                    new_lines.append(new_line)
                    # 将新行加入 existing_flats，避免相邻 region padding 重叠导致重复
                    existing_flats.append(new_flat)

                    # 处理字符级结果
                    if result.word_results is not None and j < len(result.word_results):
                        word_line = result.word_results[j]
                        for word_txt, word_score, word_box in word_line:
                            wb = (
                                word_box.tolist()
                                if hasattr(word_box, "tolist")
                                else word_box
                            )
                            if is_vertical_page and wb is not None:
                                wb = self._rotate_box_back(wb, region_orig_w)
                            if wb is not None:
                                wb = self._convert_gap_box_to_page(wb, rx1, ry1)
                            max_char_id += 1
                            new_chars.append({
                                "char_id": max_char_id,
                                "line_id": max_line_id,
                                "page_num": page_num,
                                "char": word_txt,
                                "score": float(word_score),
                                "box": wb,
                            })
            except Exception as e:
                # 异常降级：单个 region OCR 失败不影响其他 region
                print(f"[RegionDetect] 页面 {page_num} region {region} 补检失败: {e}")
                continue

        # 若有新行：扩展并按页内 x 中心（竖排）或 y 中心（横排）排序
        if new_lines:
            lines_data.extend(new_lines)
            chars_data.extend(new_chars)

            if is_vertical_page:
                def _center_key(l):
                    b = flatten_bbox(l.get("box", [0, 0, 0, 0]))
                    return (b[0] + b[2]) / 2.0  # x 中心
            else:
                def _center_key(l):
                    b = flatten_bbox(l.get("box", [0, 0, 0, 0]))
                    return (b[1] + b[3]) / 2.0  # y 中心

            # 稳定排序：先按页分组（不改变其他页顺序），再仅对当前页排序
            lines_data.sort(key=lambda l: l.get("page_num", 0))
            current_indices = [i for i, l in enumerate(lines_data) if l.get("page_num", 0) == page_num]
            current_lines = [lines_data[i] for i in current_indices]
            current_lines.sort(key=_center_key)
            for idx, sorted_line in zip(current_indices, current_lines):
                lines_data[idx] = sorted_line
            print(
                f"[RegionDetect] 页 {page_num} region 补检 {len(new_lines)} 行 "
                f"{len(new_chars)} 字符"
            )

        return lines_data, chars_data

    def _detect_columns_by_projection(self, region_img, region_offset_x, region_offset_y,
                                       page_num, engine, existing_flats,
                                       max_line_id, max_char_id):
        """对竖排页 region 裁切图执行列投影分析，检测列位置并逐列 OCR 补检。

        算法：
        1. 将 region_img 转灰度→二值化（阈值 200）
        2. 计算 x 方向墨水投影 profile[x] = sum(墨水像素 in column x)
        3. 高斯平滑（sigma=3）
        4. 阈值 thr = max(profile) * 0.1，找连续 profile[x] > thr 的区间为列候选
        5. 过滤宽度 <10px 或 >200px 的候选
        6. 对每个列候选：裁切竖向条带→逆时针旋转 90°→OCR→坐标逆变换→去重合并

        坐标变换链：
          列条带裁切图 (strip_w x region_h)
          → rotate(90, expand=True) → OCR → 旋转后坐标
          → _rotate_box_back(orig_w=strip_w) → 列条带坐标
          → +region offset (region_offset_x + col_x1, region_offset_y) → 整页坐标

        参数:
            region_img: PIL.Image, region 裁切图（已从整页裁切，未旋转）
            region_offset_x: int, region 在整页中的 x 偏移
            region_offset_y: int, region 在整页中的 y 偏移
            page_num: int, 当前页码
            engine: RapidOCR 引擎实例
            existing_flats: list, 已有行的扁平 bbox 列表（用于去重）
            max_line_id: int, 当前最大 line_id
            max_char_id: int, 当前最大 char_id

        返回:
            tuple: (new_lines, new_chars, max_line_id, max_char_id)
        """
        import numpy as np
        from PIL import Image
        from models.data_models import flatten_bbox

        new_lines = []
        new_chars = []

        # 1. 转灰度并二值化（墨水像素为 True）
        gray = np.array(region_img.convert('L'))
        binary = gray < 200

        # 2. x 方向墨水投影（长度 = region 宽度）
        profile = binary.sum(axis=0).astype(float)

        # 全页无墨水则直接返回
        if profile.max() == 0:
            return new_lines, new_chars, max_line_id, max_char_id

        # 3. 高斯平滑（sigma=3）：优先 scipy，不可用则 numpy 卷积降级
        try:
            from scipy.ndimage import gaussian_filter1d
            profile_smooth = gaussian_filter1d(profile, sigma=3)
        except ImportError:
            kernel = np.exp(-np.arange(-5, 6) ** 2 / (2 * 3 ** 2)) / (np.sqrt(2 * np.pi) * 3)
            profile_smooth = np.convolve(profile, kernel, 'same')

        # 4. 阈值 thr = max(profile) * 0.1，找连续 profile[x] > thr 的区间
        thr = profile_smooth.max() * 0.1
        columns = []
        in_col = False
        start = 0
        for x in range(len(profile_smooth)):
            if profile_smooth[x] > thr:
                if not in_col:
                    in_col = True
                    start = x
            else:
                if in_col:
                    end = x
                    width = end - start
                    # 5. 过滤宽度 <10px 或 >200px 的候选
                    if 10 <= width <= 200:
                        columns.append((start, end))
                    in_col = False
        # 处理末尾区间
        if in_col:
            end = len(profile_smooth)
            width = end - start
            if 10 <= width <= 200:
                columns.append((start, end))

        # 6. 逐列 OCR 补检
        # region 彩色数组（用于裁切列条带送 OCR）
        region_arr = np.array(region_img)

        for col_x1, col_x2 in columns:
            try:
                # 裁切竖向条带（y 取全 region 高度）
                strip_arr = region_arr[:, col_x1:col_x2].copy()
                if strip_arr.size == 0 or strip_arr.shape[0] < 5 or strip_arr.shape[1] < 5:
                    continue
                strip_img = Image.fromarray(strip_arr)
                # 旋转前宽度，作为 _rotate_box_back 的 orig_w（非 region 宽度或整页宽度）
                strip_w = strip_img.width
                strip_rotated = strip_img.rotate(90, expand=True)

                # OCR
                result = engine(
                    strip_rotated,
                    return_word_box=True,
                    return_single_char_box=True,
                )
                if not result or not result.txts:
                    continue

                for j in range(len(result.txts)):
                    text = result.txts[j]
                    score = (
                        float(result.scores[j])
                        if result.scores is not None and j < len(result.scores)
                        else 0.5
                    )
                    box = (
                        result.boxes[j].tolist()
                        if result.boxes is not None and j < len(result.boxes)
                        else None
                    )

                    # 坐标变换：旋转图坐标 → 列条带坐标 → 整页坐标
                    # orig_w 为条带旋转前宽度（strip_w）
                    if box is not None:
                        box = self._rotate_box_back(box, strip_w)
                        box = self._convert_gap_box_to_page(
                            box, region_offset_x + col_x1, region_offset_y
                        )

                    # 去重
                    new_flat = flatten_bbox(box)
                    if self._is_duplicate_line(new_flat, existing_flats):
                        continue
                    # 加入 existing_flats 避免后续列重复
                    existing_flats.append(new_flat)

                    max_line_id += 1
                    new_line = {
                        "line_id": max_line_id,
                        "page_num": page_num,
                        "text": text,
                        "score": score,
                        "box": box,
                    }
                    new_lines.append(new_line)

                    # 处理字符级结果
                    if result.word_results is not None and j < len(result.word_results):
                        word_line = result.word_results[j]
                        for word_txt, word_score, word_box in word_line:
                            wb = (
                                word_box.tolist()
                                if hasattr(word_box, "tolist")
                                else word_box
                            )
                            if wb is not None:
                                wb = self._rotate_box_back(wb, strip_w)
                                wb = self._convert_gap_box_to_page(
                                    wb, region_offset_x + col_x1, region_offset_y
                                )
                            max_char_id += 1
                            new_chars.append({
                                "char_id": max_char_id,
                                "line_id": max_line_id,
                                "page_num": page_num,
                                "char": word_txt,
                                "score": float(word_score),
                                "box": wb,
                            })
            except Exception as e:
                # 异常降级：单列 OCR 失败不影响其他列
                print(f"[ColumnProjection] 页面 {page_num} 列 {col_x1}-{col_x2} OCR 失败: {e}")
                continue

        return new_lines, new_chars, max_line_id, max_char_id

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

        # 行间隙补检：检测相邻行 y 间隙异常并重新识别漏行
        # 用于修复 DBNet 在某些行上检测失败导致的整行漏识别问题
        try:
            page_nums_in_results = sorted(
                set(l.get("page_num", 0) for l in all_lines)
            )
            if page_nums_in_results:
                if output_callback:
                    output_callback("正在执行行间隙补检...")
                filled_count = 0
                for p_num in page_nums_in_results:
                    if p_num >= len(page_images):
                        continue
                    p_img = page_images[p_num]
                    before = len(all_lines)
                    all_lines, all_chars = self._detect_and_fill_gaps(
                        p_img, all_lines, all_chars, p_num, self.engine, regions
                    )
                    filled_count += len(all_lines) - before
                if output_callback and filled_count > 0:
                    output_callback(
                        f"行间隙补检完成，新增 {filled_count} 行"
                    )
        except Exception as e:
            if output_callback:
                output_callback(f"行间隙补检失败，跳过: {e}")

        # region 引导补检：对每个用户画框 region 单独 OCR，补检漏列
        try:
            if regions:
                if output_callback:
                    output_callback("正在执行 region 引导补检...")
                # 重新计算 page_nums_in_results 避免上方 try 块作用域问题
                # 同时包含有 region 但完全漏检（无任何行）的页，这正是本功能要覆盖的场景
                result_pages = set(l.get("page_num", 0) for l in all_lines)
                region_pages = set(p for p in regions.keys() if p < len(page_images))
                page_nums_in_results = sorted(result_pages | region_pages)
                region_filled = 0
                for p_num in page_nums_in_results:
                    if p_num >= len(page_images):
                        continue
                    p_img = page_images[p_num]
                    before = len(all_lines)
                    all_lines, all_chars = self._detect_missed_in_regions(
                        p_img, all_lines, all_chars, p_num, self.engine, regions
                    )
                    region_filled += len(all_lines) - before
                if output_callback and region_filled > 0:
                    output_callback(f"region 引导补检完成，新增 {region_filled} 行")
        except Exception as e:
            if output_callback:
                output_callback(f"region 引导补检失败，跳过: {e}")

        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        json_dir = os.path.join(output_dir, pdf_basename)
        os.makedirs(json_dir, exist_ok=True)

        # 行框裁边：对每个 line 的 bbox 执行三步裁边，使 lines.json 中保存紧贴文字的 bbox
        try:
            if output_callback:
                output_callback("正在执行行框裁边...")
            lines_by_page = {}
            for line in all_lines:
                p_num = line.get("page_num", 0)
                lines_by_page.setdefault(p_num, []).append(line)
            for p_num, page_line_list in lines_by_page.items():
                if p_num >= len(page_images) or page_images[p_num] is None:
                    continue
                page_image = page_images[p_num]
                for line in page_line_list:
                    try:
                        line_bbox = flatten_bbox(line.get("box", [0, 0, 0, 0]))
                        x1 = max(0, int(round(line_bbox[0])))
                        y1 = max(0, int(round(line_bbox[1])))
                        x2 = min(page_image.size[0], int(round(line_bbox[2])))
                        y2 = min(page_image.size[1], int(round(line_bbox[3])))
                        if x2 <= x1 or y2 <= y1:
                            continue
                        line_image = page_image.crop((x1, y1, x2, y2))
                        trimmed = self._trim_line_bbox(line_image, line_bbox)
                        nx1, ny1, nx2, ny2 = trimmed
                        line["box"] = [
                            [nx1, ny1], [nx2, ny1], [nx2, ny2], [nx1, ny2]
                        ]
                    except Exception:
                        continue
            if output_callback:
                output_callback("行框裁边完成")
        except Exception as e:
            if output_callback:
                output_callback(f"行框裁边失败，跳过: {e}")

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

        # 单字切片 OCR 二次识别：与原识别结果比对，标记可疑字符
        # 异常降级：失败时跳过，不影响主流程；成功后重存 newchar.json 以包含新字段
        try:
            self._cross_check_chars_with_single_ocr(page_images, all_chars)
            newchar_path = os.path.join(json_dir, "newchar.json")
            if os.path.exists(newchar_path):
                with open(newchar_path, "w", encoding="utf-8") as f:
                    json.dump(all_chars, f, ensure_ascii=False)
            if output_callback:
                output_callback("单字OCR二次识别完成")
        except Exception as e:
            if output_callback:
                output_callback(f"单字OCR二次识别失败，跳过: {e}")

        if output_callback:
            # 复制原PDF到JSON输出文件夹
            try:
                import shutil
                shutil.copy2(pdf_path, os.path.join(json_dir, os.path.basename(pdf_path)))
            except Exception:
                pass
            output_callback(f"识别完成！结果已保存至: {json_dir}")

        return self.results

    @staticmethod
    def _compute_ink_ratio(mask, x1, y1, x2, y2):
        """计算 mask[y1:y2, x1:x2] 范围内的非白像素比例（墨水比例）。

        用于验证优化后的字符框是否有效：若墨水比例过低，说明框大部分是空白，
        可能切到了字间空白，应回退到原始 DBNet 框。

        Args:
            mask: 非白像素掩码（2D 布尔数组，True=有墨水）
            x1, y1, x2, y2: 切片区域坐标（已 clamp 到图像边界）

        Returns:
            float: 非白像素比例 [0.0, 1.0]；区域为空时返回 0.0
        """
        if x2 <= x1 or y2 <= y1:
            return 0.0
        sub = mask[int(y1):int(y2), int(x1):int(x2)]
        total = sub.size
        if total == 0:
            return 0.0
        return float(sub.sum()) / float(total)

    @staticmethod
    def _should_optimize_y_edge(mask, y_edge, x1_c, x2_c, edge_len):
        """判断竖排字符的 y 边是否需要优化。

        检测 y 边附近 ±2px 范围的有色像素数，若 > edge_len * 0.3 则判定
        "切到文字本体"，需要执行 y 边优化；否则保持原 y 值。

        Args:
            mask: 非白像素掩码（2D 布尔数组）
            y_edge: 原始 y 边位置（y1 或 y2）
            x1_c, x2_c: 字符 x 范围（已 clamp）
            edge_len: 边长（字符宽度，用于计算阈值）

        Returns:
            bool: True 表示切到文字本体，需要优化；False 表示在空白处，保持原值
        """
        if x2_c <= x1_c:
            return False
        img_h = mask.shape[0]
        y_start = max(0, int(round(y_edge)) - 2)
        y_end = min(img_h, int(round(y_edge)) + 3)  # +3 因为切片不含右端
        if y_end <= y_start:
            return False
        # 统计 y 边附近 ±2px 范围的有色像素数
        sub = mask[y_start:y_end, x1_c:x2_c]
        ink_count = int(sub.sum())
        threshold = max(1, int(edge_len * 0.3))
        return ink_count > threshold

    def _get_single_char_rec_engine(self):
        """懒加载并缓存专用单字识别 rec 引擎实例。

        与主引擎分离，避免 det/cls 配置冲突。复用主引擎的模型类型与 CUDA 配置。
        引擎实例缓存于 self._single_char_rec_engine，避免每次调用重建。
        创建失败返回 None（调用方应降级跳过）。
        """
        if hasattr(self, "_single_char_rec_engine"):
            return self._single_char_rec_engine
        try:
            rec_params = {
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.lang_type": LangRec.CH,
                "Rec.model_type": self._model_type,
                "Rec.ocr_version": OCRVersion.PPOCRV6,
                "EngineConfig.onnxruntime.use_cuda": self._has_cuda,
                "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC",
                "Rec.rec_batch_num": 64 if self._has_cuda else 16,
            }
            self._single_char_rec_engine = RapidOCR(params=rec_params)
            return self._single_char_rec_engine
        except Exception as e:
            print(f"单字rec引擎创建失败，跳过二次识别: {e}", flush=True)
            self._single_char_rec_engine = None
            return None

    def _cross_check_chars_with_single_ocr(self, page_images, all_chars):
        """单字切片 OCR 二次识别：对每个字符切片独立执行 rec 识别。

        对 all_chars 中每个字符按 box 从对应 page_image 裁切切片图像，
        复用 RapidOCR 的 rec 模型批量识别，与原识别结果比对：
          - 完全一致 → suspect=false
          - 不一致 → suspect=true, alt_char=单字OCR结果, alt_score=单字OCR置信度
        将 suspect/alt_char/alt_score 写入 char dict（原地修改 all_chars）。

        异常降级：任何失败均跳过对应字符/页，不影响主流程。
        依赖:
            rapidocr.RapidOCR.recognize_txt: 批量 rec 识别接口，接受
                List[np.ndarray] 返回 TextRecOutput（含 .txts / .scores）
            models.data_models.flatten_bbox: box 扁平化
        """
        if not all_chars:
            return

        rec_engine = self._get_single_char_rec_engine()
        if rec_engine is None:
            # 引擎不可用，全部置默认字段
            for char in all_chars:
                char.setdefault("suspect", False)
                char.setdefault("alt_char", "")
                char.setdefault("alt_score", 0.0)
            return

        print("单字OCR二次识别已启用", flush=True)

        import numpy as np

        # 按页分组字符
        chars_by_page = {}
        for char in all_chars:
            page = char.get("page_num", 0)
            chars_by_page.setdefault(page, []).append(char)

        for page_num, chars_on_page in chars_by_page.items():
            if page_num >= len(page_images) or page_images[page_num] is None:
                for char in chars_on_page:
                    char.setdefault("suspect", False)
                    char.setdefault("alt_char", "")
                    char.setdefault("alt_score", 0.0)
                continue

            page_image = page_images[page_num]
            try:
                page_image.load()  # 物化PIL图像，避免lazy image触发RecursionError
            except Exception:
                pass

            try:
                img_w, img_h = page_image.size
            except Exception:
                for char in chars_on_page:
                    char.setdefault("suspect", False)
                    char.setdefault("alt_char", "")
                    char.setdefault("alt_score", 0.0)
                continue

            # 裁切每个字符切片并转为 ndarray
            cropped_ndarrays = []
            char_indices = []
            for idx, char in enumerate(chars_on_page):
                box = char.get("box", [0, 0, 0, 0])
                bbox = flatten_bbox(box)
                x1 = max(0, int(round(bbox[0])))
                y1 = max(0, int(round(bbox[1])))
                x2 = min(img_w, int(round(bbox[2])))
                y2 = min(img_h, int(round(bbox[3])))
                if x2 <= x1 or y2 <= y1:
                    char.setdefault("suspect", False)
                    char.setdefault("alt_char", "")
                    char.setdefault("alt_score", 0.0)
                    continue
                try:
                    crop = page_image.crop((x1, y1, x2, y2))
                    crop.load()  # 物化切片，避免 lazy crop 触发 RecursionError
                    cropped_ndarrays.append(np.array(crop.convert("RGB")))
                    char_indices.append(idx)
                except Exception:
                    char.setdefault("suspect", False)
                    char.setdefault("alt_char", "")
                    char.setdefault("alt_score", 0.0)
                    continue

            if not cropped_ndarrays:
                continue

            # 批量送入 rec 模型
            try:
                rec_res = rec_engine.recognize_txt(cropped_ndarrays)
            except Exception:
                # 批量识别失败，本页全部置默认值
                for idx in char_indices:
                    chars_on_page[idx].setdefault("suspect", False)
                    chars_on_page[idx].setdefault("alt_char", "")
                    chars_on_page[idx].setdefault("alt_score", 0.0)
                continue

            rec_txts = getattr(rec_res, "txts", None)
            rec_scores = getattr(rec_res, "scores", None)

            for i, idx in enumerate(char_indices):
                char = chars_on_page[idx]
                orig_text = char.get("char", "")
                alt_text = ""
                alt_score = 0.0
                if rec_txts is not None and i < len(rec_txts):
                    try:
                        alt_text = str(rec_txts[i]) if rec_txts[i] is not None else ""
                    except Exception:
                        alt_text = ""
                if rec_scores is not None and i < len(rec_scores):
                    try:
                        alt_score = float(rec_scores[i])
                    except (TypeError, ValueError):
                        alt_score = 0.0

                char["alt_char"] = alt_text
                char["alt_score"] = alt_score
                # 单字 rec 可能输出多字（切片含多字）或空串：空串视为无结论，不标可疑
                if alt_text and alt_text == orig_text:
                    char["suspect"] = False
                elif alt_text:
                    char["suspect"] = True
                else:
                    char["suspect"] = False

    def _optimize_char_boxes(self, page_images, all_chars, json_dir):
        """优化字符边界框，使四边尽量经过纯白区域。

        对每个字符框的四条边独立优化，在±1/3倍边长范围内寻找
        非白像素最少的位置，避免截断文字或多截相邻字。

        竖排页面字符 y 边采用有条件优化：检测原始 y 边是否切到文字本体
        （±2px 范围有色像素数 > 边长 30%），若是则优化，否则保持原值。
        优化后增加切片空白比例验证：若非白像素比例 < 5%，回退原始 DBNet 框。

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
        INK_RATIO_THRESHOLD = 0.05  # 切片墨水比例 <5% 回退原始框

        for page_num, chars_on_page in chars_by_page.items():
            if page_num >= len(page_images):
                continue

            img = page_images[page_num]
            img_array = np.array(img)
            img_h, img_w = img_array.shape[:2]
            mask = np.any(img_array < WHITE_THRESHOLD, axis=2)

            # 页面级竖排检测：按 line_id 分组计算行框方向
            chars_by_line = {}
            for char in chars_on_page:
                lid = char.get("line_id", -1)
                chars_by_line.setdefault(lid, []).append(char)

            vert_lines = 0
            horiz_lines = 0
            for lid, line_chars in chars_by_line.items():
                bboxes = [flatten_bbox(c.get("box", [0, 0, 0, 0])) for c in line_chars]
                if not bboxes:
                    continue
                line_w = max(b[2] for b in bboxes) - min(b[0] for b in bboxes)
                line_h = max(b[3] for b in bboxes) - min(b[1] for b in bboxes)
                if line_h > line_w:
                    vert_lines += 1
                else:
                    horiz_lines += 1
            is_vertical_page = (
                vert_lines > horiz_lines
                if (vert_lines + horiz_lines) > 0
                else False
            )

            # H2: 尝试 native 批量优化
            native_results = None
            try:
                _, optimize_char_boxes_native, _ = _try_native()
                if optimize_char_boxes_native is not None:
                    native_results = optimize_char_boxes_native(
                        mask.astype(np.uint8), chars_on_page, is_vertical_page
                    )
            except Exception:
                native_results = None

            if native_results is not None and len(native_results) == len(chars_on_page):
                # 使用 native 结果更新 box（valid 时 box 已是 4 角点格式）
                # 增加切片空白比例验证：墨水比例 <5% 回退原始 DBNet 框
                for char, res in zip(chars_on_page, native_results):
                    if res.get("valid"):
                        new_box = res.get("box")
                        # 验证优化后切片的墨水比例
                        nb = flatten_bbox(new_box)
                        nx1 = max(0, int(round(nb[0])))
                        ny1 = max(0, int(round(nb[1])))
                        nx2 = min(img_w, int(round(nb[2])))
                        ny2 = min(img_h, int(round(nb[3])))
                        ink_ratio = self._compute_ink_ratio(mask, nx1, ny1, nx2, ny2)
                        if ink_ratio >= INK_RATIO_THRESHOLD:
                            char["box"] = new_box
                        # else: 墨水比例过低，保留原始 box（回退）
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

                    # 优化左右边（竖排/横排字符都需要）
                    new_x1 = self._optimize_edge_x(mask, x1, y1_c, y2_c, w, img_w)
                    new_x2 = self._optimize_edge_x(mask, x2, y1_c, y2_c, w, img_w)

                    if is_vertical_page:
                        # 竖排页面：y 边有条件优化
                        # 检测原始 y 边是否切到文字本体（±2px 范围有色像素 > 边长 30%）
                        if self._should_optimize_y_edge(mask, y1, x1_c, x2_c, w):
                            new_y1 = self._optimize_edge_y(mask, y1, x1_c, x2_c, h, img_h)
                        else:
                            new_y1 = y1
                        if self._should_optimize_y_edge(mask, y2, x1_c, x2_c, w):
                            new_y2 = self._optimize_edge_y(mask, y2, x1_c, x2_c, h, img_h)
                        else:
                            new_y2 = y2
                    else:
                        # 横排页面：保留逐字符 h>w 检查作为额外保护
                        is_vertical_char = h > w
                        if is_vertical_char:
                            new_y1 = y1
                            new_y2 = y2
                        else:
                            new_y1 = self._optimize_edge_y(mask, y1, x1_c, x2_c, h, img_h)
                            new_y2 = self._optimize_edge_y(mask, y2, x1_c, x2_c, h, img_h)

                    # 验证有效性
                    if new_x1 >= new_x2 or new_y1 >= new_y2:
                        continue

                    # 切片空白比例验证：墨水比例 <5% 回退原始 DBNet 框
                    nx1_v = max(0, int(round(new_x1)))
                    ny1_v = max(0, int(round(new_y1)))
                    nx2_v = min(img_w, int(round(new_x2)))
                    ny2_v = min(img_h, int(round(new_y2)))
                    ink_ratio = self._compute_ink_ratio(mask, nx1_v, ny1_v, nx2_v, ny2_v)
                    if ink_ratio < INK_RATIO_THRESHOLD:
                        # 墨水比例过低，保留原始 box（回退）
                        continue

                    # 转回4角点格式
                    char["box"] = [
                        [new_x1, new_y1],
                        [new_x2, new_y1],
                        [new_x2, new_y2],
                        [new_x1, new_y2],
                    ]

            # 竖排页字符墨水重定位：对所有竖排字符基于墨水重定位
            if is_vertical_page:
                self._relocate_vertical_char_box(mask, chars_on_page, img_h, img_w)

        # 保存为 newchar.json
        newchar_path = os.path.join(json_dir, "newchar.json")
        with open(newchar_path, "w", encoding="utf-8") as f:
            json.dump(all_chars, f, ensure_ascii=False)

    def _relocate_vertical_char_box(self, mask, chars_on_page, img_h, img_w):
        """竖排页面字符墨水重定位。

        对所有竖排页面字符（不限薄条）执行基于墨水的重定位：从字符
        x_center、y_center 向四周扩展找实际墨水边界，允许跳过最多
        2 个连续白色行/列（处理字符内部间隙如'日'字中间）。扩展边界
        限定在所属 line（列）bbox 的 x 和 y 范围内。

        取代原 _recover_thin_strips 的仅薄条恢复逻辑，扩展为所有竖排
        字符的墨水重定位，确保字符框紧贴实际墨水。

        参数:
            mask: 非白像素掩码（2D布尔数组，True=有墨水）
            chars_on_page: 当前页字符列表，每个含 box（4角点格式）和 line_id
            img_h: 页面图像高度
            img_w: 页面图像宽度
        """
        from models.data_models import flatten_bbox

        if not chars_on_page:
            return

        # 按 line_id 分组计算每列 bbox 的 x 和 y 范围（作为扩展边界）
        line_ranges = {}
        for char in chars_on_page:
            lid = char.get("line_id", -1)
            b = flatten_bbox(char.get("box", [0, 0, 0, 0]))
            if lid not in line_ranges:
                line_ranges[lid] = [b[0], b[2], b[1], b[3]]  # [x_lo, x_hi, y_lo, y_hi]
            else:
                line_ranges[lid][0] = min(line_ranges[lid][0], b[0])
                line_ranges[lid][1] = max(line_ranges[lid][1], b[2])
                line_ranges[lid][2] = min(line_ranges[lid][2], b[1])
                line_ranges[lid][3] = max(line_ranges[lid][3], b[3])

        MAX_WHITE_GAP = 2

        for char in chars_on_page:
            b = flatten_bbox(char.get("box", [0, 0, 0, 0]))
            x1, y1, x2, y2 = b
            if x2 <= x1 or y2 <= y1:
                continue

            # 字符自身的 x/y 范围及原始宽高（用于限制扩展范围，避免合并相邻字）
            x1_c = max(0, int(round(b[0])))
            x2_c = min(img_w, int(round(b[2])))
            y1_c = max(0, int(round(b[1])))
            y2_c = min(img_h, int(round(b[3])))
            orig_h = b[3] - b[1]  # 原始 box 高度
            orig_w = b[2] - b[0]  # 原始 box 宽度

            # 获取 line（列）x 和 y 范围作为扩展边界
            lid = char.get("line_id", -1)
            if lid in line_ranges:
                x_lo = max(0, int(round(line_ranges[lid][0])) - 5)
                x_hi = min(img_w, int(round(line_ranges[lid][1])) + 5)
                y_lo = max(0, int(round(line_ranges[lid][2])) - 5)
                y_hi = min(img_h, int(round(line_ranges[lid][3])) + 5)
            else:
                x_lo, x_hi = 0, img_w
                y_lo, y_hi = 0, img_h

            x_center = max(0, min(img_w - 1, int(round((x1 + x2) / 2.0))))
            y_center = max(0, min(img_h - 1, int(round((y1 + y2) / 2.0))))

            # 向左扩展找 new_x1
            new_x1 = x_center
            white_count = 0
            for x in range(x_center - 1, x_lo - 1, -1):
                if x < x_center - orig_w * 1.3:
                    break
                if x < 0:
                    break
                if mask[y_center, x].any() or self._column_has_ink(mask, x, y1_c, y2_c):
                    new_x1 = x
                    white_count = 0
                else:
                    white_count += 1
                    if white_count >= MAX_WHITE_GAP:
                        break

            # 向右扩展找 new_x2
            new_x2 = x_center
            white_count = 0
            for x in range(x_center + 1, x_hi):
                if x > x_center + orig_w * 1.3:
                    break
                if x >= img_w:
                    break
                if mask[y_center, x].any() or self._column_has_ink(mask, x, y1_c, y2_c):
                    new_x2 = x
                    white_count = 0
                else:
                    white_count += 1
                    if white_count >= MAX_WHITE_GAP:
                        break

            # 向上扩展找 new_y1
            new_y1 = y_center
            white_count = 0
            for y in range(y_center - 1, y_lo - 1, -1):
                if y < y_center - orig_h * 1.3:
                    break
                if y < 0:
                    break
                if mask[y, x_center].any() or self._row_has_ink(mask, y, x1_c, x2_c):
                    new_y1 = y
                    white_count = 0
                else:
                    white_count += 1
                    if white_count >= MAX_WHITE_GAP:
                        break

            # 向下扩展找 new_y2
            new_y2 = y_center
            white_count = 0
            for y in range(y_center + 1, y_hi):
                if y > y_center + orig_h * 1.3:
                    break
                if y >= img_h:
                    break
                if mask[y, x_center].any() or self._row_has_ink(mask, y, x1_c, x2_c):
                    new_y2 = y
                    white_count = 0
                else:
                    white_count += 1
                    if white_count >= MAX_WHITE_GAP:
                        break

            # 应用重定位后的边界（确保有效）
            if new_x2 > new_x1 and new_y2 > new_y1:
                char["box"] = [
                    [float(new_x1), float(new_y1)],
                    [float(new_x2), float(new_y1)],
                    [float(new_x2), float(new_y2)],
                    [float(new_x1), float(new_y2)],
                ]

    @staticmethod
    def _column_has_ink(mask, x, y_lo, y_hi):
        """检查指定列 x 在 [y_lo, y_hi) 范围内是否有墨水。"""
        if x < 0 or x >= mask.shape[1]:
            return False
        y_lo = max(0, int(y_lo))
        y_hi = min(mask.shape[0], int(y_hi))
        if y_hi <= y_lo:
            return False
        return bool(mask[y_lo:y_hi, x].any())

    @staticmethod
    def _row_has_ink(mask, y, x_lo, x_hi):
        """检查指定行 y 在 [x_lo, x_hi) 范围内是否有墨水。"""
        if y < 0 or y >= mask.shape[0]:
            return False
        x_lo = max(0, int(x_lo))
        x_hi = min(mask.shape[1], int(x_hi))
        if x_hi <= x_lo:
            return False
        return bool(mask[y, x_lo:x_hi].any())

    def _optimize_edge_x(self, mask, orig_x, y1, y2, edge_len, img_w):
        """优化垂直边（左/右边）的x位置。

        在 orig_x ± 1/3*edge_len 范围内搜索，找到经过非白像素最少的列位置。

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

        half = edge_len / 3.0
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

        在 orig_y ± 1/3*edge_len 范围内搜索，找到经过非白像素最少的行位置。

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

        half = edge_len / 3.0
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

    @staticmethod
    def _trim_line_bbox(line_image, orig_bbox):
        """对行切片图像执行三步裁边算法，返回紧贴文字的页面坐标 bbox。

        算法步骤：
          Step A：第一次白边裁切——对行切片图像四边裁切白色边缘
                  （灰度 >= 200 视为白色），得到紧贴非白像素的外接矩形。
          Step B：上下边框向内收缩——上下边框各自最多向内收缩 1/3，
                  在收缩范围内遇到全白行则收缩到该行；若无全白行则收缩到
                  黑色像素最少的行。左右边框不收缩。
          Step C：第二次白边裁切——对 Step B 的结果再次执行四边白边裁切。

        竖排支持：当行框高>宽时判定为竖排，对 mask 转置后走横排收缩逻辑
                  （收缩上下→对应原竖排左右），结果坐标转置回来。

        Args:
            line_image: PIL.Image 行切片图像（已用 orig_bbox 从页面裁出）。
            orig_bbox: 原始行边界框 [x1, y1, x2, y2]（页面坐标）。

        Returns:
            list: 裁边后的新 bbox [nx1, ny1, nx2, ny2]（页面坐标）。
                  若图像为空、纯白或尺寸与 bbox 不符，返回原 bbox 的副本。
        """
        if line_image is None:
            return list(orig_bbox)
        orig_x1, orig_y1, orig_x2, orig_y2 = orig_bbox
        # 竖排行框（高>宽）：收缩左右边框（通过 mask 转置映射为上下收缩）
        is_vertical = (orig_y2 - orig_y1) > (orig_x2 - orig_x1)
        expected_w = int(round(orig_x2 - orig_x1))
        expected_h = int(round(orig_y2 - orig_y1))
        img_w, img_h = line_image.size
        # 尺寸不符（native 裁切可能有 1px 误差）则跳过裁边
        if abs(img_w - expected_w) > 1 or abs(img_h - expected_h) > 1:
            return list(orig_bbox)
        try:
            import numpy as _np
            gray = _np.array(line_image.convert("L"))
            mask = gray < 200
            if not mask.any():
                # 纯白行，保持原 bbox
                return list(orig_bbox)
            # 竖排：转置 mask，将左右边框收缩映射为上下边框收缩
            if is_vertical:
                mask = mask.T
            img_h_full, img_w_full = mask.shape

            # 内部辅助：对 [r0, r1) x [c0, c1) 子区域执行四边白边裁切，
            # 返回裁切后的 (r_min, r_max, c_min, c_max)（全图坐标）。
            def _trim_white_edges(mask_full, r0, r1, c0, c1):
                sub = mask_full[r0:r1, c0:c1]
                rows = _np.where(sub.any(axis=1))[0]
                cols = _np.where(sub.any(axis=0))[0]
                if len(rows) == 0 or len(cols) == 0:
                    return r0, r1, c0, c1
                nr_min = r0 + int(rows[0])
                nr_max = r0 + int(rows[-1]) + 1
                nc_min = c0 + int(cols[0])
                nc_max = c0 + int(cols[-1]) + 1
                return nr_min, nr_max, nc_min, nc_max

            # Step A：第一次白边裁切（在全图范围内）
            r_min, r_max, c_min, c_max = _trim_white_edges(
                mask, 0, img_h_full, 0, img_w_full
            )

            # Step B：上下边框向内收缩（左右边框不收缩），各自最多收缩 1/3
            if r_max - r_min > 1:
                H = r_max - r_min
                max_shrink = max(1, H // 3)
                # 上边界搜索范围 [r_min, r_min + max_shrink)
                upper_search_end = min(r_min + max_shrink, r_max)
                if upper_search_end > r_min:
                    upper_counts = mask[r_min:upper_search_end].sum(axis=1)
                    upper_all_white = _np.where(upper_counts == 0)[0]
                    if len(upper_all_white) > 0:
                        # 上边框：第一个全白行作为新上界
                        new_r_min = r_min + int(upper_all_white[0])
                    else:
                        # 无全白行：取黑色像素最少的行（第一个最小值）作为新上界
                        upper_min_val = int(_np.min(upper_counts))
                        upper_min_idx = _np.where(upper_counts == upper_min_val)[0]
                        new_r_min = r_min + int(upper_min_idx[0])
                else:
                    new_r_min = r_min

                # 下边界搜索范围 (r_max - max_shrink, r_max)
                lower_search_start = max(r_min, r_max - max_shrink)
                if lower_search_start < r_max:
                    lower_counts = mask[lower_search_start:r_max].sum(axis=1)
                    lower_all_white = _np.where(lower_counts == 0)[0]
                    if len(lower_all_white) > 0:
                        # 下边框：最后一个全白行 + 1 作为新下界
                        new_r_max = lower_search_start + int(lower_all_white[-1]) + 1
                    else:
                        # 无全白行：取黑色像素最少的行（最后一个最小值 + 1）作为新下界
                        lower_min_val = int(_np.min(lower_counts))
                        lower_min_idx = _np.where(lower_counts == lower_min_val)[0]
                        new_r_max = lower_search_start + int(lower_min_idx[-1]) + 1
                else:
                    new_r_max = r_max

                # 仅在收缩结果有效时应用
                if new_r_min < new_r_max:
                    r_min, r_max = new_r_min, new_r_max

            # Step C：第二次白边裁切（对 Step B 结果再次四边裁切）
            r_min, r_max, c_min, c_max = _trim_white_edges(
                mask, r_min, r_max, c_min, c_max
            )

            # 竖排：mask 已转置，r 对应原 x 方向、c 对应原 y 方向，需互换回来
            if is_vertical:
                new_x1 = orig_x1 + r_min
                new_y1 = orig_y1 + c_min
                new_x2 = orig_x1 + r_max
                new_y2 = orig_y1 + c_max
            else:
                new_x1 = orig_x1 + c_min
                new_y1 = orig_y1 + r_min
                new_x2 = orig_x1 + c_max
                new_y2 = orig_y1 + r_max
            return [new_x1, new_y1, new_x2, new_y2]
        except Exception:
            return list(orig_bbox)

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

                # 对行切片四边裁切白色边缘，得到紧贴文字的新 bbox
                trimmed_bbox = self._trim_line_bbox(line_image, line_bbox)

                line_slice = LineSlice(
                    page_num=page_num,
                    bbox=trimmed_bbox,
                    polygon=[],
                    text=line_text,
                    confidence=line_score,
                    chars=updated_chars,
                    image=line_image,
                )
                lines_result.append(line_slice)

            page_lines[page_num] = lines_result

        return page_lines
