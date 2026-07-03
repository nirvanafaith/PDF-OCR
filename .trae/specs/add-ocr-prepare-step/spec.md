# OCR准备步骤界面 Spec

## Why
当前流程在选择PDF后立即自动执行OCR，用户无法控制OCR过程，也无法使用已有的JSON结果。需要在PDF选择和横校之间增加一个准备步骤界面，让用户选择OCR方式并观察执行过程。

## What Changes
- 新增OCR准备界面模块 `ui/ocr_prepare_window.py`：提供两种进入横校的路径
- **BREAKING** 修改 `main.py`：选择PDF后进入OCR准备界面，而非直接执行OCR
- 修改 `ocr_engine/surya_engine.py`：`run_ocr` 方法改为实时流式输出CMD过程，支持回调输出

## Impact
- Affected specs: implement-ocr-correction-system
- Affected code: main.py, ocr_engine/surya_engine.py, 新增 ui/ocr_prepare_window.py

## ADDED Requirements

### Requirement: OCR准备界面
系统 SHALL 在用户选择PDF文件后，显示OCR准备界面，提供两种方式获取OCR结果后进入横校。

#### Scenario: 界面布局
- **WHEN** 用户选择PDF文件后
- **THEN** 系统显示OCR准备界面，包含：PDF文件路径显示、JSON文件路径输入框、"使用本地模型识别"按钮、"选择JSON文件"按钮、"下一步"按钮、CMD输出显示区域

#### Scenario: 使用本地模型识别
- **WHEN** 用户点击"使用本地模型识别"按钮
- **THEN** 系统在后台执行 `surya_ocr` CLI命令，CMD过程的实时输出显示在界面的文本区域中；识别完成后自动将生成的results.json路径填入JSON路径输入框；"下一步"按钮变为可用状态

#### Scenario: OCR执行中的状态
- **WHEN** surya_ocr命令正在执行
- **THEN** "使用本地模型识别"按钮变为禁用状态；CMD输出区域实时滚动显示命令输出；用户可以看到执行进度

#### Scenario: OCR执行失败
- **WHEN** surya_ocr命令执行失败
- **THEN** CMD输出区域显示错误信息；"使用本地模型识别"按钮恢复可用状态；用户可以重新尝试

#### Scenario: 手动选择JSON文件
- **WHEN** 用户点击"选择JSON文件"按钮
- **THEN** 系统弹出文件选择对话框，用户选择results.json文件后，路径自动填入JSON路径输入框；"下一步"按钮变为可用状态

#### Scenario: 点击下一步进入横校
- **WHEN** JSON路径已填入且用户点击"下一步"按钮
- **THEN** 系统加载PDF页面图像、解析JSON结果、构建字符切片分组数据，然后进入横校界面

#### Scenario: 未选择JSON时下一步不可用
- **WHEN** JSON路径输入框为空
- **THEN** "下一步"按钮处于禁用状态

### Requirement: surya_ocr实时输出
系统 SHALL 在执行surya_ocr命令时，实时将CMD输出流式传输到界面，而非等待命令完成后一次性显示。

#### Scenario: 实时输出
- **WHEN** surya_ocr命令正在执行
- **THEN** 每一行CMD输出都实时追加到界面的文本显示区域，自动滚动到底部

## MODIFIED Requirements

### Requirement: 主程序流程控制
系统 SHALL 在用户选择PDF后进入OCR准备界面，由用户选择OCR方式后进入横校，而非自动执行OCR。

## REMOVED Requirements

### Requirement: OCR自动执行流程
**Reason**: 改为由用户在OCR准备界面手动触发
**Migration**: OCR逻辑移至OCR准备界面中由用户控制
