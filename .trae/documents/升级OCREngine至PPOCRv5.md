# 升级 OCREngine 至 PP-OCRv5 并适配下游代码

## 任务概述
1. 将 `ocr_engine/rapidocr_engine.py` 中的 OCR 引擎从 Paddle 升级为 PP-OCRv5（ONNXRuntime）
2. 确保横校、纵校、精修等下游代码与新的 line/char 数据格式兼容

## 数据格式分析

### 新格式（来自 new.py 输出）
**lines.json**:
```json
[{"line_id": 0, "text": "...", "score": 0.997, "box": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]}]
```

**chars.json**:
```json
[{"char_id": 0, "line_id": 0, "char": "图", "score": 0.999, "box": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]}]
```

### 现有格式（rapidocr_engine.py 输出）
- lines: `{"line_id", "text", "score", "box", "page_num"}`
- chars: `{"char_id", "line_id", "char", "score", "box", "page_num"}`

### 兼容性分析
- 新格式的 `box` 为四点多边形 `[[x1,y1], [x2,y2], [x3,y3], [x4,y4]]`
- `models/data_models.py` 中的 `flatten_bbox()` 已支持将四点多边形转为 `[x1, y1, x2, y2]` 扁平格式
- `parse_and_group()` 和 `build_line_data()` 均调用 `flatten_bbox()` 处理 box
- 所有 UI 组件（横校/纵校/精修）使用的是经过 `flatten_bbox()` 转换后的扁平 bbox
- **结论：下游代码无需修改，只需更新 OCREngine 引擎配置**

## 实施步骤

### 步骤 1：更新 `ocr_engine/rapidocr_engine.py` 的导入语句

**位置**：第 6 行

**当前代码**：
```python
from rapidocr import EngineType, RapidOCR
```

**修改为**：
```python
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR
```

### 步骤 2：更新 `OCREngine.__init__` 的引擎参数

**位置**：第 27-50 行

**当前代码**：
```python
def __init__(self, use_cuda: bool = True):
    params = {
        "Det.engine_type": EngineType.PADDLE,
        "Cls.engine_type": EngineType.PADDLE,
        "Rec.engine_type": EngineType.PADDLE,
        "EngineConfig.paddle.use_cuda": use_cuda,
    }
    self.engine = RapidOCR(params=params)
```

**修改为**：
```python
def __init__(self):
    params = {
        "Det.engine_type": EngineType.ONNXRUNTIME,
        "Det.lang_type": LangDet.CH,
        "Det.model_type": ModelType.MOBILE,
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Rec.lang_type": LangRec.CH,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
    }
    self.engine = RapidOCR(params=params)
```

**说明**：
- 移除 `use_cuda` 参数（ONNXRuntime 引擎不需要）
- 移除 `Cls`（方向分类）模块配置（PP-OCRv5 示例中未使用）
- 使用 ONNXRuntime 引擎替代 Paddle 引擎
- 配置中文语言类型和 PP-OCRv5 版本

### 步骤 3：修复 `_recognize_page` 中的 numpy 数组真值判断问题

**位置**：第 97、105、115 行

**当前代码**：
```python
num_lines = len(result.txts) if result.txts else 0
```
```python
line_score = float(result.scores[i]) if result.scores else 0.0
```
```python
if result.word_results and i < len(result.word_results):
```

**修改为**：
```python
num_lines = len(result.txts) if result.txts is not None else 0
```
```python
line_score = float(result.scores[i]) if result.scores is not None else 0.0
```
```python
if result.word_results is not None and i < len(result.word_results):
```

**说明**：`result.boxes`、`result.scores`、`result.word_results` 可能为 numpy 数组，直接布尔判断会引发 `ValueError`。

### 步骤 4：添加 `word_box` 的序列化转换

**位置**：第 117-124 行

**当前代码**：
```python
for word_txt, word_score, word_box in word_line:
    char_record = {
        "char_id": char_id_counter,
        "line_id": line_id,
        "char": word_txt,
        "score": float(word_score),
        "box": word_box,
    }
```

**修改为**：
```python
for word_txt, word_score, word_box in word_line:
    char_record = {
        "char_id": char_id_counter,
        "line_id": line_id,
        "char": word_txt,
        "score": float(word_score),
        "box": word_box.tolist() if hasattr(word_box, 'tolist') else word_box,
    }
```

**说明**：PP-OCRv5 的 `word_box` 可能为 numpy 数组，需要转为列表才能 JSON 序列化。

### 步骤 5：更新 `__init__` 的文档字符串

**位置**：第 27-43 行

更新文档字符串以反映 PP-OCRv5 引擎配置。

### 步骤 6：更新 `main.py` 中 `OCREngine` 的实例化调用

**位置**：`main.py` 第 222 行

**当前代码**：
```python
self.ocr_engine = OCREngine()
```

无需修改，因为 `__init__` 的 `use_cuda` 参数已有默认值，移除后仍可无参调用。

### 步骤 7：验证下游代码兼容性（无需修改）

以下模块已验证与新格式兼容：

| 模块 | 关键调用 | 兼容原因 |
|------|----------|----------|
| `models/data_models.py` | `flatten_bbox()` | 已支持四点多边形转扁平格式 |
| `ocr_engine.py::parse_and_group` | `flatten_bbox(bbox)` | box 经转换后为 `[x1,y1,x2,y2]` |
| `ocr_engine.py::build_line_data` | `flatten_bbox(line_box/char_bbox)` | 同上 |
| `ui/horizontal_check_window.py` | `CharSlice.bbox` | 已为扁平格式 |
| `ui/vertical_check_window.py` | `LineSlice.bbox` | 已为扁平格式 |
| `ui/refine_window.py` | `RefineTextItem.bbox` | 已为扁平格式 |
| `ui/ocr_prepare_window.py` | 无格式相关代码 | 不受影响 |

## 关键变更总结

1. **引擎升级**：Paddle → ONNXRuntime + PP-OCRv5
2. **numpy 安全**：修复 3 处 numpy 数组布尔判断问题
3. **序列化修复**：添加 `word_box` 的 `.tolist()` 转换
4. **下游兼容**：无需修改，`flatten_bbox` 已处理格式差异
