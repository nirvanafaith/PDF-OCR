# 修复 NumPy 2.x 与 onnxruntime 不兼容导致启动崩溃 Spec

## Why
当前环境存在两个兼容性问题导致应用启动崩溃：
1. NumPy 2.3.5 与 onnxruntime 1.17.0 的 ABI 不兼容（NumPy 2.x 彻底重构了 C API，onnxruntime 1.17.0 基于 NumPy 1.x 编译）
2. onnxruntime 1.17.0 仅支持 ONNX IR version 9，但 RapidOCR 的 PPOCRv5 模型使用 IR version 10，导致模型加载失败

这两个问题共同导致 `onnxruntime` 无法正常工作，进而使 RapidOCR 引擎初始化失败，应用程序在启动时直接崩溃（`MainWindow.__init__` → `OCREngine()` → `RapidOCR()` → onnxruntime 导入/模型加载失败）。

## What Changes
- **BREAKING**: 将 NumPy 版本约束为 `<2`（推荐 1.26.4），确保与 onnxruntime、paddlepaddle-gpu、rapidocr 等所有依赖包的 ABI 兼容
- **BREAKING**: 将 onnxruntime 升级到 ≥1.19.0，以支持 ONNX IR version 10（PPOCRv5 模型所需）
- 修改 `requirements.txt`，显式添加 `numpy<2` 版本约束和 `onnxruntime>=1.19.0` 版本约束
- 降级当前环境中的 NumPy 到兼容版本
- 升级当前环境中的 onnxruntime 到兼容版本

## Impact
- Affected specs: replace-surya-with-rapidocr（OCREngine 初始化依赖链）
- Affected code:
  - `requirements.txt`：添加 numpy 和 onnxruntime 版本约束
  - 运行环境：需要执行 pip 命令降级 NumPy 并升级 onnxruntime

## ADDED Requirements

### Requirement: NumPy 版本兼容性约束
系统 SHALL 在 `requirements.txt` 中显式约束 NumPy 版本为 `<2`，以防止 pip 自动安装与 onnxruntime 不兼容的 NumPy 2.x 版本。

#### Scenario: 安装依赖时自动选择兼容版本
- **WHEN** 用户执行 `pip install -r requirements.txt`
- **THEN** pip 安装 NumPy 1.x 系列（推荐 1.26.4），而非 NumPy 2.x

### Requirement: onnxruntime 版本兼容性约束
系统 SHALL 在 `requirements.txt` 中显式约束 onnxruntime 版本为 `>=1.19.0`，以确保支持 ONNX IR version 10（PPOCRv5 模型所需）。

#### Scenario: PPOCRv5 模型加载成功
- **WHEN** OCREngine 初始化 RapidOCR 并加载 PPOCRv5 模型
- **THEN** onnxruntime 成功加载模型，不出现 "Unsupported model IR version" 错误

### Requirement: onnxruntime 正常导入
系统 SHALL 确保 onnxruntime 能够在当前 Python 环境中正常导入和初始化，不出现 ABI 不兼容错误。

#### Scenario: 应用启动时 OCR 引擎初始化成功
- **WHEN** 用户运行 `python main.py`
- **THEN** `OCREngine.__init__` 成功创建 RapidOCR 实例，onnxruntime 正常加载，PPOCRv5 模型加载成功，应用窗口正常显示

### Requirement: 运行环境修复
系统 SHALL 提供明确的环境修复步骤，将当前已安装的 NumPy 2.3.5 降级为兼容版本，并将 onnxruntime 1.17.0 升级为支持 IR version 10 的版本。

#### Scenario: 修复环境后应用正常运行
- **WHEN** 用户执行环境修复步骤后运行应用
- **THEN** 所有依赖包（onnxruntime、paddlepaddle-gpu、rapidocr、opencv 等）正常工作，应用无崩溃

## MODIFIED Requirements

### Requirement: 依赖版本声明
原 `requirements.txt` 未约束 NumPy 和 onnxruntime 版本，现需显式添加 `numpy<2` 和 `onnxruntime>=1.19.0` 约束，确保与 RapidOCR PPOCRv5 模型的兼容性。

## REMOVED Requirements

无移除的需求。
