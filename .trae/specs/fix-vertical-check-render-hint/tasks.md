# Tasks
- [x] Task 1: 修复 vertical_check_window.py 第 119 行 RenderHint 枚举引用方式
  - [x] 将 `self.view.RenderHint.Antialiasing` 改为 `QPainter.RenderHint.Antialiasing`
  - [x] 在 QtGui 导入中添加 `QPainter`
