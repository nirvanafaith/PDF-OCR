# 实施计划：横校悬停全宽预览 + 字体大小精确嵌字

## 概述

两个任务：
1. 横校阶段鼠标悬停文字时，显示的切片图像宽度横跨整个PDF页面（左边界到右边界），保持上下Y坐标不变
2. 研究RapidOCR是否能提供原始字体大小信息，使嵌字时文字大小与PDF原图一致

---

## 任务1：横校悬停全宽预览

### 当前状态分析

[horizontal_check_window.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/ui/horizontal_check_window.py) 中的悬停预览逻辑：

1. **`_make_slice_pixmap`** (第334-367行)：从页面图像裁剪行切片区域
   - 优先使用 `ls.image`（预裁剪的行图像）
   - 否则从 `page_images` 按 bbox 裁剪，加20px边距
   - 裁剪范围：`x1 = bbox[0]-20, x2 = bbox[2]+20`（仅比文字区域宽40px）

2. **eventFilter悬停显示** (第307-326行)：
   - `line_w = (ls.bbox[2] - ls.bbox[0]) * self.zoom_level` — 按行bbox宽度缩放
   - `line_x = ls.bbox[0] * self.zoom_level` — 按行bbox X坐标定位
   - 预览图显示在文字上方

### 修改方案

#### 修改1：`_make_slice_pixmap` 方法

始终从 `page_images` 裁剪全宽切片，不再使用 `ls.image`：

```python
def _make_slice_pixmap(self, ls: LineSlice):
    # 始终从页面图像裁剪，宽度横跨整个页面
    if (self.page_images is not None
        and ls.page_num < len(self.page_images)):
        page_img = self.page_images[ls.page_num]
        bbox = ls.bbox
        pad = 20
        x1 = 0  # 从页面左边界开始
        y1 = max(int(bbox[1]) - pad, 0)
        x2 = page_img.width  # 到页面右边界结束
        y2 = min(int(bbox[3]) + pad, page_img.height)
        if x2 <= x1 or y2 <= y1:
            return None
        cropped = page_img.crop((x1, y1, x2, y2))
        return self._pil_to_pixmap(cropped)
    return None
```

#### 修改2：eventFilter悬停显示逻辑

缩放和定位改为全页面宽度：

```python
if pixmap is not None and pixmap.width() > 0:
    # 使用完整页面宽度缩放
    page_img = self.page_images[self.current_page]
    full_w = page_img.width * self.zoom_level
    scale_x = full_w / pixmap.width()
    target_w = max(1, int(pixmap.width() * scale_x))
    target_h = max(1, int(pixmap.height() * scale_x))
    scaled_pixmap = pixmap.scaled(
        target_w, target_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pi = QGraphicsPixmapItem(scaled_pixmap)
    pi_h = scaled_pixmap.height()
    line_x = 0  # 从页面左边界开始
    line_y = ls.bbox[1] * self.zoom_level
    pi.setPos(line_x, line_y - pi_h)
    pi.setZValue(100)
    pi.setData(0, id(ls))
    self.scene.addItem(pi)
    self._hover_pixmap_item = pi
```

---

## 任务2：字体大小精确嵌字

### 研究结论

**RapidOCR不直接输出字体大小**，但提供字符级边界框(bounding box)。边界框的高度即为文字在图像中的像素高度，可以据此推算字体大小。

### 当前状态分析

| 文件 | 当前计算方式 | 问题 |
|------|-------------|------|
| [pdf_output.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/pdf_processor/pdf_output.py#L108) 第108行 | `font_size = bbox_height * 0.6` | 0.6系数过小，嵌字明显比原文小 |
| [batch_ocr.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/batch_ocr.py#L233) 第233行 | `font_size = bbox_height * 0.6` | 同上 |
| [refine_window.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/ui/refine_window.py#L604) 第604行 | `font_size = bbox[3] - bbox[1]` | 使用完整bbox高度，显示较准确 |

### 字体大小推算原理

1. **坐标系一致性**：PDF输出画布尺寸 = 图像像素尺寸（`c.setPageSize((page_width, page_height))`），因此1 PDF单位 = 1 像素
2. **OCR bbox高度** = 文字在200DPI图像中的像素高度，包含检测模型添加的少量padding
3. **ReportLab font_size** = 字体的em-square大小，中文字符实际渲染高度 ≈ font_size × 0.87（微软雅黑）
4. **推算公式**：
   - OCR bbox高度 ≈ 实际文字高度 × (1 + padding比例)
   - 实际文字高度 ≈ font_size × 0.87
   - 因此：font_size ≈ bbox_height × (1 - padding) / 0.87
   - 假设padding约15%：font_size ≈ bbox_height × 0.85 / 0.87 ≈ bbox_height × 0.98
   - 保守取值：**font_size = bbox_height × 0.85**

### 修改方案

#### 修改1：`pdf_processor/pdf_output.py` 第108行

```python
# 旧：font_size = bbox_height * 0.6
# 新：使用0.85系数，更准确地匹配原文文字大小
font_size = bbox_height * 0.85
```

#### 修改2：`batch_ocr.py` 第233行

```python
# 旧：font_size = bbox_height * 0.6
# 新：使用0.85系数
font_size = bbox_height * 0.85
```

#### 修改3：`ui/refine_window.py` 第604行

当前使用 `font_size = bbox[3] - bbox[1]`（完整bbox高度），在显示层面已经比较准确，保持不变。

---

## 验证步骤

1. 运行应用，进入横校阶段，鼠标悬停文字，确认预览图横跨整个页面宽度
2. 完成全流程，生成PDF，对比嵌字大小与原文大小是否接近
3. 检查精修阶段文字显示是否正常
