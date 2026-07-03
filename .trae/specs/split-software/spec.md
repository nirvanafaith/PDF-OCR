# 软件拆分 Spec

## Why
当前软件包含5个阶段（画框→OCR准备→纵校→横校→精修），用户需要将其拆分为两个独立运行的软件：软件1负责画框和OCR识别，软件2负责校对和精修。这样可以让不同的工作环节独立使用，提高灵活性。

## What Changes
- **BREAKING**: 将单体应用拆分为两个独立应用
- 软件1（画框+OCR）：包含画框和OCR准备两个阶段，输出PDF+chars.json+lines.json
- 软件2（校对+精修）：包含导入、纵校、横校、精修四个阶段，输入PDF+chars.json+lines.json
- 新增 ImportWindow 用于软件2的数据导入
- 两个软件各自拥有独立的目录结构、main.py和requirements.txt

## Impact
- Affected code: main.py, ui/__init__.py, 所有UI模块
- 新增文件: 软件2/ui/import_window.py, 软件1/main.py, 软件2/main.py
- 共享模块: models/, ocr_engine/, pdf_processor/, ui/styles.py, ui/zoom_utils.py 需复制到两个目录

## ADDED Requirements

### Requirement: 软件1独立运行
系统SHALL提供独立的画框+OCR软件，包含画框和OCR准备两个阶段。

#### Scenario: 画框完成后进入OCR
- **WHEN** 用户在画框阶段完成操作并点击完成
- **THEN** 系统切换到OCR准备阶段，用户可运行OCR识别

#### Scenario: OCR完成后输出JSON
- **WHEN** OCR识别完成
- **THEN** 系统将结果保存为chars.json和lines.json，用户可获取这些文件

### Requirement: 软件2独立运行
系统SHALL提供独立的校对+精修软件，通过导入PDF和JSON文件开始工作流程。

#### Scenario: 导入数据后进入纵校
- **WHEN** 用户选择PDF文件和对应的chars.json、lines.json文件并确认
- **THEN** 系统加载数据并进入纵校阶段

#### Scenario: 完成全部校对流程
- **WHEN** 用户依次完成纵校、横校、精修
- **THEN** 系统输出最终的双层PDF文件

### Requirement: ImportWindow数据导入
系统SHALL提供ImportWindow界面，允许用户选择PDF和JSON文件进行数据导入。

#### Scenario: 选择文件并加载
- **WHEN** 用户点击选择PDF文件和JSON文件按钮并选择有效文件
- **THEN** 系统加载PDF页面图像和OCR结果数据，解析并分组字符切片

#### Scenario: 文件不存在
- **WHEN** 用户选择的JSON文件不存在或格式错误
- **THEN** 系统显示错误提示信息
