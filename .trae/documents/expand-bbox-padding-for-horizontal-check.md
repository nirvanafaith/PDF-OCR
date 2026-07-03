# 横校环节字符截取扩展边距计划

## 问题描述
在横校环节根据字符 bbox 大小截取 PDF 图片时，当前截取范围刚好等于 bbox 边界，导致字符边缘可能被裁切不完整。

## 解决方案
将 bbox 的四边往外扩展 3 像素（padding=3），确保字符完整显示。

## 修改位置
**文件**: `ocr_engine/rapidocr_engine.py`  
**方法**: `parse_and_group`  
**行号**: 188-191

## 当前代码
```python
crop_x1 = max(0, int(round(bbox_flat[0])))
crop_y1 = max(0, int(round(bbox_flat[1])))
crop_x2 = min(img_width, int(round(bbox_flat[2])))
crop_y2 = min(img_height, int(round(bbox_flat[3])))
```

## 修改后代码
```python
padding = 3
crop_x1 = max(0, int(round(bbox_flat[0])) - padding)
crop_y1 = max(0, int(round(bbox_flat[1])) - padding)
crop_x2 = min(img_width, int(round(bbox_flat[2])) + padding)
crop_y2 = min(img_height, int(round(bbox_flat[3])) + padding)
```

## 实现步骤
1. 在 `ocr_engine/rapidocr_engine.py` 的 `parse_and_group` 方法中，在第 188 行之前添加 `padding = 3`
2. 修改 crop 坐标计算，将 x1/y1 减去 padding，将 x2/y2 加上 padding
3. 验证修改后的代码能正常运行

## 影响范围
- 仅影响横校环节的字符切片显示
- 不影响 OCR 识别结果
- 不影响纵校环节
