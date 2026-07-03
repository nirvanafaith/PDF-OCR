# 修复纵校窗口 RenderHint 属性错误 Spec

## Why
横校完成进入纵校时，`VerticalCheckWindow.__init__` 中 `self.view.RenderHint.Antialiasing` 报 `AttributeError`，因为 PyQt6 的枚举类型是类属性而非实例属性。

## What Changes
- 修复 `vertical_check_window.py` 第 119 行：`self.view.RenderHint.Antialiasing` → `QGraphicsView.RenderHint.Antialiasing`

## Impact
- Affected code: `ui/vertical_check_window.py`

## MODIFIED Requirements
### Requirement: 纵校窗口初始化
纵校窗口 SHALL 使用 `QGraphicsView.RenderHint.Antialiasing`（类属性）设置渲染提示，而非 `self.view.RenderHint.Antialiasing`（实例属性）。
