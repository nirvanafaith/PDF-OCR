# 软件1按钮改名+PDF复制+软件2去模型 Spec

## Why
软件1的OCR环节"下一步"按钮语义不明确，应改为"新书制作"；OCR输出的JSON文件夹应包含原书PDF便于软件2使用；软件2不执行OCR识别，不需要RapidOCR模型，应移除以减小体积和依赖。

## What Changes
- 软件1 OCR环节"下一步"按钮改名为"新书制作"
- 软件1 OCR识别完成后将原PDF文件复制到JSON输出文件夹
- 软件2移除RapidOCR模型相关代码和依赖

## Impact
- Affected code: 软件1/ui/ocr_prepare_window.py, 软件1/ocr_engine/rapidocr_engine.py, 软件2/ocr_engine/rapidocr_engine.py, 软件2/requirements.txt, 软件2/main.py

## ADDED Requirements

### Requirement: 按钮改名
系统SHALL将软件1 OCR环节的"下一步"按钮改名为"新书制作"。

### Requirement: PDF复制到JSON文件夹
系统SHALL在OCR识别完成后将原PDF文件复制到JSON输出文件夹中。

#### Scenario: OCR完成后PDF复制
- **WHEN** OCR识别完成并保存lines.json和chars.json
- **THEN** 原PDF文件也被复制到同一目录下

### Requirement: 软件2移除模型依赖
系统SHALL从软件2中移除RapidOCR模型相关代码和依赖，仅保留数据处理方法。

#### Scenario: 软件2独立运行无需模型
- **WHEN** 软件2启动
- **THEN** 不加载任何OCR模型，不依赖rapidocr和onnxruntime
