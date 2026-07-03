# 修正OCR识别逻辑：整页识别+框内过滤

## 问题分析

当前 `OCREngine.run_ocr` 方法在有 regions（画框区域）时，对每个框单独裁剪图像后执行OCR识别：

```python
# 当前逻辑（第196-235行）
for region_bbox in page_regions:
    x1, y1, x2, y2 = [int(round(v)) for v in region_bbox]
    cropped = page_image.crop((x1, y1, x2, y2))
    page_lines, page_chars = self._recognize_page(cropped, page_idx, output_callback)
    # 坐标偏移回整页...
```

**问题**：
1. **性能差**：每个框单独调用OCR引擎推理，N个框需要N次推理
2. **识别不完整**：裁剪边界可能切断文字行，导致识别缺失
3. **跨框文字丢失**：一个文字行可能跨越两个框，裁剪后无法完整识别

## 修改方案

改为：对每页执行一次整页OCR识别，然后过滤结果只保留框内的内容。

### 修改文件：`ocr_engine/rapidocr_engine.py`

#### 1. 新增辅助方法 `_boxes_overlap`

```python
def _boxes_overlap(self, box1_flat, box2_flat):
    """判断两个 [x1, y1, x2, y2] 格式的框是否有交集"""
    x1 = max(box1_flat[0], box2_flat[0])
    y1 = max(box1_flat[1], box2_flat[1])
    x2 = min(box1_flat[2], box2_flat[2])
    y2 = min(box1_flat[3], box2_flat[3])
    return x1 < x2 and y1 < y2
```

#### 2. 修改 `run_ocr` 方法的 regions 分支

将当前的逐框裁剪识别逻辑替换为：

```python
if regions is not None and len(regions) > 0:
    page_regions = regions.get(page_idx, [])
    if not page_regions:
        continue

    # 整页识别
    page_lines, page_chars = self._recognize_page(page_image, page_idx, output_callback)

    # 过滤：只保留与某个region有交集的行和字符
    filtered_lines = []
    filtered_chars = []
    for line in page_lines:
        line_bbox = flatten_bbox(line.get("box", [0, 0, 0, 0]))
        for region_bbox in page_regions:
            if self._boxes_overlap(line_bbox, region_bbox):
                filtered_lines.append(line)
                # 保留该行下的所有字符
                for char in page_chars:
                    if char.get("line_id") == line.get("line_id"):
                        filtered_chars.append(char)
                break

    # 后续ID偏移和page_num设置逻辑不变...
```

### 关键设计决策

1. **行级过滤**：以OCR行为单位过滤，行与region有交集则保留整行及其所有字符。这比字符级过滤更合理，因为OCR识别本身就是按行组织的。

2. **交集判断而非包含判断**：使用交集（overlap）而非完全包含（contain），因为用户画的框可能不完全覆盖一个文字行，但只要行与框有交集就应该保留。

3. **性能提升**：从 N次OCR推理（N=框数）减少到 1次OCR推理（每页），大幅提升性能。

4. **识别质量提升**：整页识别不会切断文字行，识别更完整准确。

## 验证计划

1. 启动应用，加载PDF，画框后执行OCR识别
2. 确认识别结果只包含框内内容
3. 确认跨框文字行能被正确识别
4. 确认无框页面被跳过
5. 对比修改前后的识别结果质量
