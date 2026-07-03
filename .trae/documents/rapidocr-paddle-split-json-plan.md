# RapidOCR Paddle 引擎 + 双 JSON 输出修正计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 `new.py`，将行结构和单字结构分别输出到两个 JSON 文件，并将推理引擎切换为 PaddlePaddle。

**Architecture:** 通过 `EngineType.PADDLE` 指定 PaddlePaddle 作为 RapidOCR 的推理引擎；OCR 结果解析后，将 `lines` 和 `chars` 分别写入两个独立的 JSON 文件，保持外键关联。

**Tech Stack:** Python, rapidocr, paddlepaddle, json

---

## 背景知识总结

### 1. 使用 PaddlePaddle 作为推理引擎

根据 RapidOCR 官方文档，使用 PaddlePaddle 引擎需要在初始化 `RapidOCR` 时传入 `params` 参数，指定 `Det`、`Cls`、`Rec` 三个阶段的 `engine_type` 为 `EngineType.PADDLE`。

**导入方式：**
```python
from rapidocr import EngineType, RapidOCR
```

**初始化方式（CPU 版）：**
```python
engine = RapidOCR(
    params={
        "Det.engine_type": EngineType.PADDLE,
        "Cls.engine_type": EngineType.PADDLE,
        "Rec.engine_type": EngineType.PADDLE,
    }
)
```

**GPU 版（可选）：**
```python
engine = RapidOCR(
    params={
        "Det.engine_type": EngineType.PADDLE,
        "EngineConfig.paddle.use_cuda": True,
        "EngineConfig.paddle.cuda_ep_cfg.device_id": 0,
    }
)
```

**验证方式：** 查看运行日志，出现 `Using engine_name: paddle` 即表示成功切换。

### 2. 双 JSON 输出设计

将原来的单个 JSON 文件拆分为两个：

- **`<图片名>_lines.json`**：仅包含行级信息（`line_id`, `text`, `score`, `box`）
- **`<图片名>_chars.json`**：仅包含字级信息（`char_id`, `line_id`, `char`, `score`, `box`）

`chars.json` 中的 `line_id` 作为外键关联到 `lines.json` 中的 `line_id`。

---

## 任务分解

### Task 1: 修改 `new.py` 引擎为 PaddlePaddle

**Files:**
- Modify: `c:\Users\E-VR\Documents\trae_projects\横校\new.py`

- [ ] **Step 1.1: 导入 `EngineType`**

将原来的：
```python
from rapidocr import RapidOCR
```
改为：
```python
from rapidocr import EngineType, RapidOCR
```

- [ ] **Step 1.2: 修改引擎初始化代码**

将原来的：
```python
engine = RapidOCR()
```
改为：
```python
engine = RapidOCR(
    params={
        "Det.engine_type": EngineType.PADDLE,
        "Cls.engine_type": EngineType.PADDLE,
        "Rec.engine_type": EngineType.PADDLE,
    }
)
```

### Task 2: 修改 `new.py` 输出为两个 JSON 文件

**Files:**
- Modify: `c:\Users\E-VR\Documents\trae_projects\横校\new.py`

- [ ] **Step 2.1: 修改 `convert_ocr_result_to_json` 函数，使其返回两个字典**

```python
def convert_ocr_result_to_json(result):
    """将 RapidOCR 结果转换为行级和字级两个字典。

    返回 (lines_data, chars_data)，分别对应行表和字表。
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

    return lines, chars
```

- [ ] **Step 2.2: 修改 `main` 函数，分别保存为两个 JSON 文件**

```python
def main():
    engine = RapidOCR(
        params={
            "Det.engine_type": EngineType.PADDLE,
            "Cls.engine_type": EngineType.PADDLE,
            "Rec.engine_type": EngineType.PADDLE,
        }
    )

    img_url = r"C:\Users\E-VR\Documents\trae_projects\横校\图片PDF文字识别与人工校正系统详细设计文档_第一页.jpg"
    result = engine(img_url, return_word_box=True, return_single_char_box=True)

    lines, chars = convert_ocr_result_to_json(result)

    img_path = Path(img_url)
    lines_output_path = img_path.with_suffix(".lines.json")
    chars_output_path = img_path.with_suffix(".chars.json")

    with open(lines_output_path, "w", encoding="utf-8") as f:
        json.dump(lines, f, ensure_ascii=False, indent=2)

    with open(chars_output_path, "w", encoding="utf-8") as f:
        json.dump(chars, f, ensure_ascii=False, indent=2)

    print(f"Lines JSON saved to: {lines_output_path}")
    print(f"Chars JSON saved to: {chars_output_path}")
    result.vis("vis_return_words.jpg")
```

---

## 完整代码（`new.py`）

```python
import json
from pathlib import Path
from rapidocr import EngineType, RapidOCR


def convert_ocr_result_to_json(result):
    """将 RapidOCR 结果转换为行级和字级两个字典。

    返回 (lines_data, chars_data)，分别对应行表和字表。
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

    return lines, chars


def main():
    engine = RapidOCR(
        params={
            "Det.engine_type": EngineType.PADDLE,
            "Cls.engine_type": EngineType.PADDLE,
            "Rec.engine_type": EngineType.PADDLE,
        }
    )

    img_url = r"C:\Users\E-VR\Documents\trae_projects\横校\图片PDF文字识别与人工校正系统详细设计文档_第一页.jpg"
    result = engine(img_url, return_word_box=True, return_single_char_box=True)

    lines, chars = convert_ocr_result_to_json(result)

    img_path = Path(img_url)
    lines_output_path = img_path.with_suffix(".lines.json")
    chars_output_path = img_path.with_suffix(".chars.json")

    with open(lines_output_path, "w", encoding="utf-8") as f:
        json.dump(lines, f, ensure_ascii=False, indent=2)

    with open(chars_output_path, "w", encoding="utf-8") as f:
        json.dump(chars, f, ensure_ascii=False, indent=2)

    print(f"Lines JSON saved to: {lines_output_path}")
    print(f"Chars JSON saved to: {chars_output_path}")
    result.vis("vis_return_words.jpg")


if __name__ == "__main__":
    main()
```

---

## 计划检查清单

1. **Spec coverage:**
   - [x] 行和单字分别输出到两个 JSON 文件
   - [x] 使用 PaddlePaddle 作为 RapidOCR 推理引擎
   - [x] 保持 `line_id` 外键关联

2. **Placeholder scan:**
   - [x] 无 "TBD", "TODO", "implement later"
   - [x] 所有代码完整可运行

3. **Type consistency:**
   - [x] `EngineType.PADDLE` 导入和使用方式与官方文档一致
   - [x] 文件命名规则一致（`.lines.json` 和 `.chars.json`）
