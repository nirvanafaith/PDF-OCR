# 单窗口多阶段切换与PDF缩放优化 Spec

## Why
当前每个阶段（OCR准备→横校→纵校→精修）都是独立的 QMainWindow，切换时窗口关闭/打开体验差。纵校和精修的 PDF 默认缩放比例过大，无法完整显示。

## What Changes
- 将四个阶段窗口从 QMainWindow 改为 QWidget，嵌入 MainWindow 的 QStackedWidget
- MainWindow 添加进度条显示当前阶段
- 纵校和精修窗口首次渲染时自动适合宽度
- **BREAKING**: 四个阶段窗口类从 QMainWindow 改为 QWidget，toolbar 从 addToolBar 改为布局内嵌

## Impact
- Affected code: `main.py`, `ui/ocr_prepare_window.py`, `ui/horizontal_check_window.py`, `ui/vertical_check_window.py`, `ui/refine_window.py`
- Affected specs: 所有阶段切换逻辑

## ADDED Requirements

### Requirement: 单窗口多阶段切换
系统 SHALL 在同一个窗口内完成所有阶段切换，使用 QStackedWidget 管理四个阶段页面，切换时无窗口关闭/打开。

#### Scenario: 阶段切换
- **WHEN** 用户完成一个阶段点击下一步
- **THEN** 当前页面切换到下一阶段页面，窗口保持不变
- **AND** 进度条更新显示当前阶段

### Requirement: 进度条显示
MainWindow 顶部 SHALL 显示进度条，包含四个步骤标签（OCR准备、横校、纵校、精修），当前步骤高亮显示。

#### Scenario: 进度显示
- **WHEN** 用户处于任意阶段
- **THEN** 进度条高亮当前步骤，已完成步骤显示为已完成状态

### Requirement: PDF自动适合宽度
纵校和精修窗口首次渲染 PDF 时 SHALL 自动计算缩放比例使 PDF 宽度适合视图宽度。

#### Scenario: 首次渲染
- **WHEN** 纵校或精修窗口首次显示 PDF 页面
- **THEN** 自动计算 zoom_level 使 PDF 宽度等于视图宽度减去边距

## MODIFIED Requirements

### Requirement: 阶段窗口类型
所有阶段窗口 SHALL 继承 QWidget 而非 QMainWindow。toolbar 通过布局内嵌而非 addToolBar。

### Requirement: MainWindow架构
MainWindow SHALL 使用 QStackedWidget 管理四个阶段页面，不再创建/关闭独立窗口。

## REMOVED Requirements
无
