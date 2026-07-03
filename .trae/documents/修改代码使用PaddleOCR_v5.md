# 修改 RapidOCR 代码以使用本地 PaddleOCR v5

## 任务概述
将 `new.py` 修改为使用本地 PaddleOCR v5 模型进行文本识别，并简化输出逻辑，直接保存原始模型输出。

## 当前代码分析

### 现有实现
- 使用 RapidOCR 配置 Paddle 引擎和 CUDA 加速
- 执行 OCR 识别并获取单字边界框
- 将结果转换为结构化的行级和字级数据（`convert_ocr_result_to_json` 函数）
- 分别保存为 `.lines.json` 和 `.chars.json` 文件
- 生成可视化结果

### 需要修改的部分
1. 引擎配置：从 Paddle 引擎切换到支持 PP-OCRv5 的配置
2. 输出逻辑：移除数据转换函数，直接保存原始结果
3. 导入语句：添加必要的枚举类型

## PP-OCRv5 配置要点

根据 RapidOCR 官方文档，使用 PP-OCRv5 需要以下配置：

### 必需导入
```python
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR
```

### 引擎参数配置
- **Det（文本检测）模块**：
  - `Det.engine_type`: EngineType.ONNXRUNTIME 或其他支持的引擎
  - `Det.lang_type`: LangDet.CH（中文）
  - `Det.model_type`: ModelType.MOBILE
  - `Det.ocr_version`: OCRVersion.PPOCRV5

- **Rec（文本识别）模块**：
  - `Rec.engine_type`: EngineType.ONNXRUNTIME 或其他支持的引擎
  - `Rec.lang_type`: LangRec.CH（中文）
  - `Rec.model_type`: ModelType.MOBILE
  - `Rec.ocr_version`: OCRVersion.PPOCRV5

## 实施步骤

### 步骤 1：更新导入语句
**位置**：文件顶部（第 1-3 行）

**当前代码**：
```python
import json
from pathlib import Path
from rapidocr import EngineType, RapidOCR
```

**修改为**：
```python
import json
from pathlib import Path
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR
```

**说明**：添加 PP-OCRv5 所需的枚举类型导入。

### 步骤 2：删除数据转换函数
**位置**：第 6-77 行

**操作**：完全删除 `convert_ocr_result_to_json` 函数

**说明**：用户要求直接输出原始模型结果，不再需要将结果拆分为行级和字级数据。

### 步骤 3：重构 main 函数
**位置**：第 80-131 行

**修改内容**：

#### 3.1 更新引擎初始化
**当前代码**（第 104-111 行）：
```python
engine = RapidOCR(
    params={
        "Det.engine_type": EngineType.PADDLE,
        "Cls.engine_type": EngineType.PADDLE,
        "Rec.engine_type": EngineType.PADDLE,
        "EngineConfig.paddle.use_cuda": True,
    }
)
```

**修改为**：
```python
engine = RapidOCR(
    params={
        "Det.engine_type": EngineType.ONNXRUNTIME,
        "Det.lang_type": LangDet.CH,
        "Det.model_type": ModelType.MOBILE,
        "Det.ocr_version": OCRVersion.PPOCRV5,
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Rec.lang_type": LangRec.CH,
        "Rec.model_type": ModelType.MOBILE,
        "Rec.ocr_version": OCRVersion.PPOCRV5,
    }
)
```

**说明**：
- 使用 ONNXRuntime 引擎（PP-OCRv5 的推荐引擎）
- 配置中文语言类型
- 使用移动端模型（更轻量）
- 指定 PP-OCRv5 版本

#### 3.2 简化 OCR 调用
**当前代码**（第 114 行）：
```python
result = engine(img_url, return_word_box=True, return_single_char_box=True)
```

**修改为**：
```python
result = engine(img_url)
```

**说明**：移除单字边界框参数，简化为基本 OCR 识别。

#### 3.3 简化结果处理
**当前代码**（第 116-126 行）：
```python
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
```

**修改为**：
```python
img_path = Path(img_url)
output_path = img_path.with_suffix(".json")

result_dict = {
    "txts": result.txts,
    "boxes": [box.tolist() if box is not None else None for box in result.boxes] if result.boxes else None,
    "scores": [float(score) for score in result.scores] if result.scores else None,
}

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(result_dict, f, ensure_ascii=False, indent=2)

print(f"OCR result saved to: {output_path}")
```

**说明**：
- 移除对 `convert_ocr_result_to_json` 的调用
- 直接从 result 对象提取原始数据（txts、boxes、scores）
- 将边界框和分数转换为可序列化格式
- 保存为单个 `.json` 文件

#### 3.4 更新可视化输出
**当前代码**（第 130 行）：
```python
result.vis("vis_return_words.jpg")
```

**修改为**：
```python
result.vis("vis_result.jpg")
```

**说明**：更新可视化文件名以反映新的实现。

### 步骤 4：更新 main 函数文档字符串
**位置**：第 81-103 行

**修改为**：
```python
"""脚本入口函数，执行单张图片的 OCR 识别并保存结果。

使用 PP-OCRv5 模型初始化 RapidOCR，对指定图片执行 OCR 识别，
将识别结果直接保存为 JSON 文件，并生成可视化结果图片。

参数:
    无。

返回:
    None

调用关系:
    脚本入口函数，由 __main__ 块调用。

依赖:
    - json: JSON 序列化，用于将识别结果写入文件。
    - pathlib.Path: 文件路径处理，用于生成输出文件路径。
    - rapidocr.EngineType: OCR 引擎类型枚举，指定使用 ONNXRuntime 引擎。
    - rapidocr.LangDet: 检测模块语言类型枚举。
    - rapidocr.LangRec: 识别模块语言类型枚举。
    - rapidocr.ModelType: 模型类型枚举，指定移动端模型。
    - rapidocr.OCRVersion: OCR 版本枚举，指定 PP-OCRv5。
    - rapidocr.RapidOCR: OCR 识别引擎，执行文字检测和文字识别。
"""
```

## 最终代码结构

修改后的代码将具有以下结构：

```
new.py
├── 导入语句（更新后）
├── main() 函数
│   ├── 引擎初始化（PP-OCRv5 配置）
│   ├── OCR 识别执行
│   ├── 结果保存（直接输出原始数据）
│   └── 可视化生成
└── __main__ 块
```

## 关键变更总结

1. **引擎变更**：从 Paddle 引擎切换到 ONNXRuntime 引擎
2. **模型版本**：从默认版本升级到 PP-OCRv5
3. **输出简化**：移除数据转换逻辑，直接保存原始结果
4. **代码精简**：删除 70+ 行的转换函数代码

## 注意事项

1. 用户环境中已安装 paddleocr，代码无需测试
2. 使用 ONNXRuntime 引擎需要确保环境中已安装 onnxruntime
3. PP-OCRv5 模型文件会在首次运行时自动下载
4. 输出的 JSON 格式为 RapidOCR 的原始结果格式
