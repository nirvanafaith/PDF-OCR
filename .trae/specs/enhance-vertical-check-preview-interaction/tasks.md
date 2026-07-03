# Tasks

- [x] Task 1: 缩减切片输入框宽度
  - [x] SubTask 1.1: `SliceItemWidget.__init__` 将 `self._char_input.setGeometry(40, 68, 45, 18)` 改为 `self._char_input.setGeometry(63, 68, 22, 18)`(宽度 45→22,右移保持右下角对齐)

- [x] Task 2: 蓝框 tooltip 与点击高亮
  - [x] SubTask 2.1: 修改 `_show_line_preview` 收集 overlay_rects 时,改为 `list[tuple[QRectF, str]]`,每项 `(QRectF(ox,oy,ow,oh), char_data.get("char",""))`
  - [x] SubTask 2.2: 修改 `PreviewGraphicsView.set_scene_pixmap` 的 `overlay_rects` 参数为 `list[tuple[QRectF, str]]`;遍历时解包 `(ov_rect, char_text)`,创建 `QGraphicsRectItem` 后调用 `ov_item.setToolTip(char_text)` 与 `ov_item.setData(Qt.UserRole, char_text)`;初始化 `self._highlighted_overlay = None`、`self._overlay_interaction_enabled = False`
  - [x] SubTask 2.3: `VerticalCheckWindow._on_overlay_toggle` 中增加 `self.preview_view._overlay_interaction_enabled = bool(state)`
  - [x] SubTask 2.4: 重写 `PreviewGraphicsView.mousePressEvent` 开头:命中蓝框时高亮(橙色 #ff9500, 2px),重置上一个高亮为蓝色
  - [x] SubTask 2.5: `set_scene_pixmap` 开头重置 `self._highlighted_overlay = None`
  - [x] SubTask 2.6: `PreviewGraphicsView.__init__` 添加 `self.setMouseTracking(True)`

- [x] Task 3: 红框可选中与拖拽调整
  - [x] SubTask 3.1: `PreviewGraphicsView.__init__` 初始化红框调整状态变量
  - [x] SubTask 3.2: 新增 `_hit_red_rect_handle(view_pos)` 方法:6px 容差,4 角优先,4 边中点
  - [x] SubTask 3.3: 重写 `mousePressEvent` 红框部分:手柄命中→进入 resize;内部命中→高亮选中
  - [x] SubTask 3.4: 重写 `mouseMoveEvent`:delta/scale 转换为 pixmap 本地增量,按 handle 调整对应边,clamp + min 4px
  - [x] SubTask 3.5: 重写 `mouseReleaseEvent`:比较 final_rect 与 start_rect,差异>0.5px 则标记 dirty
  - [x] SubTask 3.6: `set_scene_pixmap` 重建时重置 `_resizing/_red_rect_selected/_resize_handle`,保留 `_resized_dirty` 供 VCW 提交

- [x] Task 4: 焦点切换时按红框重新切片
  - [x] SubTask 4.1: `VerticalCheckWindow.__init__` 添加 `self._current_crop_offset = (0, 0)`
  - [x] SubTask 4.2: `_show_line_preview` 中计算完 `crop_x1, crop_y1` 后,记录 `self._current_crop_offset = (crop_x1, crop_y1)`
  - [x] SubTask 4.3: 新增 `_update_ocr_results_char_box(char_slice, new_bbox)`:遍历 `ocr_results[1]`(chars),匹配 `page_num+line_id+char_id`,设置 `char_data["box"] = list(new_bbox)`
  - [x] SubTask 4.4: 新增 `_commit_pending_red_box_resize()`:local_rect + crop_offset = 页面绝对 bbox,clamp 边界,重新 crop page_image,更新 char_slice.image/bbox + ocr_results.box,失效 _pixmap_cache,清空 dirty
  - [x] SubTask 4.5: 在 7 个方法开头调用 `_commit_pending_red_box_resize()`:`_on_slice_clicked`、`_preview_slice`、`_on_label_selected`、`_on_next_step`、`_on_prev_step`、`_on_next_page`、`_on_prev_page`

- [x] Task 5: 验证
  - [x] SubTask 5.1: `python -m py_compile ui\vertical_check_window.py` 语法验证通过(exit code 0)
  - [x] SubTask 5.2: Grep 确认 `setGeometry(63, 68, 22, 18)`(L419)、`_overlay_interaction_enabled`(L51/127/928)、`_hit_red_rect_handle`(L71/147)、`_commit_pending_red_box_resize`(L1405)、`_update_ocr_results_char_box`(L1393)、`_current_crop_offset`(L518/867/1423)均已定义
  - [x] SubTask 5.3: Grep 确认 7 个焦点切换方法开头均调用 `_commit_pending_red_box_resize()`(L721/781/816/1219/1510/1519/1536)
  - [x] SubTask 5.4: context7 复查 QRectF.right()/bottom() 返回真实坐标(非 QRect 的 -1 行为),QGraphicsRectItem.rect()→QRectF,QGraphicsScene.itemAt(QPointF, QTransform),mapToScene/mapFromScene API 使用正确
  - [x] SubTask 5.5: 通读修改后代码确认:坐标数学正确(pixmap local + crop_offset = page absolute)、PIL crop box 格式匹配 [x1,y1,x2,y2]、cache key 格式一致 (char_text, global_idx)、clamp 防止无效 rect、dirty 清空防重复提交、_preview_slice 提交防止 set_scene_pixmap 丢弃调整、7 个入口均 commit-before-switch

# Task Dependencies
- Task 1 独立(改 SliceItemWidget)
- Task 2、3 均修改 PreviewGraphicsView.mousePressEvent,串行(Task 2 先,Task 3 扩展优先级链)
- Task 4 依赖 Task 3(红框 dirty 状态由 Task 3 产生)
- Task 5 依赖 Task 1-4 完成
