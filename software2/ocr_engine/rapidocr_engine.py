import json
import os
import tempfile
import time
from pathlib import Path

from PIL import Image

from models.data_models import CharSlice, LineSlice, flatten_bbox


# 文件日志：进程崩溃后仍保留最后成功步骤，用于定位 native 硬崩溃点
_DEBUG_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "crash_debug.log")


def _debug_log(msg: str) -> None:
    """写入文件日志，即使进程崩溃也能保留最后记录。"""
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            f.flush()
    except Exception:
        pass


class OCREngine:
    """基于 RapidOCR 的 OCR 识别引擎，提供 PDF 文档的文字识别与结构化处理能力。

    该引擎封装了 RapidOCR（PP-OCRv5 模型 + ONNXRuntime 引擎）的文本检测和文字识别流程，
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
        """初始化数据处理引擎。

        软件2仅使用数据处理方法，不需要OCR模型。
        """
        self.results = None

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

        result = self.engine(page_image, return_word_box=True, return_single_char_box=True)

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
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for page_idx, page_image in page_images_with_idx:
                future = executor.submit(self._recognize_page, page_image, page_idx, None)
                futures[future] = page_idx

            for future in as_completed(futures):
                page_idx = futures[future]
                results[page_idx] = future.result()
                if output_callback:
                    output_callback(f"第 {page_idx + 1} 页识别完成")

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
        格式，从对应页面图像中裁剪出字符区域（按边界框精确裁剪），并按
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
        _debug_log(f"parse_and_group 开始: {len(lines)} 行, {len(chars)} 字符, {len(page_images)} 页")
        print(f"[parse_and_group] 开始: {len(lines)} 行, {len(chars)} 字符, {len(page_images)} 页", flush=True)

        # 尝试加载 native H3 批量裁切
        try:
            from native import has_native as _has_native
            from native import batch_crop_qimage as _batch_crop
            _debug_log("native模块导入完成,即将调用has_native()")
            print("[parse_and_group] native模块导入完成,即将调用has_native()", flush=True)
            _native_ok = _has_native()
            _debug_log(f"has_native()返回: {_native_ok}")
            print(f"[parse_and_group] has_native()返回: {_native_ok}", flush=True)
            if not _native_ok:
                _debug_log("native不可用,使用Python fallback")
                print("[parse_and_group] native不可用,使用Python fallback", flush=True)
                _batch_crop = None
            else:
                _debug_log("native可用,使用H3加速")
                print("[parse_and_group] native可用,使用H3加速", flush=True)
        except Exception as e:
            _debug_log(f"native导入异常: {e}")
            print(f"[parse_and_group] native导入异常: {e}", flush=True)
            _batch_crop = None

        # 第一遍：收集所有字符的元数据与裁切坐标
        char_items = []  # [(char_data, char_text, page_num, bbox_flat, crop_coords, valid), ...]
        for char_data in chars:
            char_text = char_data.get("char", "")
            if not char_text:
                continue

            page_num = char_data.get("page_num", 0)
            bbox = char_data.get("box", [0, 0, 0, 0])
            bbox_flat = flatten_bbox(bbox)

            page_image = page_images[page_num] if page_num < len(page_images) else None
            img_width, img_height = page_image.size if page_image else (0, 0)

            crop_x1 = max(0, int(round(bbox_flat[0])))
            crop_y1 = max(0, int(round(bbox_flat[1])))
            crop_x2 = min(img_width, int(round(bbox_flat[2])))
            crop_y2 = min(img_height, int(round(bbox_flat[3])))
            valid = bool(page_image and crop_x2 > crop_x1 and crop_y2 > crop_y1)

            char_items.append((char_data, char_text, page_num, bbox_flat,
                               (crop_x1, crop_y1, crop_x2, crop_y2), valid))

        print(f"[parse_and_group] 第一遍完成: {len(char_items)} 个字符项", flush=True)
        _debug_log(f"第一遍完成: {len(char_items)} 个字符项")
        cropped_images = [None] * len(char_items)

        if _batch_crop is not None:
            # 按页分组批量裁切
            page_groups = {}
            for idx, item in enumerate(char_items):
                page_groups.setdefault(item[2], []).append(idx)

            for page_num, indices in page_groups.items():
                _debug_log(f"处理页 {page_num}: {len(indices)} 个字符")
                print(f"[parse_and_group] 处理页 {page_num}: {len(indices)} 个字符", flush=True)
                page_image = page_images[page_num] if page_num < len(page_images) else None
                if not page_image:
                    _debug_log(f"页 {page_num} 无图像,跳过")
                    print(f"[parse_and_group] 页 {page_num} 无图像,跳过", flush=True)
                    continue
                bboxes = [list(char_items[idx][4]) for idx in indices]
                results_bytes = None
                try:
                    page_image.load()  # 物化PIL图像，避免lazy image触发RecursionError
                    page_rgba = page_image.convert("RGBA").tobytes("raw", "RGBA")
                    img_w, img_h = page_image.size
                    # 防御：校验 buffer 大小，避免传给 native 的 buffer 越界导致 segfault
                    expected_len = img_w * img_h * 4
                    actual_len = len(page_rgba)
                    if actual_len != expected_len:
                        _debug_log(f"页 {page_num} buffer大小不匹配: got {actual_len}, expected {expected_len}, 使用Python fallback")
                        print(f"[parse_and_group] 页 {page_num} buffer大小不匹配: got {actual_len}, expected {expected_len}, 使用Python fallback", flush=True)
                        results_bytes = None
                    else:
                        _debug_log(f"页 {page_num} 准备H3调用: img_w={img_w}, img_h={img_h}, bboxes={len(bboxes)}")
                        print(f"[parse_and_group] 页 {page_num} 准备H3调用: img_w={img_w}, img_h={img_h}, bboxes={len(bboxes)}", flush=True)
                        results_bytes = _batch_crop(page_rgba, img_w, img_h, bboxes, 0)
                        _debug_log(f"页 {page_num} H3调用完成,返回{len(results_bytes) if results_bytes else 0}个切片")
                        print(f"[parse_and_group] 页 {page_num} H3调用完成,返回{len(results_bytes) if results_bytes else 0}个切片", flush=True)
                except Exception as e:
                    _debug_log(f"页 {page_num} H3调用异常: {e}")
                    print(f"[parse_and_group] 页 {page_num} H3调用异常: {e}", flush=True)
                    results_bytes = None

                if results_bytes is None:
                    # native 调用失败，回退到逐字符 crop
                    for idx in indices:
                        if char_items[idx][5]:
                            page_image.load()  # 物化PIL图像，避免lazy image触发RecursionError
                            cropped_images[idx] = page_image.crop(char_items[idx][4])
                else:
                    for i, idx in enumerate(indices):
                        if not char_items[idx][5]:
                            continue
                        rgba_bytes = results_bytes[i]
                        if not rgba_bytes:
                            continue
                        cx1, cy1, cx2, cy2 = char_items[idx][4]
                        crop_w = cx2 - cx1
                        crop_h = cy2 - cy1
                        try:
                            cropped_images[idx] = Image.frombytes(
                                "RGBA", (crop_w, crop_h), rgba_bytes)
                        except Exception:
                            page_image.load()  # 物化PIL图像，避免lazy image触发RecursionError
                            cropped_images[idx] = page_image.crop(char_items[idx][4])
                print(f"[parse_and_group] 页 {page_num} 裁切完成", flush=True)
                _debug_log(f"页 {page_num} 裁切完成")
        else:
            # 回退：原有逐字符 crop 逻辑
            print("[parse_and_group] 使用Python fallback逐字符crop", flush=True)
            _debug_log("使用Python fallback逐字符crop")
            for idx, item in enumerate(char_items):
                char_data, char_text, page_num, bbox_flat, crop_coords, valid = item
                if valid:
                    page_image = page_images[page_num]
                    page_image.load()  # 物化PIL图像，避免lazy image触发RecursionError
                    cropped_images[idx] = page_image.crop(crop_coords)
            print("[parse_and_group] Python fallback完成", flush=True)
            _debug_log("Python fallback完成")

        # 构建 CharSlice 对象并按字符文本分组
        for idx, (char_data, char_text, page_num, bbox_flat, crop_coords, valid) in enumerate(char_items):
            line_id = char_data.get("line_id", -1)
            char_id = char_data.get("char_id", -1)
            score = float(char_data.get("score", 1.0))
            suspect = bool(char_data.get("suspect", False))
            alt_char = char_data.get("alt_char", "")
            alt_score = float(char_data.get("alt_score", 0.0))

            char_slice = CharSlice(
                page_num=page_num,
                bbox=list(bbox_flat),
                image=cropped_images[idx],
                text=char_text,
                line_id=line_id,
                char_id=char_id,
                score=score,
                suspect=suspect,
                alt_char=alt_char,
                alt_score=alt_score,
            )

            if char_text not in grouped:
                grouped[char_text] = []
            grouped[char_text].append(char_slice)

        print(f"[parse_and_group] 全部完成: {len(grouped)} 种字符", flush=True)
        _debug_log(f"parse_and_group 全部完成: {len(grouped)} 种字符")
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

        # 尝试加载 native H3 批量裁切
        try:
            from native import has_native as _has_native
            from native import batch_crop_qimage as _batch_crop
            if not _has_native():
                _batch_crop = None
        except Exception:
            _batch_crop = None

        for page_num, page_lines_list in page_lines_map.items():
            page_image = page_images[page_num] if page_num < len(page_images) else None
            lines_result = []
            line_crop_meta = []  # [(line_slice, crop_coords, valid), ...]

            for line in page_lines_list:
                line_id = line.get("line_id", -1)
                line_text = line.get("text", "")
                line_score = line.get("score", 0)
                line_box = line.get("box", [0, 0, 0, 0])

                line_bbox = flatten_bbox(line_box)

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

                # 计算行裁切坐标（暂不裁切，收集后批量处理）
                crop_coords = (0, 0, 0, 0)
                valid = False
                if page_image:
                    x1 = max(0, int(round(line_bbox[0])))
                    y1 = max(0, int(round(line_bbox[1])))
                    x2 = min(page_image.size[0], int(round(line_bbox[2])))
                    y2 = min(page_image.size[1], int(round(line_bbox[3])))
                    if x2 > x1 and y2 > y1:
                        crop_coords = (x1, y1, x2, y2)
                        valid = True

                line_slice = LineSlice(
                    page_num=page_num,
                    bbox=list(line_bbox),
                    polygon=[],
                    text=line_text,
                    confidence=line_score,
                    chars=updated_chars,
                    image=None,
                )
                lines_result.append(line_slice)
                line_crop_meta.append((line_slice, crop_coords, valid))

            # 批量裁切本页所有行图像
            if _batch_crop is not None and page_image:
                bboxes = [list(m[1]) for m in line_crop_meta]
                results_bytes = None
                try:
                    page_rgba = page_image.convert("RGBA").tobytes("raw", "RGBA")
                    img_w, img_h = page_image.size
                    results_bytes = _batch_crop(page_rgba, img_w, img_h, bboxes, 0)
                except Exception:
                    results_bytes = None

                if results_bytes is None:
                    # native 调用失败，回退到逐行 crop
                    for ls, coords, valid in line_crop_meta:
                        if valid:
                            ls.image = page_image.crop(coords)
                else:
                    for i, (ls, coords, valid) in enumerate(line_crop_meta):
                        if not valid:
                            continue
                        rgba_bytes = results_bytes[i]
                        if not rgba_bytes:
                            continue
                        cx1, cy1, cx2, cy2 = coords
                        crop_w = cx2 - cx1
                        crop_h = cy2 - cy1
                        try:
                            ls.image = Image.frombytes(
                                "RGBA", (crop_w, crop_h), rgba_bytes)
                        except Exception:
                            ls.image = page_image.crop(coords)
            else:
                # 回退：原有逐行 crop 逻辑
                for ls, coords, valid in line_crop_meta:
                    if valid and page_image:
                        ls.image = page_image.crop(coords)

            page_lines[page_num] = lines_result

        return page_lines