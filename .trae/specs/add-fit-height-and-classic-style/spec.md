# 适合高度按钮 + 经典银灰风格 Spec

## Why
PDF阅读界面缺少"适合高度"缩放功能，仅有"适合宽度"不够灵活；当前界面使用现代圆角蓝色风格，用户希望改为经典方形银灰风格。

## What Changes
- 在软件1画框、软件2横校和精修的工具栏添加"适合高度"按钮
- 将两个软件的界面风格从现代蓝色圆角改为经典银灰方形

## Impact
- Affected code: 软件1/ui/draw_box_window.py, 软件2/ui/horizontal_check_window.py, 软件2/ui/refine_window.py, 软件1/ui/styles.py, 软件2/ui/styles.py, 软件1/main.py, 软件2/main.py

## ADDED Requirements

### Requirement: 适合高度按钮
系统SHALL在PDF阅读界面的工具栏提供"适合高度"按钮，点击后将页面缩放至适合视口高度。

#### Scenario: 点击适合高度
- **WHEN** 用户点击"适合高度"按钮
- **THEN** 系统根据视口高度和页面图像高度计算缩放比例，重新渲染页面

### Requirement: 经典银灰界面风格
系统SHALL使用经典方形银灰风格，包括方形边框、银灰色配色、无圆角。

#### Scenario: 界面显示
- **WHEN** 应用启动
- **THEN** 工具栏、按钮、列表等控件均为方形边框、银灰色调
