# 修复横校界面属性错误与优化布局 Spec

## Why
横校界面在初始化时因调用顺序问题导致 `grid_layout` 属性未创建就被访问，引发 AttributeError。同时需要优化横校界面布局使其更美观实用。

## What Changes
- 修复 `_init_ui` 中 `_refresh_label_list()` 调用顺序导致的 AttributeError
- 优化横校界面布局：使用 QGroupBox 分组、统一按钮样式、改善切片展示

## Impact
- Affected code: ui/horizontal_check_window.py

## ADDED Requirements

### Requirement: 横校界面布局优化
系统 SHALL 使用 QGroupBox 分组展示横校界面的各个区域，按钮样式统一美观。

#### Scenario: 界面分组
- **WHEN** 横校界面启动
- **THEN** 左侧字符列表和右侧切片展示区域有清晰的视觉分组和边框

## MODIFIED Requirements

### Requirement: 横校界面初始化
`_refresh_label_list()` 必须在所有UI控件创建完成之后调用，避免访问未创建的属性。

## REMOVED Requirements
无
