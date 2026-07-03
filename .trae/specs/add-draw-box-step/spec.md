# 手动画框步骤 Spec

## Why
当前系统对整页进行OCR识别，产生大量无关文本，用户需要手动筛选。通过在OCR之前新增"画框"步骤，让用户手动标记感兴趣的区域，OCR仅识别框内文本，大幅减少后续校对工作量并提升处理效率。

## What Changes
- 新增 `ui/draw_box_window.py`：画框步骤窗口，作为软件新的首页
- **BREAKING** `MainWindow.STAGES` 从4步变为5步：`["画框", "OCR准备", "横校", "纵校", "精修"]`
- 修改 `OCREngine.run_ocr`：新增 `regions` 参数，仅识别指定区域内的文本
- 修改 `OCRPrepareWindow`：接收来自画框步骤的 `pdf_path` 和 `regions` 数据，传递给OCR引擎
- 修改 `MainWindow`：新增画框阶段的界面管理和数据流转
- 新增 `models/data_models.TextBox` 数据类：存储用户绘制的文本框信息

## Impact
- Affected specs: OCR准备阶段的数据输入流程、OCR引擎的识别范围
- Affected code: `main.py`, `ocr_engine/rapidocr_engine.py`, `ui/ocr_prepare_window.py`, `models/data_models.py`, 新增 `ui/draw_box_window.py`

## ADDED Requirements

### Requirement: 画框步骤窗口
系统 SHALL 提供一个画框步骤窗口（DrawBoxWindow），作为软件的首页。用户在此窗口中加载PDF文件，在每页上绘制矩形框标记需要识别的文本区域。

#### Scenario: 加载PDF并浏览
- **WHEN** 用户点击"选择PDF"按钮并选择一个PDF文件
- **THEN** 系统将PDF渲染为图像并在视图中显示第一页，用户可通过翻页按钮浏览所有页面

#### Scenario: 绘制文本框
- **WHEN** 用户在PDF页面上按住鼠标左键拖拽
- **THEN** 系统绘制一个矩形框，外框颜色为蓝色，填充为透明
- **AND** 框的信息（页码、坐标）被记录到内部数据结构中

#### Scenario: 删除文本框
- **WHEN** 用户右键点击一个已绘制的框
- **THEN** 弹出菜单提供"删除"选项，选择后该框被移除

#### Scenario: 完成画框
- **WHEN** 用户点击"完成"按钮
- **THEN** 系统发射 `finished_signal`，携带 `pdf_path` 和 `regions`（按页码组织的框列表）
- **AND** 主窗口切换到OCR准备阶段，并将 `pdf_path` 和 `regions` 传递给 OCRPrepareWindow

### Requirement: OCR区域限制识别
系统 SHALL 支持在OCR识别时仅识别用户指定区域内的文本。

#### Scenario: 带区域限制的OCR识别
- **WHEN** OCR引擎收到 `regions` 参数（非空）
- **THEN** 对每一页，仅对 `regions` 中该页对应的框区域进行OCR识别
- **AND** 识别结果的坐标为相对于整页的绝对坐标

#### Scenario: 无区域限制的OCR识别
- **WHEN** OCR引擎收到 `regions` 参数为 None 或空
- **THEN** 对整页进行OCR识别（保持原有行为）

### Requirement: OCR准备阶段接收区域信息
系统 SHALL 让OCR准备阶段接收并使用来自画框步骤的区域信息。

#### Scenario: 从画框步骤进入OCR准备
- **WHEN** 画框步骤完成并传递 `pdf_path` 和 `regions`
- **THEN** OCR准备窗口自动填入PDF路径，且OCR识别时使用这些区域限制
- **AND** 后续横校、纵校、精修仅包含框内文本

## MODIFIED Requirements

### Requirement: 主窗口步骤流程
主窗口的步骤从4步变为5步：画框 → OCR准备 → 横校 → 纵校 → 精修。步骤指示器显示5个步骤标签。

### Requirement: OCR引擎识别方法
`OCREngine.run_ocr` 方法新增可选参数 `regions`，类型为 `dict[int, list[list[float]]]`（键为页码，值为该页的框坐标列表，每个框为 `[x1, y1, x2, y2]`）。当 `regions` 不为空时，仅识别指定区域内的文本。

## REMOVED Requirements
无
