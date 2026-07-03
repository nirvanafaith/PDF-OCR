# 纵校原图预览交互增强 Spec

## Why
当前原图预览的"显示其他字框"功能仅静态显示蓝框,无法点击交互或查看对应文字;切片右下角输入框过宽遮挡图像;红框(当前字 bbox)不可调整,当 OCR 切分边界不准时用户无法在纵校阶段直接修正,必须回到横校或外部工具。

## What Changes
- 蓝框交互:勾选"显示其他字框"后,点击原图预览上某蓝框则高亮该框(橙色加粗);鼠标悬停蓝框显示对应字符文字 tooltip
- 切片右下角输入框横向宽度缩减一半(45px → 22px),保持右下角对齐
- 红框可拖拽调整:点选红框高亮,拖拽四边/四角改变大小;焦点切换(选其他切片、换字符集合、上一步/下一步、翻页)时,按拖拽后的红框重新裁切该字符切片并更新 JSON 的 box 字段

## Impact
- Affected specs: refine-vertical-check-ui-and-overlay(蓝框从静态叠加升级为可交互;红框从只读升级为可调整)
- Affected code: `d:\hx\software2\ui\vertical_check_window.py`
  - `PreviewGraphicsView`(mousePressEvent/mouseMoveEvent/mouseReleaseEvent 重写、set_scene_pixmap 扩展、新增 resize 逻辑)
  - `SliceItemWidget.__init__`(输入框 setGeometry)
  - `VerticalCheckWindow._show_line_preview`(overlay_rects 携带 char_text、记录 crop offset)
  - `VerticalCheckWindow`(新增 `_commit_pending_red_box_resize`、`_update_ocr_results_char_box`,在所有焦点切换入口调用)
- 依赖数据: `ocr_results` 的 `chars` 列表(每条含 `page_num`、`line_id`、`char_id`、`box`、`char`)

## ADDED Requirements

### Requirement: 蓝框点击高亮与悬停提示
系统 SHALL 在"显示其他字框"勾选时,支持点击原图预览上的蓝框以高亮该框(橙色 #ff9500 加粗),且鼠标悬停蓝框时显示其对应字符文字的 tooltip。

#### Scenario: 点击蓝框高亮
- **WHEN** "显示其他字框"已勾选,用户点击原图预览中某个蓝框
- **THEN** 该蓝框变为橙色加粗高亮,之前高亮的蓝框恢复为蓝色细线;不触发平移

#### Scenario: 悬停蓝框显示文字
- **WHEN** 鼠标悬停在某个蓝框上
- **THEN** 显示 tooltip,内容为该蓝框对应的字符文字

#### Scenario: 取消勾选后蓝框不可点击
- **WHEN** "显示其他字框"未勾选
- **THEN** 点击原图预览不触发蓝框高亮(无蓝框显示),恢复为平移行为

### Requirement: 红框可拖拽调整大小
系统 SHALL 支持点选红框使其高亮,并拖拽红框的四边或四角调整其大小,拖拽范围限制在所属 PDF 页面图像边界内。

#### Scenario: 点选红框高亮
- **WHEN** 用户点击红框内部或边缘
- **THEN** 红框变为高亮状态(加粗或变色),表明已选中可调整

#### Scenario: 拖拽边角调整大小
- **WHEN** 用户在红框高亮状态下,按下并拖拽某个边或角
- **THEN** 红框对应边/角随鼠标移动调整,对边/对角固定;红框不超出页面图像边界;最小尺寸不小于 4px

#### Scenario: 拖拽完成后标记脏状态
- **WHEN** 拖拽结束且红框尺寸相比拖拽前发生变化
- **THEN** 系统记录该红框已修改(脏状态),等待焦点切换时提交

### Requirement: 焦点切换时按红框重新切片
系统 SHALL 在切换焦点(选中其他切片、切换字符集合、上一步/下一步、翻页)时,若当前预览切片的红框被拖拽修改过,则按新红框重新裁切该字符切片图像、更新其 bbox 与对应 JSON 的 box 字段,并失效相关缓存。

#### Scenario: 焦点切换提交红框修改
- **WHEN** 用户拖拽红框后,执行选中其他切片/换字符集合/上一步/下一步/翻页等任一焦点切换
- **THEN** 系统按新红框(pixmap 本地坐标 + crop 偏移 = 页面绝对坐标)从页面图像重新裁切 char_slice.image,更新 char_slice.bbox,更新 ocr_results 中对应 char_data 的 `box` 字段(扁平 [x1,y1,x2,y2]),并从 _pixmap_cache 删除该切片缓存

#### Scenario: 未拖拽不提交
- **WHEN** 红框未被拖拽修改,焦点切换
- **THEN** 不执行重新切片,行为与原有逻辑一致

## MODIFIED Requirements

### Requirement: 切片右下角输入框尺寸
`SliceItemWidget` 的字符输入框 SHALL 横向宽度为原来的一半(45px → 22px),保持右下角位置对齐(setGeometry(63, 68, 22, 18)),其余样式不变。

## Assumptions & Decisions
1. 蓝框交互优先级高于平移:勾选"显示其他字框"时,点击命中蓝框则高亮且不平移;未命中则平移
2. 红框交互优先级最高:点击命中红框边角(6px 容差)进入调整;命中红框内部则仅高亮选中;均不命中才平移
3. 完整 mousePressEvent 优先级:蓝框高亮(需勾选) > 红框边角调整 > 红框内部选中 > 平移
4. 蓝框 tooltip 通过 `QGraphicsItem.setToolTip(char_text)` 实现,Qt 自动管理悬停显示,无需手动 mouseMoveEvent
5. 蓝框高亮通过切换 `QPen` 实现:蓝色(#0d6efd, 1px) ↔ 橙色(#ff9500, 2px);`set_scene_pixmap` 重建时重置高亮引用为 None
6. 蓝框携带文字:`overlay_rects` 参数从 `list[QRectF]` 改为 `list[tuple[QRectF, str]]`,创建时 `setData(Qt.UserRole, char_text)` 以便点击命中时识别
7. 红框调整的手柄检测在视图像素空间进行(将红框 `sceneBoundingRect` 映射到 view 坐标),6px 容差,8 个手柄(4 角 + 4 边中点),角优先
8. 红框调整在 pixmap 本地坐标空间执行:鼠标增量 delta / 当前缩放因子 = pixmap 本地增量,直接 `rect_item.setRect(new_rect)`
9. 脏状态存储于 `PreviewGraphicsView._resized_dirty` + `_resized_rect`(pixmap 本地);`VerticalCheckWindow` 额外存储 `_current_crop_offset = (crop_x1, crop_y1)` 用于还原页面绝对坐标
10. JSON box 字段更新为扁平 `[x1, y1, x2, y2]` 格式;`flatten_bbox` 读取时原样返回,兼容现有逻辑
11. 重新切片不改变字符文字,切片留在原字符集合中(不触发 _move_slice_to_new_char)
12. 焦点切换入口统一调用 `_commit_pending_red_box_resize()`:`_on_slice_clicked`、`_preview_slice`、`_on_label_selected`、`_on_next_step`、`_on_prev_step`、`_on_next_page`、`_on_prev_page`
13. 红框高亮选中状态:点选后 pen 加粗(2px → 3px)或变色(#dc3545 → #ff0000);`set_scene_pixmap` 重建时重置
14. `_pixmap_cache` 按 `(char_text, global_idx)` 失效;`_line_preview_cache` 因 crop_y 可能变化自动生成新 key,旧 key 由 LRU 淘汰
