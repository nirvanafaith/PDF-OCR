# Tasks

- [x] Task 1: 按钮迁移与动态文字
  - [x] SubTask 1.1: import 添加 `QMessageBox`(L3-24 import 块)
  - [x] SubTask 1.2: `_init_ui` 中删除 `self.back_btn` 及其添加到 left_layout 的代码(L343-345);删除 `_on_back` 方法
  - [x] SubTask 1.3: `_init_ui` 的 `bottom_layout`(L448-459)中,在 `addStretch()` 之前添加 `self.prev_step_btn = QPushButton("上一步")`,连接 `_on_prev_step`
  - [x] SubTask 1.4: 新增 `_on_prev_step` 方法:若 `current_row == 0` 则 `self.back_signal.emit()`;否则 `_flush_pending_modifications()` + `blockSignals` + `setCurrentRow(max(0, current_row-1))` + `blockSignals` + 更新显示
  - [x] SubTask 1.5: 新增 `_update_nav_button_texts` 方法:根据 `self.label_list.currentRow()` 与 `count()` 更新 `prev_step_btn` 文字("返回导入" if row==0 else "上一步")与 `next_button` 文字("进入横校" if row==count-1 else "下一步")
  - [x] SubTask 1.6: 在 `_update_slice_display` 末尾调用 `self._update_nav_button_texts()`;在 `_refresh_label_list` 末尾(setCurrentRow(0) 之后)也调用一次(保险)

- [x] Task 2: 字符跳转输入框
  - [x] SubTask 2.1: `_init_ui` 的 `left_layout` 顶部(原 back_btn 位置)添加 `self.jump_edit = QLineEdit()` + `self.jump_btn = QPushButton("确认")` 的水平布局
  - [x] SubTask 2.2: 连接 `jump_btn.clicked` 与 `jump_edit.returnPressed` 到 `self._on_jump_char`
  - [x] SubTask 2.3: 新增 `_on_jump_char` 方法:`text = self.jump_edit.text().strip()`;若空则 return;若 `text in self.char_slices` 则遍历 `label_list` 找到 `item.data(Qt.UserRole) == text` 并 `setCurrentItem(item)`;否则 `QMessageBox.warning(self, "未找到", f"没有找到字符: {text}")`

- [x] Task 3: 单选切片方向键导航
  - [x] SubTask 3.1: 修改 `keyPressEvent`:删除 `elif event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return: self._on_next_step()` 分支(保留 Space)
  - [x] SubTask 3.2: 在 `keyPressEvent` 中添加方向键处理:仅当 `len(self._selected_indices) == 1 and self._last_clicked_index is not None` 时,根据 `Qt.Key_Up/Down/Left/Right` 调用 `_navigate_selection(delta)`,否则 `super().keyPressEvent(event)`
  - [x] SubTask 3.3: 新增 `_navigate_selection(delta)` 方法:计算 `start = self._current_page * self._current_page_size`;`page_idx = self._last_clicked_index - start`;获取 `slices = self.char_slices.get(self._current_char_text, [])`;`page_slices_len = min(self._current_page_size, len(slices) - start)`;若 `page_idx < 0 or page_idx >= page_slices_len` 则 return;`new_page_idx = (page_idx + delta) % page_slices_len`;`new_global_idx = start + new_page_idx`;清空选中设为 `{new_global_idx}`;`_last_clicked_index = new_global_idx`;`_refresh_slice_selection_visuals()`;`_preview_slice(new_global_idx)`
  - [x] SubTask 3.4: 方向键 delta 映射:Up = `-self._current_columns`;Down = `+self._current_columns`;Left = `-1`;Right = `+1`

- [x] Task 4: 整行 PDF 长条预览
  - [x] SubTask 4.1: 修改 `_show_line_preview`:将裁剪算法改为复用横校 `_make_slice_pixmap` 逻辑
    - 确定 y 范围:优先用 `line_box`(flatten_bbox 后的 `lx1, ly1, lx2, ly2`)的 `ly1, ly2`;若 `line_box is None` 则用 `char_slice.bbox` 的 `cy1, cy2` 作为回退
    - `pad = 20`;`crop_x1 = 0`;`crop_y1 = max(0, int(line_y1) - pad)`;`crop_x2 = page_img.width`;`crop_y2 = min(img_h, int(line_y2) + pad)`
    - 去除原有的 `margin_x`/`margin_y` 计算(L668-673)
  - [x] SubTask 4.2: 调整 cache_key 为 `(page_num, crop_y1, crop_y2)`(x 始终全宽,仅 y 变化)
  - [x] SubTask 4.3: 红框坐标调整为:`rect_x = cx1 - crop_x1`(即 cx1,因 crop_x1=0);`rect_y = cy1 - crop_y1`;`rect_w = max(1, cx2 - cx1)`;`rect_h = max(1, cy2 - cy1)`;保留 min_display 逻辑
  - [x] SubTask 4.4: 保留 `set_scene_pixmap` + `center_on_rect` 调用不变(center_on_rect 居中红框,用户看到整行上下文 + 居中字符)

- [x] Task 5: 验证
  - [x] SubTask 5.1: `python -m py_compile ui\vertical_check_window.py` 语法验证
  - [x] SubTask 5.2: context7 复查 QMessageBox.warning、QLineEdit.returnPressed、Qt.Key_* API 使用正确
  - [x] SubTask 5.3: Grep 确认无残留 `back_btn` 引用、无残留 `_on_back` 定义
  - [x] SubTask 5.4: 通读修改后代码,确认按钮文字更新、方向键导航、整行预览逻辑正确

# Task Dependencies

- Task 1、2、3、4 相互独立(修改不同方法),可并行实施,但均修改同一文件,建议串行避免 Edit 冲突
- Task 5 依赖 Task 1-4 完成
