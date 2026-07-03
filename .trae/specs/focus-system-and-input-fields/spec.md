# 画框焦点系统 + 页码缩放输入框 Spec

## Why
画框环节缺少框选中和删除功能，操作不便；页码和缩放率仅显示不可编辑，用户无法快速跳转和精确控制缩放。

## What Changes
- 软件1画框窗口新增焦点系统：点击框选中加粗，Delete删除，点击空白/翻页取消选中
- 软件1画框窗口页码和缩放率从QLabel改为QLineEdit输入框
- 软件2横校和精修窗口缩放率从QLabel改为QLineEdit输入框

## Impact
- Affected code: 软件1/ui/draw_box_window.py, 软件2/ui/horizontal_check_window.py, 软件2/ui/refine_window.py

## ADDED Requirements

### Requirement: 画框焦点系统
系统SHALL在画框环节支持框的选中和删除。

#### Scenario: 点击框选中
- **WHEN** 用户点击一个已存在的框
- **THEN** 该框边框变粗变红，成为选中状态，旧选中框恢复普通样式

#### Scenario: Delete删除
- **WHEN** 选中框后按Delete键
- **THEN** 删除该框并取消选中

#### Scenario: 点击空白取消选中
- **WHEN** 用户点击PDF空白区域
- **THEN** 取消当前选中框的选中状态

#### Scenario: 翻页取消选中
- **WHEN** 用户翻页
- **THEN** 取消当前选中框的选中状态

### Requirement: 页码输入框
系统SHALL将页码显示改为输入框，用户输入页码按Enter可跳转。

#### Scenario: 输入页码跳转
- **WHEN** 用户在页码输入框输入有效页码并按Enter
- **THEN** 跳转到对应页面

### Requirement: 缩放输入框
系统SHALL将缩放率显示改为输入框，用户输入百分比按Enter可改变缩放。

#### Scenario: 输入缩放率
- **WHEN** 用户在缩放输入框输入有效百分比（10-1000）并按Enter
- **THEN** 页面按新缩放率重新渲染
