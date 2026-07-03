# 字符框精修算法 - 优化chars.json中的单字边界框

## 需求分析

PDF中字与字之间有空白间隔，但OCR模型切分出的单字框往往会截断文字的一部分或多截到相邻字的一部分。需要通过图像分析优化每个字符的四条边，使边尽量经过纯白区域（字间空白），避免截断文字。

## 当前状态

- **chars.json生成位置**: `软件1/ocr_engine/rapidocr_engine.py` 的 `run_ocr` 方法，第302-305行
- **box格式**: 4角点多边形 `[[x1,y1],[x2,y2],[x3,y3],[x4,y4]]`，坐标为200DPI渲染图像的像素坐标
- **page_images**: 在 `run_ocr` 中已生成（第213行），为PIL Image列表
- **flatten_bbox**: `models/data_models.py` 中，将4角点转为 `[x1,y1,x2,y2]`
- **测试数据**: `软件1/json/金融与生活97871133261660000（1-1）/` 下有chars.json（210,926个字符，275页）和对应PDF

## 算法设计

### 核心思路

对每个字符框的四条边独立优化，在允许范围内寻找经过非白像素最少的位置：

1. **左/右边优化**: 在水平方向扫描，对每个候选x位置，统计该列在[y1,y2]范围内的非白像素数
2. **上/下边优化**: 在垂直方向扫描，对每个候选y位置，统计该行在[x1,x2]范围内的非白像素数
3. **选择策略**: 选择非白像素数最少的位置；若原始位置已是最优则保持不动；若并列则选最接近原始位置

### 搜索范围

- 左边搜索: `[x1 - 0.5*Width, x1 + 0.5*Width]`
- 右边搜索: `[x2 - 0.5*Width, x2 + 0.5*Width]`
- 上边搜索: `[y1 - 0.5*Height, y1 + 0.5*Height]`
- 下边搜索: `[y2 - 0.5*Height, y2 + 0.5*Height]`

其中 Width = x2-x1, Height = y2-y1

### 白色阈值

像素任一RGB通道 < 200 视为"非白"（有墨迹），使用 `np.any(img_array < 200, axis=2)` 生成mask

### 向量化实现（性能关键）

利用numpy向量化避免Python循环：
```python
# 左边优化示例
col_sums = mask[y1:y2, x_start:x_end].sum(axis=0)  # 一次性计算所有候选列的非白像素数
min_idx = np.argmin(col_sums)  # 找最小值索引
```

每个字符仅需4次numpy操作，210,926个字符预计处理时间<2分钟。

### 边界情况处理

- 候选位置超出图像边界时裁剪
- 优化后 x1 >= x2 或 y1 >= y2 时回退到原始位置
- 原始位置已是最优（count=0或等于最小值）时保持不动

## 修改方案

### 修改文件: `软件1/ocr_engine/rapidocr_engine.py`

#### 1. 添加 `_optimize_char_boxes` 方法

```python
def _optimize_char_boxes(self, page_images, all_chars, json_dir):
    """优化字符边界框，使四边尽量经过纯白区域。
    
    对每个字符框的四条边独立优化，在±0.5倍边长范围内寻找
    非白像素最少的位置，避免截断文字或多截相邻字。
    
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
    
    for page_num, chars_on_page in chars_by_page.items():
        if page_num >= len(page_images):
            continue
        
        img = page_images[page_num]
        img_array = np.array(img)
        img_h, img_w = img_array.shape[:2]
        mask = np.any(img_array < WHITE_THRESHOLD, axis=2)
        
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
            
            # 优化左边
            new_x1 = self._optimize_edge_x(mask, x1, y1_c, y2_c, w, img_w, direction='left')
            # 优化右边
            new_x2 = self._optimize_edge_x(mask, x2, y1_c, y2_c, w, img_w, direction='right')
            # 优化上边
            new_y1 = self._optimize_edge_y(mask, y1, x1_c, x2_c, h, img_h, direction='top')
            # 优化下边
            new_y2 = self._optimize_edge_y(mask, y2, x1_c, x2_c, h, img_h, direction='bottom')
            
            # 验证有效性
            if new_x1 >= new_x2 or new_y1 >= new_y2:
                continue  # 保持原始box
            
            # 转回4角点格式
            char["box"] = [
                [new_x1, new_y1],
                [new_x2, new_y1],
                [new_x2, new_y2],
                [new_x1, new_y2]
            ]
    
    # 保存为 newchar.json
    newchar_path = os.path.join(json_dir, "newchar.json")
    with open(newchar_path, "w", encoding="utf-8") as f:
        json.dump(all_chars, f, ensure_ascii=False)
```

#### 2. 添加 `_optimize_edge_x` 和 `_optimize_edge_y` 辅助方法

```python
def _optimize_edge_x(self, mask, orig_x, y1, y2, edge_len, img_w, direction='left'):
    """优化垂直边（左/右边）的x位置。"""
    import numpy as np
    
    half = edge_len / 2
    if direction == 'left':
        search_start = max(0, int(orig_x - half))
        search_end = min(img_w, int(orig_x + half) + 1)
    else:  # right
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


def _optimize_edge_y(self, mask, orig_y, x1, x2, edge_len, img_h, direction='top'):
    """优化水平边（上/下边）的y位置。"""
    import numpy as np
    
    half = edge_len / 2
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
```

#### 3. 在 `run_ocr` 中调用优化（第305行之后）

在保存chars.json之后，添加调用：
```python
# 优化字符边界框
if output_callback:
    output_callback("正在优化字符边界框...")
try:
    self._optimize_char_boxes(page_images, all_chars, json_dir)
    if output_callback:
        output_callback("字符边界框优化完成，已保存为 newchar.json")
except Exception as e:
    if output_callback:
        output_callback(f"字符边界框优化失败: {e}")
```

## 验证步骤

1. 用测试数据 `软件1/json/金融与生活97871133261660000（1-1）/` 的PDF和chars.json运行优化
2. 检查生成的newchar.json中box坐标是否合理（边经过空白区域）
3. 对比优化前后的box，确认边框移动方向正确
4. 运行软件1完整OCR流程，确认newchar.json正常生成
5. 确认软件1无报错
