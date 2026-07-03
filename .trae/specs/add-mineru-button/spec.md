# 软件1 MinerU模型识别 + JSON输出路径 Spec

## Why
软件1需要在画框阶段集成MinerU模型识别功能，让用户一键调用MinerU解析PDF并自动导入结果；同时OCR输出的JSON文件需要统一存放在软件1目录下的json文件夹中，便于软件2读取。

## What Changes
- 在DrawBoxWindow工具栏新增"模型识别"按钮
- 点击按钮后弹出CMD窗口运行MinerU命令解析当前PDF
- MinerU解析完成后自动找到最大的JSON文件并导入显示框
- OCR准备阶段的JSON输出路径从PDF同目录改为软件1目录下的json/文件夹

## Impact
- Affected code: 软件1/ui/draw_box_window.py, 软件1/ui/ocr_prepare_window.py
- 新增依赖: subprocess, threading (Python标准库)

## ADDED Requirements

### Requirement: MinerU模型识别按钮
系统SHALL在画框阶段工具栏提供"模型识别"按钮，点击后运行MinerU解析当前PDF。

#### Scenario: 点击模型识别
- **WHEN** 用户已加载PDF并点击"模型识别"按钮
- **THEN** 系统弹出CMD窗口运行 `mineru -p <pdf> -o <output_dir> -b hybrid-auto-engine --method ocr --lang ch --format json`
- **AND** 按钮在运行期间禁用

#### Scenario: MinerU解析完成
- **WHEN** MinerU命令执行完毕
- **THEN** 系统在output目录中递归查找最大的JSON文件
- **AND** 使用现有JSON导入规则将框显示在PDF上

#### Scenario: 未加载PDF时点击
- **WHEN** 用户未加载PDF就点击"模型识别"
- **THEN** 系统显示提示"请先选择PDF文件"

### Requirement: JSON输出到json文件夹
系统SHALL将OCR识别产生的chars.json和lines.json保存到软件1目录下的json/文件夹中。

#### Scenario: 使用本地模型识别
- **WHEN** 用户在OCR准备阶段点击"使用本地模型识别"
- **THEN** chars.json和lines.json保存在 `软件1/json/<pdf_name>/` 目录下
