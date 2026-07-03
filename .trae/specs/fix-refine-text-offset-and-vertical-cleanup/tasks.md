# Tasks

- [x] Task 1: 修复精修 MovableTextItem 文字与框错位
  - [x] 在 __init__ 中设置 `_text_item.document().setDocumentMargin(0)` 去除默认边距
  - [x] 添加 _center_text 方法调整文字居中
  - [x] 在 update_zoom 和 mouseMoveEvent 缩放时同步更新文字位置

- [x] Task 2: 移除纵校"调整位置"功能
  - [x] 删除 _on_context_menu 中的 adjust_action 相关代码
  - [x] 删除 _on_adjust_position 方法
  - [x] 删除 _on_finish 中 adjust_count 统计和显示

- [x] Task 3: 纵校切片宽度与行文本一致
  - [x] 修改 eventFilter 中切片缩放逻辑：计算行文本显示宽度，按比例缩放切片到该宽度

# Task Dependencies
- Task 1, 2, 3 互相独立，可并行
