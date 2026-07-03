# Checklist

## Task 1: 纵校已检查标记修复
- [x] `_on_next_step` 中 `self._checked_chars.add(...)` 之后有 `item.setBackground(QBrush(QColor("#b3d9ff")))` 调用
- [x] 有越界保护（`0 <= current_row < self.label_list.count()`）
- [x] 有空值保护（`item is not None`）
- [x] 即时更新在 `_flush_pending_modifications()` 之前执行
- [x] `_refresh_label_list` 中的原浅蓝逻辑保留（双重保证）
- [x] 无修改点击下一步时浅蓝底色立即显示

## Task 2: 精修字号优化
- [x] `_calculate_max_font_size(text, frame_w, frame_h)` 方法存在
- [x] 候选字号为 `int(frame_h)`
- [x] 使用 `QFontMetrics.horizontalAdvance(text)` 测量字符宽度
- [x] 使用 `fm.ascent() + fm.descent()` 测量字符高度
- [x] 字符宽度超框时按比例缩小字号
- [x] 字符高度超框时按比例缩小字号
- [x] 最小字号 1px
- [x] `mouseMoveEvent` 中字号设置调用 `_calculate_max_font_size`
- [x] `update_zoom` 中字号设置调用 `_calculate_max_font_size`
- [x] 拖拽缩放时字号实时更新为框内最大字体

## 通用验证
- [x] `python -m py_compile ui\vertical_check_window.py` 通过
- [x] `python -m py_compile ui\refine_window.py` 通过
- [x] Grep 确认纵校新增 `setBackground` 调用
- [x] Grep 确认精修新增 `_calculate_max_font_size` 方法
- [x] Grep 确认 `mouseMoveEvent` 和 `update_zoom` 调用新方法
- [x] 无关代码（`_make_slice_pixmap`、`_hover_rect_item`、`_sync_current_page` 等）未被修改
- [x] context7 确认 QFontMetrics API 使用正确
