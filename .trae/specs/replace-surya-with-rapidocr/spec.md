# 替换 Surya 为 RapidOCR Spec

## Why
现有系统使用 Surya OCR 作为识别引擎，但 Surya 需要外部命令行工具支持，部署复杂且识别效果不稳定。RapidOCR 是更成熟的 ONNX/Paddle 推理引擎，支持直接 Python API 调用，且已验证支持行级和字级坐标输出。本次变更将彻底移除 Surya 依赖，全面替换为 RapidOCR，同时保持 JSON 输出格式和 UI 交互逻辑不变。

## What Changes
- **BREAKING**: 移除 `ocr_engine/surya_engine.py`，新建 `ocr_engine/rapidocr_engine.py`
- **BREAKING**: OCR 结果数据结构从 Surya 的 `results.json` 格式改为 RapidOCR 的 `lines.json` + `chars.json` 双文件格式
- 修改 `ocr_engine/__init__.py` 导入新的 `OCREngine`
- 修改 `models/data_models.py` 适配 RapidOCR 输出字段
- 修改 `ui/ocr_prepare_window.py` 的 OCR 调用逻辑和 JSON 加载逻辑
- 修改 `main.py` 中的数据流传递逻辑
- 修改 `ui/horizontal_check_window.py` 和 `ui/vertical_check_window.py` 的数据解析逻辑
- 移除所有与 `surya_ocr` 命令行相关的代码和提示文本

## Impact
- Affected specs: implement-ocr-correction-system
- Affected code:
  - `ocr_engine/surya_engine.py` → 删除
  - `ocr_engine/rapidocr_engine.py` → 新建
  - `ocr_engine/__init__.py`
  - `models/data_models.py`
  - `ui/ocr_prepare_window.py`
  - `ui/horizontal_check_window.py`
  - `ui/vertical_check_window.py`
  - `main.py`

## ADDED Requirements

### Requirement: RapidOCR 引擎封装
系统 SHALL 提供基于 RapidOCR 的 OCR 引擎类，支持对 PDF 每一页图像进行文字识别，并输出行级和字级坐标。

#### Scenario: 成功识别一页图像
- **WHEN** 系统传入一页 PIL Image
- **THEN** 引擎使用 RapidOCR (Paddle 后端) 进行识别，返回该页的 lines 列表和 chars 列表

#### Scenario: 批量处理 PDF 所有页
- **WHEN** 系统传入 PDF 页面图像列表
- **THEN** 引擎逐页识别，汇总为统一的 lines 和 chars 列表，并保存为两个 JSON 文件

### Requirement: 双 JSON 输出格式
系统 SHALL 将 OCR 结果保存为两个 JSON 文件：`<basename>.lines.json` 和 `<basename>.chars.json`。

#### Scenario: lines.json 结构
- **WHEN** OCR 完成
- **THEN** lines.json 为列表，每项包含 `line_id`, `text`, `score`, `box`

#### Scenario: chars.json 结构
- **WHEN** OCR 完成
- **THEN** chars.json 为列表，每项包含 `char_id`, `line_id`, `char`, `score`, `box`，其中 `line_id` 为外键

### Requirement: 字符切片分组
系统 SHALL 从 RapidOCR 结果中构建字符切片分组，供横校界面使用。

#### Scenario: 按字符文本分组
- **WHEN** 系统调用 `parse_and_group`
- **THEN** 返回字典，键为字符文本，值为 `CharSlice` 列表，每个切片包含页码、坐标框、裁剪图像

### Requirement: 行数据构建
系统 SHALL 从 RapidOCR 结果和横校修正结果中构建行数据，供纵校界面使用。

#### Scenario: 构建纵校行数据
- **WHEN** 横校完成，进入纵校
- **THEN** 系统构建每页的行列表，每行包含文本、坐标框、字符列表、裁剪图像

## MODIFIED Requirements

### Requirement: OCR 准备界面
原要求调用 `surya_ocr` 命令行，现改为调用 RapidOCR 引擎的 Python API。

#### Scenario: 执行 OCR 识别
- **WHEN** 用户点击"使用本地模型识别"
- **THEN** 系统在后台线程调用 RapidOCR 逐页识别，输出进度到 CMD 输出区域，完成后自动填入 JSON 路径

#### Scenario: 加载已有 JSON
- **WHEN** 用户选择已有的 lines.json 和 chars.json
- **THEN** 系统加载这两个文件并解析为内部数据结构

## REMOVED Requirements

### Requirement: Surya OCR 命令行调用
**Reason**: 全面替换为 RapidOCR Python API
**Migration**: 用户无需再安装 surya-ocr 命令行工具，只需安装 rapidocr 和 paddlepaddle
