# Tasks

- [x] Task 1: 统一上一步按钮样式
  - [x] SubTask 1.1: 在 `VerticalCheckWindow` 类定义顶部添加类常量 `_NAV_BTN_STYLE`,内容为现有 `next_button` 的 stylesheet 字符串(背景 #0D6EFD、白色文字、min-height 44px、min-width 120px、padding 10px 30px、border-radius 6px、font-size 14px、hover #0b5ed7)
  - [x] SubTask 1.2: `_init_ui` 中 `self.prev_step_btn = QPushButton("上一步")` 之后调用 `self.prev_step_btn.setStyleSheet(self._NAV_BTN_STYLE)`
  - [x] SubTask 1.3: 将 `self.next_button.setStyleSheet(...)` 的内联字符串替换为 `self.next_button.setStyleSheet(self._NAV_BTN_STYLE)`,消除重复

- [x] Task 2: 修正分页行列数算法
  - [x] SubTask 2.1: 修改 `_recalc_layout`(L479-500):将 `avail = viewport_width - 40` 改为 `avail = viewport_width - 2`
  - [x] SubTask 2.2: 将 `rows = max(1, int((viewport_height - 60) / item_h)) if viewport_height > 60 else 1` 改为 `rows = max(1, int(viewport_height / item_h)) if viewport_height > 0 else 1`
  - [x] SubTask 2.3: 验证 `cols`、`rows`、`page_size` 计算无需其他改动;`_render_current_page` 的 `row = page_idx // cols`、`col = page_idx % cols` 自动适配新列数

- [x] Task 3: 原图预览工具栏与字框叠加 UI
  - [x] SubTask 3.1: `_init_ui` 中 `preview_layout = QVBoxLayout(preview_group)` 之后、`self.preview_stack` 创建之前,插入工具栏布局
  - [x] SubTask 3.2: 在 import 块的 `PyQt5.QtWidgets` 中添加 `QCheckBox` 导入

- [x] Task 4: 蓝框渲染逻辑
  - [x] SubTask 4.1: 扩展 `PreviewGraphicsView.set_scene_pixmap` 签名为 `set_scene_pixmap(self, pixmap, rect_in_pixmap_coords, overlay_rects=None)`,其中 `overlay_rects` 为 `list[QRectF]` 或 `None`
  - [x] SubTask 4.2: 在 `set_scene_pixmap` 创建 `_rect_item`(红框)之后,若 `overlay_rects` 非空,遍历每个 `QRectF` 创建蓝色 `QGraphicsRectItem`(pen #0d6efd, width 1, cosmetic, NoBrush, parent=pixmap_item)
  - [x] SubTask 4.3: 修改 `_show_line_preview`:在调用 `set_scene_pixmap` 之前,若 `self.show_other_chars_cb.isChecked()` 为真,从 `ocr_results` 的 `chars` 列表收集同行其他字 bbox(过滤 page_num+line_id,排除当前 char_id),flatten_bbox 后转 pixmap 本地坐标,传入 `set_scene_pixmap`
  - [x] SubTask 4.4: 新增 `_on_overlay_toggle(self, state)`:若 `self._current_preview_index is not None`,调用 `self._preview_slice(self._current_preview_index)` 重新渲染当前预览

- [x] Task 5: 验证
  - [x] SubTask 5.1: `python -m py_compile ui\vertical_check_window.py` 语法验证
  - [x] SubTask 5.2: Grep 确认 `prev_step_btn` 与 `next_button` 均使用 `_NAV_BTN_STYLE`
  - [x] SubTask 5.3: Grep 确认 `_recalc_layout` 中无 `- 40` 与 `- 60` 残留
  - [x] SubTask 5.4: context7 复查 QCheckBox.stateChanged、QGraphicsRectItem.setParentItem API 使用正确
  - [x] SubTask 5.5: 通读修改后代码,确认按钮样式、行列算法、蓝框叠加、复选框切换逻辑正确

# Task Dependencies
- Task 1、2、3 相互独立(修改不同方法),可并行实施,但均修改同一文件,建议串行避免 Edit 冲突
- Task 4 依赖 Task 3(复选框 `show_other_chars_cb` 已创建)
- Task 5 依赖 Task 1-4 完成
