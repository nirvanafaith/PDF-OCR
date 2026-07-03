# 纵校提示改进与精修环节 Spec

## Why
纵校环节的 PDF 切片提示跟随鼠标移动，操作不便；纵校完成后直接生成 PDF 退出，缺少对双层 PDF 的精细编辑能力。需要改进纵校提示方式并新增精修环节。

## What Changes
- 纵校界面：鼠标悬停行文字时，PDF 切片固定显示在该行文字正上方，而非跟随鼠标
- 新增精修窗口（RefineWindow）：纵校完成后进入精修环节
  - 显示双层 PDF（底层原图 + 上层覆盖文字）
  - 可编辑上层文字内容
  - 可手动添加新文字
  - 可选中文字并拖动移动位置
  - 每个文字选中时显示边框，拖动四角可缩放
  - 点击输出按钮保存结果后回到 OCR 准备环节
- 主流程调整：纵校完成 → 精修 → 输出 → 回到准备环节

## Impact
- Affected code: `ui/vertical_check_window.py`, `main.py`, `models/data_models.py`, `ui/__init__.py`
- New code: `ui/refine_window.py`

## ADDED Requirements

### Requirement: 纵校切片固定定位显示
当鼠标悬停到纵校界面某行文字时，该行的原 PDF 切片 SHALL 固定显示在该行文字的正上方，不跟随鼠标移动。鼠标离开该行时切片消失。

#### Scenario: 鼠标悬停显示切片
- **WHEN** 鼠标移入某行文字区域
- **THEN** 该行的原 PDF 切片以 QGraphicsPixmapItem 形式固定显示在该行文字正上方
- **AND** 切片位置不随鼠标移动而变化

#### Scenario: 鼠标离开隐藏切片
- **WHEN** 鼠标移出该行文字区域
- **THEN** 切片立即消失

### Requirement: 精修窗口 - 双层PDF阅读
精修窗口 SHALL 以 QGraphicsScene 显示双层 PDF 内容：底层为原始页面图像，上层为可编辑的覆盖文字项。

#### Scenario: 显示双层PDF
- **WHEN** 进入精修环节
- **THEN** 窗口显示每页的原始 PDF 图像作为背景
- **AND** 在图像上方叠加显示已校正的文字项，每个文字项可独立操作

### Requirement: 精修窗口 - 编辑文字
用户 SHALL 能双击文字项修改其内容。

#### Scenario: 双击修改文字
- **WHEN** 用户双击某个文字项
- **THEN** 弹出编辑对话框，可修改文字内容
- **AND** 确认后文字项更新显示

### Requirement: 精修窗口 - 添加文字
用户 SHALL 能在页面上手动添加新文字。

#### Scenario: 右键添加文字
- **WHEN** 用户在页面空白处右键选择"添加文字"
- **THEN** 在右键位置弹出编辑对话框
- **AND** 确认后在对应位置创建新的文字项

### Requirement: 精修窗口 - 选中与移动文字
用户 SHALL 能选中文字项并拖动移动其位置。

#### Scenario: 拖动移动文字
- **WHEN** 用户点击某个文字项
- **THEN** 该文字项被选中，显示蓝色虚线边框和四角缩放手柄
- **WHEN** 用户拖动选中的文字项
- **THEN** 文字项跟随鼠标移动到新位置

### Requirement: 精修窗口 - 缩放文字
用户 SHALL 能通过拖动四角手柄缩放文字项。

#### Scenario: 拖动角点缩放
- **WHEN** 用户拖动选中文字项的四角手柄
- **THEN** 文字项及其边框按比例缩放
- **AND** 字体大小相应调整

### Requirement: 精修窗口 - 输出与循环
用户完成精修后 SHALL 能输出结果并回到 OCR 准备环节。

#### Scenario: 输出并回到准备环节
- **WHEN** 用户点击"输出"按钮
- **THEN** 系统生成双层 PDF 并保存
- **AND** 精修窗口关闭
- **AND** 回到 OCR 准备环节等待处理下一个工作

## MODIFIED Requirements

### Requirement: 主流程增加精修环节
主流程 SHALL 变为：OCR准备 → 横校 → 纵校 → 精修 → 输出 → 回到OCR准备。纵校完成后不再直接生成 PDF，而是进入精修环节。

### Requirement: 纵校切片显示方式
纵校界面的 PDF 切片 SHALL 从跟随鼠标的浮动窗口改为固定在该行文字正上方的 QGraphicsPixmapItem。
