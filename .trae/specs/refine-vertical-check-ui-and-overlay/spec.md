# 纵校 UI 精修与字框叠加 Spec

## Why
当前纵校窗口存在三处体验缺陷:(1) "上一步"按钮采用默认样式,与右侧蓝色"下一步"按钮视觉不对称;(2) 分页行列数计算因多余的 `-40`/`-60` 边距扣除,导致每页少排一行/一列,浪费展示空间;(3) 原图预览仅显示当前选中字的红框,用户无法看到同行其他字的位置上下文,校对时难以判断切分是否正确。

## What Changes
- "上一步"按钮应用与"下一步"一致的蓝色样式(min-height 44px、min-width 120px、圆角、hover 效果)
- 修正 `_recalc_layout` 行列数算法:水平边距由 `-40` 改为 `-2`(仅扣除滚动区边框),垂直边距由 `-60` 改为 `0`(viewport 已排除同级布局),确保一行排满再换行、一页排满再换页
- 原图预览区顶部新增工具栏,含"显示其他字框"复选框;勾选后,当前行切片预览上除红框(当前字)外,以蓝框标出同行全部其他字符的 bbox

## Impact
- Affected specs: enhance-vertical-check-nav-and-preview(按钮文字动态变化逻辑不变,仅样式统一)
- Affected code: `d:\hx\software2\ui\vertical_check_window.py`(`_init_ui`、`_recalc_layout`、`PreviewGraphicsView.set_scene_pixmap`、`_show_line_preview`、新增 `_on_overlay_toggle`)
- 依赖数据: `ocr_results` 的 `chars` 列表(每条含 `page_num`、`line_id`、`char_id`、`box`),已由 RapidOCR 引擎产出

## ADDED Requirements

### Requirement: 原图预览字框叠加工具栏
系统 SHALL 在原图预览区顶部提供一条工具栏,包含"显示其他字框"复选框。

#### Scenario: 勾选复选框显示蓝框
- **WHEN** 用户勾选"显示其他字框"且当前已选中某切片
- **THEN** 预览图上除当前字红框外,以蓝色矩形框标出该切片所属行的全部其他字符 bbox

#### Scenario: 取消勾选隐藏蓝框
- **WHEN** 用户取消勾选"显示其他字框"
- **THEN** 预览图仅显示当前字红框,蓝框全部消失

#### Scenario: 切换选中切片时保持叠加状态
- **WHEN** 复选框处于勾选状态,用户点击切换到另一切片
- **THEN** 新预览图自动按当前勾选状态渲染蓝框(同行其他字)

## MODIFIED Requirements

### Requirement: 上一步按钮样式
"上一步"按钮 SHALL 与"下一步"按钮采用相同的蓝色样式(背景 #0D6EFD、白色文字、min-height 44px、min-width 120px、padding 10px 30px、border-radius 6px、font-size 14px、hover #0b5ed7),仅文字随位置动态变化("上一步"/"返回导入")。

### Requirement: 分页行列数计算
`_recalc_layout` SHALL 按滚动区 viewport 实际可用尺寸计算行列数,水平方向仅扣除 2px 边框、垂直方向不扣除同级布局高度,公式为:
- `cols = max(1, int((viewport_width - 2 + spacing) / (slice_size + spacing)))`
- `rows = max(1, int(viewport_height / (slice_size + spacing)))`
- `page_size = cols * rows`

确保一行排满再换行、一页排满再换页,最大化利用展示区域。

## Assumptions & Decisions
1. 两个按钮都使用蓝色主按钮样式,左右对称;用户明确要求"一致",不区分主次操作
2. 蓝框颜色选用 `#0d6efd`(与按钮主色一致),线宽 1px、cosmetic pen,无填充
3. 蓝框不应用 `min_display` 最小显示尺寸,保持 bbox 真实大小以提供准确上下文
4. 蓝框作为 `pixmap_item` 的子项(`setParentItem`),随 pixmap 清除自动回收,无需单独管理生命周期
5. 工具栏使用 `QHBoxLayout` + `QCheckBox` 实现(轻量,无需 QToolBar 的浮动/可拖拽特性)
6. 复选框状态变化时重新调用 `_preview_slice` 刷新当前预览,而非增量增删蓝框(逻辑简单、性能足够)
7. 同行其他字通过 `ocr_results` 的 `chars` 列表按 `page_num + line_id` 过滤,排除当前 `char_id`
8. 行列算法修正后,`_navigate_selection` 的方向键 delta(基于 `_current_columns`)自动适配新列数,无需额外改动
