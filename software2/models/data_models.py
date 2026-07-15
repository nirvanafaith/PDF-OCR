from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# 中文字号标准档位：档位号 → 磅值（pt）
# 一号=26pt, 二号=22pt, 三号=16pt, 四号=14pt, 五号=10.5pt
FONT_SIZE_GRADES = {1: 26, 2: 22, 3: 16, 4: 14, 5: 10.5}


def match_font_grade(line_height_pt):
    """根据行框高度（磅值）匹配最接近的中文字号档位号。

    遍历 FONT_SIZE_GRADES，返回磅值差最小的档位号（1-5）。
    当输入为 None 或非正数时，回退到五号（最小档位）。
    五号收容上界为 15.0pt（小于该值直接归五号）。

    Args:
        line_height_pt: 行框高度，单位磅（pt）。

    Returns:
        int: 档位号（1-5）。
    """
    if not line_height_pt or line_height_pt <= 0:
        return 5
    # 五号字放宽收容：上界 15.0pt
    if line_height_pt < 15.0:
        return 5
    best_grade = 5
    best_diff = None
    for grade, pt in FONT_SIZE_GRADES.items():
        diff = abs(line_height_pt - pt)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_grade = grade
    return best_grade


def font_name_for_grade(grade: int) -> str:
    """根据字号档位返回对应的中文字体名。

    字体规则：
        - 档位 1、2（一号、二号）：使用黑体 SimHei
        - 档位 3、4、5（三号、四号、五号）：使用书宋体 SimSun

    Args:
        grade: 字号档位号（1-5）。

    Returns:
        str: 字体名（"SimHei" 或 "SimSun"）。未知档位回退到 "SimSun"。
    """
    if grade in (1, 2):
        return "SimHei"
    return "SimSun"


# ASCII 字母/数字专用字体名
LATIN_FONT_NAME = "Times New Roman"


def is_latin_alnum(ch: str) -> bool:
    """判断字符是否为 ASCII 拉丁字母或数字（a-z, A-Z, 0-9）。

    仅匹配单字符；ASCII 标点符号（如 . , : ; -）返回 False，
    保持原中文字体。

    Args:
        ch: 待检测的字符串（预期为单字符）。

    Returns:
        bool: True 表示是 ASCII 字母或数字，False 表示其他。
    """
    if len(ch) != 1:
        return False
    c = ch[0]
    return ('0' <= c <= '9') or ('a' <= c <= 'z') or ('A' <= c <= 'Z')


def font_name_for_char(ch: str, grade: int) -> str:
    """根据字符类型和字号档位返回字体名。

    ASCII 字母/数字使用 Times New Roman；其他字符（含中文、标点）
    按档位规则使用 SimHei(1,2号) 或 SimSun(3,4,5号)。

    Args:
        ch: 单个字符。
        grade: 字号档位号（1-5）。

    Returns:
        str: 字体名（"Times New Roman"、"SimHei" 或 "SimSun"）。
    """
    if is_latin_alnum(ch):
        return LATIN_FONT_NAME
    return font_name_for_grade(grade)


@dataclass
class TextLine:
    """OCR 识别的单行文本结果。

    存储一行文本的识别内容、置信度以及位置信息，是 OCR 页面结果的基本组成单元。
    被 OCREngine 使用。

    Attributes:
        text: 识别出的文本内容。
        confidence: 识别置信度，取值范围 0.0 ~ 1.0。
        bbox: 文本行的边界框，格式为 [x1, y1, x2, y2]。
        polygon: 文本行的多边形轮廓，格式为 [[x1, y1], [x2, y2], ...]。
    """

    text: str
    confidence: float
    bbox: List[float]
    polygon: List[List[float]]


@dataclass
class OCRPageResult:
    """单页 OCR 识别结果。

    包含一个页面的全部识别文本行、页面尺寸及检测到的语言信息。
    被 OCREngine 使用。

    Attributes:
        page_num: 页码，从 0 开始计数。
        image_bbox: 页面图像的边界框，格式为 [x1, y1, x2, y2]。
        text_lines: 该页面中所有识别出的文本行列表。
        languages: 该页面检测到的语言列表。
    """

    page_num: int
    image_bbox: List[float]
    text_lines: List[TextLine]
    languages: List[str]


@dataclass
class OCRResult:
    """完整文档的 OCR 识别结果。

    作为 OCR 识别的最顶层容器，包含文档所有页面的识别结果。
    被 OCREngine 使用。

    Attributes:
        pages: 所有页面的 OCR 识别结果列表。
    """

    pages: List[OCRPageResult]


@dataclass
class CharSlice:
    """单字符切片数据。

    表示从 OCR 结果中解析出的单个字符，包含位置、图像及归属信息。
    由 OCREngine.parse_and_group 创建，被 VerticalCheckWindow 使用。

    Attributes:
        page_num: 字符所在页码。
        bbox: 字符的边界框，格式为 [x1, y1, x2, y2]。
        image: 字符的图像对象，默认为 None。
        text: 字符的文本内容，默认为空字符串。
        line_id: 字符所属行的索引，默认为 -1 表示未分配。
        char_id: 字符在行内的索引，默认为 -1 表示未分配。
        score: 字符识别置信度，默认为 1.0。
    """

    page_num: int
    bbox: List[float]
    image: object = None
    text: str = ""
    line_id: int = -1
    char_id: int = -1
    score: float = 1.0

    def to_dict(self):
        """序列化为可 JSON 化的字典。

        image 字段为运行期对象，不参与序列化。
        """
        return {
            'page_num': self.page_num,
            'bbox': list(self.bbox) if self.bbox else [0, 0, 0, 0],
            'text': self.text,
            'line_id': self.line_id,
            'char_id': self.char_id,
            'score': self.score,
        }

    @classmethod
    def from_dict(cls, d):
        """从字典构造 CharSlice，image 置 None（需由调用方重新裁切）。"""
        return cls(
            page_num=d.get('page_num', 0),
            bbox=d.get('bbox', [0, 0, 0, 0]),
            image=None,
            text=d.get('text', ''),
            line_id=d.get('line_id', -1),
            char_id=d.get('char_id', -1),
            score=d.get('score', 1.0),
        )


@dataclass
class LineSlice:
    """单行文本切片数据。

    表示从 OCR 结果中构建的一行文本，包含位置、轮廓、置信度及字符组成。
    由 OCREngine.build_line_data 创建，被 HorizontalCheckWindow 和 RefineWindow 使用。

    Attributes:
        page_num: 文本行所在页码。
        bbox: 文本行的边界框，格式为 [x1, y1, x2, y2]。
        polygon: 文本行的多边形轮廓，格式为 [[x1, y1], [x2, y2], ...]。
        text: 文本行的完整文本内容。
        confidence: 识别置信度，取值范围 0.0 ~ 1.0。
        chars: 该行包含的字符切片列表，默认为空列表。
        image: 文本行的图像对象，默认为 None。
    """

    page_num: int
    bbox: List[float]
    polygon: List[List[float]]
    text: str
    confidence: float
    chars: list = field(default_factory=list)
    image: object = None

    def to_dict(self):
        """序列化为可 JSON 化的字典。

        image 字段为运行期对象，不参与序列化。
        chars 元素若为数据类（含 to_dict）则递归序列化，否则原样保留（如已是字典）。
        _ignored 为横校窗口动态设置的忽略标记，一并保留。
        """
        chars_serialized = []
        for c in self.chars:
            if hasattr(c, 'to_dict'):
                chars_serialized.append(c.to_dict())
            else:
                chars_serialized.append(c)
        return {
            'page_num': self.page_num,
            'bbox': list(self.bbox) if self.bbox else [0, 0, 0, 0],
            'polygon': [list(p) for p in self.polygon] if self.polygon else [],
            'text': self.text,
            'confidence': self.confidence,
            'chars': chars_serialized,
            'ignored': bool(getattr(self, '_ignored', False)),
        }

    @classmethod
    def from_dict(cls, d):
        """从字典构造 LineSlice，image 置 None，并恢复 _ignored 标记。"""
        obj = cls(
            page_num=d.get('page_num', 0),
            bbox=d.get('bbox', [0, 0, 0, 0]),
            polygon=d.get('polygon', []),
            text=d.get('text', ''),
            confidence=d.get('confidence', 1.0),
            chars=d.get('chars', []),
            image=None,
        )
        if d.get('ignored', False):
            obj._ignored = True
        return obj


@dataclass
class CorrectedChar:
    """校对后的单字符数据。

    表示经过人工校对的单个字符，包含文本、位置及是否忽略的标记。
    由 RefineWindow._build_corrected_chars 创建，被 PDFOutputGenerator.generate 使用。

    Attributes:
        text: 校对后的字符文本。
        bbox: 字符的边界框，格式为 [x1, y1, x2, y2]。
        page_num: 字符所在页码。
        ignored: 是否在校对中被标记为忽略，默认为 False。
    """

    text: str
    bbox: List[float]
    page_num: int
    ignored: bool = False


@dataclass
class CorrectedLine:
    """校对后的单行文本数据。

    表示经过人工校对的一行文本，包含文本、位置及是否忽略的标记。
    由 HorizontalCheckWindow._build_corrected_lines 创建。

    Attributes:
        text: 校对后的行文本内容。
        bbox: 文本行的边界框，格式为 [x1, y1, x2, y2]。
        page_num: 文本行所在页码。
        ignored: 是否在校对中被标记为忽略，默认为 False。
    """

    text: str
    bbox: List[float]
    page_num: int
    ignored: bool = False


@dataclass
class VerticalCheckData:
    """纵校检查数据。

    预留数据类，用于存储纵向校对流程中的字符切片数据。

    Attributes:
        char_slices: 字符切片字典，键为页码，值为该页的字符切片列表。
    """

    char_slices: dict


@dataclass
class HorizontalCheckData:
    """横校检查数据。

    预留数据类，用于存储横向校对流程中的字符切片数据。

    Attributes:
        char_slices: 字符切片字典，键为页码，值为该页的字符切片列表。
    """

    char_slices: dict


@dataclass
class FinalCharList:
    """最终字符列表。

    预留数据类，用于存储校对完成后的最终字符集合。

    Attributes:
        chars: 校对完成后的字符列表。
    """

    chars: List[CorrectedChar]


@dataclass
class RefineTextItem:
    """精排文本项数据。

    表示精排阶段的一个文本项，包含文本、位置、字号及是否忽略的标记。
    由 RefineWindow._convert_chars 创建，被 MovableTextItem 使用。

    Attributes:
        text: 文本内容。
        bbox: 文本的边界框，格式为 [x1, y1, x2, y2]。
        page_num: 文本所在页码。
        font_size: 字体大小，默认为 12.0。
        ignored: 是否在校对中被标记为忽略，默认为 False。
        line_bbox: 所属行框的边界框，格式为 [x1, y1, x2, y2]，
            用于字号档位匹配与字体选择，默认为 [0, 0, 0, 0]。
        font_family: 自定义字体族名，None表示使用默认档位字体。
            用户通过右键"修改字体"设置后存储，PDF导出时优先使用。
    """

    text: str
    bbox: List[float]
    page_num: int
    font_size: float = 12.0
    ignored: bool = False
    line_bbox: List[float] = field(default_factory=lambda: [0, 0, 0, 0])
    font_family: Optional[str] = None

    def to_dict(self):
        """序列化为可 JSON 化的字典。"""
        return {
            'text': self.text,
            'bbox': list(self.bbox) if self.bbox else [0, 0, 0, 0],
            'page_num': self.page_num,
            'font_size': self.font_size,
            'ignored': self.ignored,
            'line_bbox': list(self.line_bbox) if self.line_bbox else [0, 0, 0, 0],
            'font_family': self.font_family,
        }

    @classmethod
    def from_dict(cls, d):
        """从字典构造 RefineTextItem。"""
        return cls(
            text=d.get('text', ''),
            bbox=d.get('bbox', [0, 0, 0, 0]),
            page_num=d.get('page_num', 0),
            font_size=d.get('font_size', 12.0),
            ignored=d.get('ignored', False),
            line_bbox=d.get('line_bbox', [0, 0, 0, 0]),
            font_family=d.get('font_family'),
        )


@dataclass
class TextBox:
    """用户手动绘制的文本框数据。

    表示在画框步骤中由用户在PDF页面上绘制的矩形区域，
    用于限制OCR识别的范围，仅识别框内文本。

    Attributes:
        page_num: 文本框所在页码。
        bbox: 文本框的边界框，格式为 [x1, y1, x2, y2]，
            坐标为相对于页面图像的像素坐标。
    """

    page_num: int
    bbox: List[float]


def flatten_bbox(bbox):
    """将多边形边界框转换为轴对齐的矩形边界框。

    当输入为四点多边形格式 [[x1, y1], [x2, y2], [x3, y3], [x4, y4]] 时，
    取所有点的 x、y 坐标的最小值和最大值，转换为 [xmin, ymin, xmax, ymax] 格式。
    若输入已经是矩形格式则原样返回；若输入无效则返回 [0, 0, 0, 0]。

    被 OCREngine.parse_and_group 和 OCREngine.build_line_data 调用。

    Args:
        bbox: 边界框数据，支持以下格式：
            - 四点多边形格式：[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
            - 矩形格式：[x1, y1, x2, y2]

    Returns:
        List[float]: 轴对齐的矩形边界框，格式为 [xmin, ymin, xmax, ymin]。
            若输入无效则返回 [0, 0, 0, 0]。
    """
    if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(p, list) for p in bbox):
        x_coords = [p[0] for p in bbox]
        y_coords = [p[1] for p in bbox]
        return [min(x_coords), min(y_coords), max(x_coords), max(y_coords)]
    return bbox if isinstance(bbox, list) else [0, 0, 0, 0]