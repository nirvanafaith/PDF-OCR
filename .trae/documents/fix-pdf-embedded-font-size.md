# 修复PDF嵌入文字过大问题

## 问题描述

在精修环节生成PDF时，嵌入到PDF上的文字尺寸过大，超出了原始字符的实际大小。

## 根因分析

问题出在 [pdf_output.py:106](file:///c:/Users/E-VR/Documents/trae_projects/横校/pdf_processor/pdf_output.py#L106)：

```python
font_size = y2 - y1
```

当前逻辑直接将字符边界框（bbox）的高度作为 reportlab 的 `font_size`，存在两个问题：

1. **OCR边界框包含内边距**：OCR识别产生的bbox通常比原始字符略大（包含5%-15%的padding），直接用bbox高度作为字号会使嵌入文字大于原始字符。
2. **基线定位不准确**：`lly = page_height - y2` 将基线放在bbox底部，但CJK字体的基线并不在字符底部，而是在em-square底部附近（约12%位置），导致文字垂直方向偏移。

## 解决方案

修改 `pdf_output.py` 中的字符渲染逻辑：

1. **缩小字号**：将 `font_size` 设为 `bbox高度 × 缩放因子`（默认0.9），使嵌入文字与原始字符大小一致
2. **垂直居中**：调整基线位置 `lly`，使文字在bbox内垂直居中
3. **水平适配**：对多字符文本检查渲染宽度，若超出bbox宽度则按比例缩小字号

## 具体代码修改

### 文件：`pdf_processor/pdf_output.py`

#### 修改1：新增 import

在文件顶部 import 区域添加：

```python
from reportlab.pdfbase.pdfmetrics import stringWidth
```

#### 修改2：修改字符渲染循环（第102-114行）

将原来的：

```python
for char in chars_by_page.get(page_idx, []):
    x1, y1, x2, y2 = char.bbox
    llx = x1
    lly = page_height - y2
    font_size = y2 - y1
    if font_size < 1:
        font_size = 1
    c.setFont(default_font, font_size)
    if text_color == "transparent":
        c.setFillColor(Color(0, 0, 0, alpha=0))
    else:
        c.setFillColorRGB(1, 0, 0)
    c.drawString(llx, lly, char.text)
```

替换为：

```python
for char in chars_by_page.get(page_idx, []):
    x1, y1, x2, y2 = char.bbox
    bbox_height = y2 - y1
    bbox_width = x2 - x1
    font_size = bbox_height * 0.9
    if font_size < 1:
        font_size = 1
    text_w = stringWidth(char.text, default_font, font_size)
    if text_w > bbox_width and bbox_width > 0:
        font_size = font_size * bbox_width / text_w
    c.setFont(default_font, font_size)
    lly = (page_height - y2) + (bbox_height - font_size) / 2
    llx = x1
    if text_color == "transparent":
        c.setFillColor(Color(0, 0, 0, alpha=0))
    else:
        c.setFillColorRGB(1, 0, 0)
    c.drawString(llx, lly, char.text)
```

### 修改要点说明

| 修改点 | 原逻辑 | 新逻辑 | 原因 |
|--------|--------|--------|------|
| 字号计算 | `font_size = y2 - y1` | `font_size = bbox_height * 0.9` | OCR的bbox比实际字符大，0.9倍使嵌入文字与原字等大 |
| 垂直定位 | `lly = page_height - y2` | `lly = (page_height - y2) + (bbox_height - font_size) / 2` | 基线上移使文字在bbox内垂直居中 |
| 水平适配 | 无 | `stringWidth` 检查 + 按比例缩小 | 多字符文本可能超出bbox宽度 |

## 影响范围

- 仅修改 `pdf_processor/pdf_output.py` 一个文件
- 不影响精修窗口UI中的文字显示（UI使用Qt的 `QFont.setPixelSize`）
- 不影响数据模型（`CorrectedChar` 无 `font_size` 字段，字号始终从bbox计算）
- 缩放因子0.9为经验值，如需微调可直接修改该常量
