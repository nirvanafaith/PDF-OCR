import json
import os
import tempfile
from pathlib import Path

from models.data_models import CharSlice, LineSlice, flatten_bbox


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

        for char_data in chars:
            char_text = char_data.get("char", "")
            if not char_text:
                continue

            page_num = char_data.get("page_num", 0)
            bbox = char_data.get("box", [0, 0, 0, 0])
            line_id = char_data.get("line_id", -1)
            char_id = char_data.get("char_id", -1)
            score = float(char_data.get("score", 1.0))

            bbox_flat = flatten_bbox(bbox)

            page_image = page_images[page_num] if page_num < len(page_images) else None
            img_width, img_height = page_image.size if page_image else (0, 0)

            crop_x1 = max(0, int(round(bbox_flat[0])))
            crop_y1 = max(0, int(round(bbox_flat[1])))
            crop_x2 = min(img_width, int(round(bbox_flat[2])))
            crop_y2 = min(img_height, int(round(bbox_flat[3])))

            cropped_image = None
            if page_image and crop_x2 > crop_x1 and crop_y2 > crop_y1:
                cropped_image = page_image.crop((crop_x1, crop_y1, crop_x2, crop_y2))

            char_slice = CharSlice(
                page_num=page_num,
                bbox=list(bbox_flat),
                image=cropped_image,
                text=char_text,
                line_id=line_id,
                char_id=char_id,
                score=score,
            )

            if char_text not in grouped:
                grouped[char_text] = []
            grouped[char_text].append(char_slice)

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

                line_image = None
                if page_image:
                    x1 = max(0, int(round(line_bbox[0])))
                    y1 = max(0, int(round(line_bbox[1])))
                    x2 = min(page_image.size[0], int(round(line_bbox[2])))
                    y2 = min(page_image.size[1], int(round(line_bbox[3])))
                    if x2 > x1 and y2 > y1:
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