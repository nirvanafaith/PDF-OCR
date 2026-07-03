# RapidOCR 扫描结果 JSON 导出实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用 RapidOCR 扫描图片，提取每行文本的坐标框和文字，以及每个单字的字符和坐标框信息，并按照数据库范式组织为带外键关系的 JSON 文件。

**Architecture:** 基于 RapidOCR 的 `return_word_box=True` 和 `return_single_char_box=True` 参数获取行级和字级信息，通过 Python 脚本将结果解析为规范化的 JSON 结构（行表 + 字表，通过 `line_id` 外键关联）。

**Tech Stack:** Python, rapidocr, json

---

## 背景知识总结

### RapidOCR 关键参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `return_word_box` | `bool` | `False` | 是否返回文字的单字/单词坐标。中文返回单字坐标，英文返回单词坐标（`>=2.1.0`）。 |
| `return_single_char_box` | `bool` | `False` | 在 `return_word_box=True` 时，强制英文/数字也返回单字坐标（`>=3.1.0`）。 |

调用方式：
```python
result = engine(img_url, return_word_box=True, return_single_char_box=True)
```

### RapidOCROutput 数据结构

- `result.boxes`: `np.ndarray`，每行文本的检测框，形状 `(N, 4, 2)`，即 N 行，每行 4 个角点坐标 `[[x1,y1], [x2,y2], [x3,y3], [x4,y4]]`。
- `result.txts`: `Tuple[str]`，每行文本的识别结果。
- `result.scores`: `Tuple[float]`，每行文本的置信度。
- `result.word_results`: `Tuple[Tuple[Tuple[str, float, List[List[int]]], ...], ...]`
  - 外层 tuple：每一行
  - 内层 tuple：该行中的每个字/词
  - 最内层 tuple：`(text, confidence_score, bounding_box)`，其中 `bounding_box` 为 `[[x0,y0], [x1,y1], [x2,y2], [x3,y3]]`

### 数据库范式 JSON 设计

为了避免数据冗余，采用类似关系型数据库的范式结构：

- **lines 表**：存储每行文本的信息，每行有唯一 `line_id`。
- **chars 表**：存储每个单字的信息，通过 `line_id` 外键关联到 `lines` 表。

---

## 任务分解

### Task 1: 编写 `new.py` 核心逻辑

**Files:**
- Modify: `c:\Users\E-VR\Documents\trae_projects\横校\new.py`

**步骤：**

- [ ] **Step 1.1: 导入依赖并初始化引擎**

```python
import json
from pathlib import Path
from rapidocr import RapidOCR

engine = RapidOCR()
```

- [ ] **Step 1.2: 定义图片路径并执行 OCR**

```python
img_url = r"C:\Users\E-VR\Documents\trae_projects\横校\图片PDF文字识别与人工校正系统详细设计文档_第一页.jpg"
result = engine(img_url, return_word_box=True, return_single_char_box=True)
```

- [ ] **Step 1.3: 定义 JSON 数据结构转换函数**

将 `result` 中的行级信息和字级信息转换为带外键关系的规范化 JSON。

```python
def convert_to_json(result):
    lines = []
    chars = []
    line_id_counter = 0
    char_id_counter = 0

    # result.boxes: np.ndarray of shape (N, 4, 2)
    # result.txts: Tuple[str] of length N
    # result.scores: Tuple[float] of length N
    # result.word_results: Tuple[Tuple[Tuple[str, float, List[List[int]]], ...], ...]

    num_lines = len(result.txts) if result.txts else 0

    for i in range(num_lines):
        line_id = line_id_counter
        line_id_counter += 1

        line_box = result.boxes[i].tolist() if result.boxes is not None else None
        line_text = result.txts[i] if result.txts else ""
        line_score = float(result.scores[i]) if result.scores else 0.0

        line_record = {
            "line_id": line_id,
            "text": line_text,
            "score": line_score,
            "box": line_box,
        }
        lines.append(line_record)

        # 处理字级信息
        if result.word_results and i < len(result.word_results):
            word_line = result.word_results[i]
            for word_txt, word_score, word_box in word_line:
                char_record = {
                    "char_id": char_id_counter,
                    "line_id": line_id,  # 外键
                    "char": word_txt,
                    "score": float(word_score),
                    "box": word_box,
                }
                chars.append(char_record)
                char_id_counter += 1

    return {
        "lines": lines,
        "chars": chars,
    }
```

- [ ] **Step 1.4: 执行转换并保存 JSON**

```python
json_data = convert_to_json(result)

output_path = Path(img_url).with_suffix(".json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(json_data, f, ensure_ascii=False, indent=2)

print(f"JSON saved to: {output_path}")
```

- [ ] **Step 1.5: 保留可视化输出（可选）**

```python
result.vis("vis_return_words.jpg")
```

---

## 完整代码（`new.py`）

```python
import json
from pathlib import Path
from rapidocr import RapidOCR


def convert_ocr_result_to_json(result):
    """将 RapidOCR 结果转换为带外键关系的规范化 JSON 结构。

    采用数据库范式思想，分为 lines 和 chars 两张表，
    chars 表通过 line_id 外键关联到 lines 表。
    """
    lines = []
    chars = []
    line_id_counter = 0
    char_id_counter = 0

    num_lines = len(result.txts) if result.txts else 0

    for i in range(num_lines):
        line_id = line_id_counter
        line_id_counter += 1

        line_box = result.boxes[i].tolist() if result.boxes is not None else None
        line_text = result.txts[i] if result.txts else ""
        line_score = float(result.scores[i]) if result.scores else 0.0

        line_record = {
            "line_id": line_id,
            "text": line_text,
            "score": line_score,
            "box": line_box,
        }
        lines.append(line_record)

        if result.word_results and i < len(result.word_results):
            word_line = result.word_results[i]
            for word_txt, word_score, word_box in word_line:
                char_record = {
                    "char_id": char_id_counter,
                    "line_id": line_id,
                    "char": word_txt,
                    "score": float(word_score),
                    "box": word_box,
                }
                chars.append(char_record)
                char_id_counter += 1

    return {
        "lines": lines,
        "chars": chars,
    }


def main():
    engine = RapidOCR()

    img_url = r"C:\Users\E-VR\Documents\trae_projects\横校\图片PDF文字识别与人工校正系统详细设计文档_第一页.jpg"
    result = engine(img_url, return_word_box=True, return_single_char_box=True)

    json_data = convert_ocr_result_to_json(result)

    output_path = Path(img_url).with_suffix(".json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    print(f"JSON saved to: {output_path}")
    result.vis("vis_return_words.jpg")


if __name__ == "__main__":
    main()
```

---

## 计划检查清单

1. **Spec coverage:**
   - [x] 使用 RapidOCR 扫描图片
   - [x] 返回每行的大坐标框及文字
   - [x] 返回每个单字的字符及坐标框
   - [x] 按数据库范式组织为 JSON
   - [x] 行和单字之间通过外键（`line_id`）关联

2. **Placeholder scan:**
   - [x] 无 "TBD", "TODO", "implement later"
   - [x] 所有代码完整可运行

3. **Type consistency:**
   - [x] `result.boxes` 为 `np.ndarray`，使用 `.tolist()` 转为 JSON 可序列化格式
   - [x] `result.word_results` 结构已确认与文档一致
   - [x] `line_id` 和 `char_id` 为自增整数，确保唯一性
