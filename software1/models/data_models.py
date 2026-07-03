from dataclasses import dataclass, field
from typing import List, Optional, Tuple


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
    """

    page_num: int
    bbox: List[float]
    image: object = None
    text: str = ""
    line_id: int = -1
    char_id: int = -1


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
    """

    text: str
    bbox: List[float]
    page_num: int
    font_size: float = 12.0
    ignored: bool = False


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
