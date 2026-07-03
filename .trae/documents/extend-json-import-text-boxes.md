# 扩展JSON导入：支持title/list/image/table中的文本框

## 问题分析

当前 `_on_import_json` 方法仅导入 `para_block.type == "text"` 的顶层块，遗漏了大量嵌套在其他类型块中的文本框。

### 数据统计（遗漏量）

| JSON文件 | 当前导入 | 应导入 | 遗漏 | 遗漏率 |
|---|---|---|---|---|
| 城市轨道交通信号 | 3692 | 5664 | 1972 | 34.8% |
| 高速铁路概论 | 2006 | 3919 | 1913 | 48.8% |

### 遗漏的框类型

| 来源 | 城市轨道交通信号 | 高速铁路概论 | 说明 |
|---|---|---|---|
| title（标题） | 1073 | 824 | para_block.type="title"，直接用其bbox |
| list→text（目录文本） | 626 | 724 | list的blocks子块中type="text" |
| image→image_caption | 214 | 265 | image的blocks子块中type="image_caption" |
| image→image_footnote | 43 | 21 | image的blocks子块中type="image_footnote" |
| table→table_caption | 16 | 65 | table的blocks子块中type="table_caption" |
| table→table_footnote | 0 | 14 | table的blocks子块中type="table_footnote" |

### JSON结构示意

```
para_block.type="title" → 直接有bbox，内部lines→spans有text内容
para_block.type="list" → blocks数组 → 子块有独立bbox和type="text"
para_block.type="image" → blocks数组 → 子块有image_caption/image_footnote
para_block.type="table" → blocks数组 → 子块有table_caption/table_footnote
```

## 修改方案

### 修改文件：`ui/draw_box_window.py`

#### 1. 添加类属性

在 `EXPAND_BBOX_PIXELS = 2.0` 下方添加：

```python
TEXT_BLOCK_TYPES = {"text", "title"}
TEXT_SUB_BLOCK_TYPES = {"image_caption", "image_footnote", "table_caption", "table_footnote", "text", "ref_text"}
```

#### 2. 修改 `_on_import_json` 方法

将核心遍历逻辑从：

```python
for block in para_blocks:
    if block.get('type') != 'text':
        continue
    bbox = block.get('bbox', [])
    ...
```

改为：

```python
for block in para_blocks:
    block_type = block.get('type', '')
    if block_type in self.TEXT_BLOCK_TYPES:
        bbox = block.get('bbox', [])
        if len(bbox) == 4:
            # 添加框（坐标转换+扩展逻辑不变）
            ...
    elif block_type in ('list', 'image', 'table'):
        for sub_block in block.get('blocks', []):
            if sub_block.get('type', '') not in self.TEXT_SUB_BLOCK_TYPES:
                continue
            bbox = sub_block.get('bbox', [])
            if len(bbox) == 4:
                # 添加框（坐标转换+扩展逻辑不变）
                ...
```

### 不修改的部分

- `pdf_processor/pdf_loader.py`：无需修改
- 坐标转换逻辑（scale_x/scale_y计算）：不变
- 框扩展逻辑（EXPAND_BBOX_PIXELS）：不变
- 数据合并逻辑（追加到self.boxes）：不变

## 验证计划

1. 使用城市轨道交通信号JSON测试：确认导入框数从3692增加到5664
2. 使用高速铁路概论JSON测试：确认导入框数从2006增加到3919
3. 目视验证：检查title、list、image_caption等框是否正确显示在对应文字上方
4. 回归验证：手动绘制框与导入框仍然可以共存
