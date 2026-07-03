# 将 OCR 结果拆分为 Line 和 Char 两个 JSON 文件

## 任务概述
将当前的单文件 JSON 输出拆分为两个独立的 JSON 文件，分别存储行级数据和字级数据，两者通过外键 `line_id` 关联，符合数据库规范化设计。

## 当前数据结构分析

当前输出为单个 JSON 文件，包含四个平铺字段：
```json
{
  "txts": ["第一行文本", "第二行文本"],
  "boxes": [[[x1,y1], ...], ...],
  "scores": [0.99, 0.98],
  "word_results": [
    [{"char": "第", "score": 0.99, "box": [...]}, ...],
    [{"char": "第", "score": 0.98, "box": [...]}, ...]
  ]
}
```

问题：行级数据和字级数据混合在一起，不符合数据库规范化设计，无法独立管理和查询。

## 目标数据结构设计

### lines.json — 行级数据表
```json
[
  {
    "line_id": 0,
    "text": "图片PDF文字识别与人工校正系统详细设计",
    "score": 0.99702,
    "box": [[103.0, 133.0], [904.0, 133.0], [904.0, 181.0], [103.0, 181.0]]
  },
  {
    "line_id": 1,
    "text": "文档",
    "score": 0.99745,
    "box": [[456.0, 187.0], [552.0, 187.0], [552.0, 243.0], [456.0, 243.0]]
  }
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| line_id | int | 主键，行唯一标识，从 0 递增 |
| text | str | 行文本内容 |
| score | float | 行置信度分数 |
| box | list | 行边界框坐标，4 个角点 |

### chars.json — 字级数据表
```json
[
  {
    "char_id": 0,
    "line_id": 0,
    "char": "图",
    "score": 0.99996,
    "box": [[104, 133], [141, 133], [141, 181], [104, 181]]
  },
  {
    "char_id": 1,
    "line_id": 0,
    "char": "片",
    "score": 0.97296,
    "box": [[144, 133], [181, 133], [181, 181], [144, 181]]
  },
  {
    "char_id": 20,
    "line_id": 1,
    "char": "文",
    "score": 0.99943,
    "box": [[456, 187], [502, 187], [502, 243], [456, 243]]
  }
]
```

| 字段 | 类型 | 说明 |
|------|------|------|
| char_id | int | 主键，字唯一标识，从 0 全局递增 |
| line_id | int | 外键，关联 lines 表的 line_id |
| char | str | 单字文本内容 |
| score | float | 单字置信度分数 |
| box | list | 单字边界框坐标，4 个角点 |

### 关系图
```
lines.json (1) ────< chars.json (N)
  line_id ──────────── line_id (FK)
```

## 实施步骤

### 步骤 1：修改结果处理逻辑

**位置**：`new.py` 第 46-71 行

**当前代码**：
```python
img_path = Path(img_url)
output_path = img_path.with_suffix(".json")

word_results = None
if result.word_results is not None:
    word_results = []
    for line_words in result.word_results:
        if line_words is not None:
            line_word_data = []
            for word_txt, word_score, word_box in line_words:
                line_word_data.append({
                    "char": word_txt,
                    "score": float(word_score),
                    "box": word_box.tolist() if hasattr(word_box, 'tolist') else word_box,
                })
            word_results.append(line_word_data)
        else:
            word_results.append(None)

result_dict = {
    "txts": result.txts,
    "boxes": [box.tolist() for box in result.boxes] if result.boxes is not None else None,
    "scores": [float(score) for score in result.scores] if result.scores is not None else None,
    "word_results": word_results,
}

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(result_dict, f, ensure_ascii=False, indent=2)

print(f"OCR result saved to: {output_path}")
```

**修改为**：
```python
img_path = Path(img_url)
lines_output_path = img_path.with_suffix(".lines.json")
chars_output_path = img_path.with_suffix(".chars.json")

lines = []
chars = []
char_id_counter = 0

num_lines = len(result.txts) if result.txts else 0

for i in range(num_lines):
    line_box = result.boxes[i].tolist() if result.boxes is not None else None
    line_text = result.txts[i] if result.txts else ""
    line_score = float(result.scores[i]) if result.scores is not None else 0.0

    lines.append({
        "line_id": i,
        "text": line_text,
        "score": line_score,
        "box": line_box,
    })

    if result.word_results is not None and i < len(result.word_results):
        line_words = result.word_results[i]
        if line_words is not None:
            for word_txt, word_score, word_box in line_words:
                chars.append({
                    "char_id": char_id_counter,
                    "line_id": i,
                    "char": word_txt,
                    "score": float(word_score),
                    "box": word_box.tolist() if hasattr(word_box, 'tolist') else word_box,
                })
                char_id_counter += 1

with open(lines_output_path, "w", encoding="utf-8") as f:
    json.dump(lines, f, ensure_ascii=False, indent=2)

with open(chars_output_path, "w", encoding="utf-8") as f:
    json.dump(chars, f, ensure_ascii=False, indent=2)

print(f"Lines JSON saved to: {lines_output_path}")
print(f"Chars JSON saved to: {chars_output_path}")
```

### 步骤 2：更新 main 函数文档字符串

**位置**：`new.py` 第 6-29 行

将文档字符串中的描述更新为拆分输出逻辑。

## 关键变更总结

1. **输出文件**：从单个 `.json` 拆分为 `.lines.json` + `.chars.json`
2. **数据结构**：从平铺结构变为数据库规范化结构
3. **主键设计**：lines 使用 `line_id`（行索引），chars 使用 `char_id`（全局递增）
4. **外键关联**：chars 通过 `line_id` 外键关联到对应的 line 记录
