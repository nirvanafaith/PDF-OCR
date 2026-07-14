"""文字与背景墨迹对齐算法模块。

本模块实现二值模板匹配：给定文字掩码 T 和背景墨迹掩码 I，
寻找平移量 (dx, dy) 使两者交集面积最大化，从而实现渲染文字
与扫描背景中墨迹的最佳对齐。

模块仅依赖 PyQt5.QtCore / PyQt5.QtGui（用于文字渲染）、PIL（图像裁切）
和 numpy（数组运算），不导入任何 UI 组件，保持低耦合。
"""

import numpy as np
from PIL import Image
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QImage, QPainter, QPen, QFont

try:
    from native import find_best_offset as _native_find_best_offset
except Exception:
    _native_find_best_offset = None


def render_text_mask(text, font, w, h):
    """使用 QPainter 渲染文字掩码。

    在白底黑字的 QImage 上绘制指定文字，再转换为 bool 型 numpy 数组，
    其中 True 表示文字像素（黑色像素）。

    参数:
        text (str): 待渲染的文本内容
        font (QFont): 字体对象，直接用于 setFont
        w (int): 输出图像宽度（像素）
        h (int): 输出图像高度（像素）

    返回:
        np.ndarray: 形状为 (h, w) 的 bool 数组，True 表示文字像素
    """
    # 创建白底 ARGB32 预乘格式图像
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.white)

    # 使用 QPainter 绘制黑字
    painter = QPainter(img)
    painter.setPen(QPen(Qt.black))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, text)
    painter.end()

    # 通过 constBits 取得图像数据并转为 numpy 数组
    ptr = img.constBits()
    ptr.setsize(h * w * 4)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, w, 4)

    # 取 R 通道二值化：黑字（像素值 < 128）为 True
    text_mask = arr[:, :, 0] < 128
    return text_mask


def extract_ink_mask(bg_img, bbox, radius):
    """从背景图像中提取墨迹掩码。

    根据 bbox 扩展 radius 像素的裁切区域，从背景图像中裁切并二值化，
    得到 bool 型墨迹掩码（非白色像素为 True）。

    参数:
        bg_img (PIL.Image.Image): 背景图像（300DPI）
        bbox (list): 边界框 [x1, y1, x2, y2]，原始坐标
        radius (int): 四周扩展的像素半径

    返回:
        np.ndarray: bool 数组，True 表示墨迹（非白色）像素
    """
    x1, y1, x2, y2 = bbox
    bw = int(x2 - x1)
    bh = int(y2 - y1)

    # 理想裁切区域：bbox 四周扩展 radius 像素
    ix1 = int(x1 - radius)
    iy1 = int(y1 - radius)
    ix2 = int(x2 + radius)
    iy2 = int(y2 + radius)

    # 钳制到图像边界内
    cx1 = max(0, ix1)
    cy1 = max(0, iy1)
    cx2 = min(bg_img.width, ix2)
    cy2 = min(bg_img.height, iy2)

    # 裁切并转为灰度 numpy 数组
    crop_region = bg_img.crop((cx1, cy1, cx2, cy2))
    gray = np.array(crop_region.convert('L'))

    # 二值化：非白色（灰度 < 200）为 True
    ink_mask = gray < 200

    # 补齐到理想尺寸 (bh+2*radius, bw+2*radius)，缺失部分填 False（无墨迹）
    # 这样 find_best_offset 的 radius 偏移假设始终成立
    target_h = bh + 2 * radius
    target_w = bw + 2 * radius
    ch, cw = ink_mask.shape
    if ch < target_h or cw < target_w:
        padded = np.zeros((target_h, target_w), dtype=bool)
        # 实际裁切左上角 (cx1,cy1) 在理想掩码中的偏移：
        # 理想左上角 (ix1,iy1)，因钳制 cy1>=iy1，故顶部被截断 pad_top=cy1-iy1 行
        pad_top = max(0, cy1 - iy1)
        pad_left = max(0, cx1 - ix1)
        padded[pad_top:pad_top + ch, pad_left:pad_left + cw] = ink_mask
        ink_mask = padded

    return ink_mask


def find_best_offset(text_mask, ink_mask, radius):
    """在指定半径范围内搜索使文字与墨迹重叠最大的偏移量。

    在 (dx, dy) ∈ [-radius, radius] 范围内遍历所有偏移，对每个偏移
    从 ink_mask 中取出与 text_mask 对齐的区域，计算两者交集面积，
    返回使交集面积最大的 (dx, dy)。

    参数:
        text_mask (np.ndarray): 文字掩码，形状 (th, tw)
        ink_mask (np.ndarray): 墨迹掩码，四周边界已扩展 radius 像素
        radius (int): 搜索半径

    返回:
        tuple: (best_dx, best_dy, best_overlap) 最佳偏移量和交集像素数；
               若墨迹掩码全零则返回 (0, 0, 0)
    """
    th, tw = text_mask.shape
    # 优先使用 H7 native 加速；失败回落 numpy
    try:
        result = _native_find_best_offset(text_mask, ink_mask, radius)
        if result is not None:
            dx, dy = tuple(result)
            oy = radius + dy
            ox = radius + dx
            if oy >= 0 and ox >= 0 and oy + th <= ink_mask.shape[0] and ox + tw <= ink_mask.shape[1]:
                region = ink_mask[oy:oy + th, ox:ox + tw]
                overlap = int(np.count_nonzero(text_mask & region))
            else:
                overlap = 0
            return (dx, dy, overlap)
    except Exception:
        pass
    # ---- numpy fallback（原实现）----
    # 全零墨迹掩码无法对齐，直接返回零偏移
    if ink_mask.sum() == 0:
        return (0, 0, 0)

    best_overlap = -1
    best_dx, best_dy = 0, 0

    # 遍历所有候选偏移
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            # ink_mask 已在四周扩展 radius，故偏移起点为 radius + d
            oy = radius + dy
            ox = radius + dx
            if oy < 0 or ox < 0:
                continue
            if oy + th > ink_mask.shape[0] or ox + tw > ink_mask.shape[1]:
                continue
            # 取出与 text_mask 对齐的墨迹区域并计算交集
            region = ink_mask[oy:oy + th, ox:ox + tw]
            overlap = np.count_nonzero(text_mask & region)
            if overlap > best_overlap:
                best_overlap = overlap
                best_dx, best_dy = dx, dy

    return (best_dx, best_dy, best_overlap)


def align_text_to_background(text, font, bbox, bg_img, radius=8):
    """将渲染文字与背景墨迹对齐，返回最佳偏移量。

    主入口函数，依次执行：渲染文字掩码、提取背景墨迹掩码、
    搜索最佳偏移三步，返回使文字与墨迹重叠最大的平移量 (dx, dy)。

    参数:
        text (str): 待对齐的文本内容
        font (QFont): 渲染所用字体
        bbox (list): 文字边界框 [x1, y1, x2, y2]（300DPI 原始坐标）
        bg_img (PIL.Image.Image): 背景图像
        radius (int): 搜索半径，默认 8

    返回:
        tuple: (dx, dy, overlap) 最佳偏移量和交集像素数；
               空文本、无效尺寸或异常时返回 (0, 0, 0)
    """
    try:
        # 空文本无需对齐
        if not text:
            return (0, 0, 0)

        # 计算文字掩码尺寸
        w = int(bbox[2] - bbox[0])
        h = int(bbox[3] - bbox[1])
        if w <= 0 or h <= 0:
            return (0, 0, 0)

        # 三步对齐流程
        text_mask = render_text_mask(text, font, w, h)
        ink_mask = extract_ink_mask(bg_img, bbox, radius)
        dx, dy, overlap = find_best_offset(text_mask, ink_mask, radius)
        return (dx, dy, overlap)
    except Exception as e:
        # 异常时打印错误并返回零偏移，保证调用方安全
        print(f"align_text_to_background 对齐失败: {e}")
        return (0, 0, 0)
