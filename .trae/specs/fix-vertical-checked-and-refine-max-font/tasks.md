# Tasks

- [x] Task 1: 修复纵校已检查标记即时生效
  - [x] SubTask 1.1: 在 `_on_next_step` 方法中 `self._checked_chars.add(self._current_char_text)` 之后，立即获取 `self.label_list.currentRow()` 对应的 `QListWidgetItem`，调用 `item.setBackground(QBrush(QColor("#b3d9ff")))` 设置浅蓝底色
    - 需越界保护：`0 <= current_row < self.label_list.count()`
    - 需空值保护：`item is not None`
    - 插入位置：L1289（`self._checked_chars.add(...)`）之后、L1290（`current_row = self.label_list.currentRow()`）之前或之后均可，但必须在 `_flush_pending_modifications()` 之前

- [x] Task 2: 精修 MovableTextItem 字号优化为框内最大字体
  - [x] SubTask 2.1: 在 `MovableTextItem` 类中新增 `_calculate_max_font_size(self, text, frame_w, frame_h)` 方法
    - 候选字号 `candidate = int(frame_h)`
    - `font = QFont("Microsoft YaHei")`, `font.setPixelSize(candidate)`
    - `fm = QFontMetrics(font)`
    - `char_w = fm.horizontalAdvance(text)`
    - `char_h = fm.ascent() + fm.descent()`
    - 若 `char_w > frame_w and frame_w > 0`：`candidate = int(candidate * frame_w / char_w)`
    - 若 `char_h > frame_h and frame_h > 0`：`candidate = int(candidate * frame_h / char_h)`
    - 返回 `max(candidate, 1)` 和对应的 `font` 对象
  - [x] SubTask 2.2: 修改 `mouseMoveEvent` 中字号设置（当前 L333-335）
    - 替换 `font = QFont("Microsoft YaHei")` + `font.setPixelSize(max(int(new_h), 1))` + `self._text_item.setFont(font)`
    - 改为调用 `self._calculate_max_font_size(self._data.text, new_w, new_h)` 获取 font
    - `self._text_item.setFont(font)`
  - [x] SubTask 2.3: 修改 `update_zoom` 中字号设置（当前 L512-513）
    - 替换 `font = QFont("Microsoft YaHei")` + `font.setPixelSize(max(int(new_h), 1))` + `self._text_item.setFont(font)`
    - 改为调用 `self._calculate_max_font_size(self._data.text, new_w, new_h)` 获取 font
    - `self._text_item.setFont(font)`

- [x] Task 3: 验证
  - [x] SubTask 3.1: `python -m py_compile ui\vertical_check_window.py` 语法验证
  - [x] SubTask 3.2: `python -m py_compile ui\refine_window.py` 语法验证
  - [x] SubTask 3.3: Grep 确认 `_on_next_step` 中新增 `setBackground` 调用存在
  - [x] SubTask 3.4: Grep 确认 `_calculate_max_font_size` 方法存在
  - [x] SubTask 3.5: Grep 确认 `mouseMoveEvent` 和 `update_zoom` 中调用 `_calculate_max_font_size`
  - [x] SubTask 3.6: Grep 确认 `_make_slice_pixmap` 和 `_hover_rect_item` 等无关逻辑未被修改
  - [x] SubTask 3.7: context7 复查 QFontMetrics.horizontalAdvance/ascent/descent API 使用正确

# Task Dependencies
- Task 1 独立（纵校修复）
- Task 2 独立（精修优化）
- Task 3 依赖 Task 1 和 Task 2 完成
