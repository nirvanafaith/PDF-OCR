# 纵校环节:手柄容差/已检查标记/删除跳转/默认选中

## Summary

针对 `d:\hx\software2\ui\vertical_check_window.py` 进行 4 项增强:
1. 红框四边四角的鼠标手柄判定区域向框内扩展(非对称容差)
2. 点击"下一步"时,原集合在字符列表中永久标记为浅蓝底色(已检查)
3. 删光集合后跳转到原集合向下数的下一个集合(而非第一个)
4. 无论何种方式进入集合时,默认选中第一个切片并显示原图预览

## Current State Analysis

### 变更 1: `_hit_red_rect_handle` (L72-113)
- 当前: `margin = 6` 对称容差,框内外各 6px
- 问题: 用户反馈"鼠标要挪边框需要点的位置太靠外",即框外 6px 不够直观,希望框内更容易点中手柄

### 变更 2: 字符列表已检查标记
- 当前: `_refresh_label_list` (L1298-1315) 创建 QListWidgetItem 时无背景色区分
- `_on_next_step` (L1258-1296) 切换到下一个字符组,无"已检查"概念
- styles.py L45-48: `QListWidget::item` 无 `background-color` → `setBackground()` 有效
- styles.py L50-53: `QListWidget::item:selected` (#316ac5) 选中时覆盖 → 符合预期(选中时显示选中色)
- styles.py L55-57: `QListWidget::item:hover` (#e8e4dc) 悬停时覆盖 → 可接受(临时状态)
- QBrush/QColor 已在 L29 导入

### 变更 3: 删光集合跳转逻辑
- `_on_delete_slice` (L1216-1256): 删光后 `self.label_list.setCurrentRow(0)` → 跳到第一个
- `_delete_selected` (L1388-1428): 同样 `setCurrentRow(0)` → 跳到第一个
- 问题: 用户要求跳转到原集合向下数的下一个,若已是最后一个则回上一个

### 变更 4: 默认选中第一个切片
- `_update_slice_display` (L804-817): 渲染页面后不选中任何切片,不显示原图预览
- 调用方: `_on_label_selected`、`_on_next_step`、`_on_prev_step`、`_on_delete_slice`、`_delete_selected`、`_on_jump_char`(间接)
- 问题: 用户要求进入集合时直接默认选中第一个切片并显示预览

## Proposed Changes

### 变更 1: 手柄容差改为非对称

**文件**: `vertical_check_window.py` L72-113
**方法**: `_hit_red_rect_handle`
**改动**:
- `margin = 6` → `margin_out = 3`(框外容差,防误点) + `margin_in = 12`(框内容差,更易点中) + `margin_mid = 6`(边中点平行方向容差)
- 4 角: 两个方向均用非对称区间
  - tl: `(-margin_out <= x-left <= margin_in) and (-margin_out <= y-top <= margin_in)`
  - tr: `(-margin_in <= x-right <= margin_out) and (-margin_out <= y-top <= margin_in)`
  - bl: `(-margin_out <= x-left <= margin_in) and (-margin_in <= y-bottom <= margin_out)`
  - br: `(-margin_in <= x-right <= margin_out) and (-margin_in <= y-bottom <= margin_out)`
- 4 边中点: 垂直方向非对称,水平方向对称
  - t: `(-margin_out <= y-top <= margin_in) and abs(x-mid_x) <= margin_mid`
  - b: `(-margin_in <= y-bottom <= margin_out) and abs(x-mid_x) <= margin_mid`
  - l: `(-margin_out <= x-left <= margin_in) and abs(y-mid_y) <= margin_mid`
  - r: `(-margin_in <= x-right <= margin_out) and abs(y-mid_y) <= margin_mid`

**原理**: left/top 边的外侧为负方向,内侧为正方向;right/bottom 边相反。框内 12px 比框外 3px 更容易命中手柄。

### 变更 2: 已检查集合标记

**子变更 2.1** — `__init__` (L568 附近)
- 新增: `self._checked_chars = set()`

**子变更 2.2** — `_on_next_step` (L1258-1296)
- 在 `_commit_pending_red_box_resize()` 之后、切换逻辑之前:
  ```python
  if self._current_char_text:
      self._checked_chars.add(self._current_char_text)
  ```
- 注意: 仅在非最后一项(即切换到下一个)时添加。最后一项(发射 finished_signal)也添加,因为原集合已完成检查。

**子变更 2.3** — `_refresh_label_list` (L1298-1315)
- 在 `item.setData(Qt.UserRole, char_text)` 之后:
  ```python
  if char_text in self._checked_chars:
      item.setBackground(QBrush(QColor("#b3d9ff")))
  ```

**QSS 交互验证** (context7 确认):
- `QListWidget::item`(无 background-color)不覆盖 `setBackground()` → 未选中时显示浅蓝
- `QListWidget::item:selected`(#316ac5)覆盖 → 选中时显示深蓝
- `QListWidget::item:hover`(#e8e4dc)覆盖 → 悬停时显示浅灰(临时)

### 变更 3: 删光集合跳转下一个

**文件**: `_on_delete_slice` (L1216-1256) 和 `_delete_selected` (L1388-1428)

**`_on_delete_slice` 改动**:
- L1220 后(capture original_row): `original_row = self.label_list.currentRow()`
- L1248-1252(集合已删除分支):
  ```python
  elif self.label_list.count() > 0:
      target_row = min(original_row, self.label_list.count() - 1)
      self.label_list.setCurrentRow(target_row)
      current_item = self.label_list.currentItem()
      if current_item:
          self._update_slice_display(current_item.data(Qt.UserRole))
  ```

**`_delete_selected` 改动**:
- L1393 后(capture original_row): `original_row = self.label_list.currentRow()`
- L1422-1426(集合已删除分支): 同上 `target_row = min(original_row, count-1)`

**原理**: 删除前记录 `original_row`。删除后列表缩短一项,`original_row` 位置上的新 item 即为原集合的下一个(若原非最后)。若原为最后一项,`min(original_row, count-1)` 自动回退到上一项。

**已知限制**: `_refresh_label_list` 内部 `setCurrentRow(0)` (L1314) 会触发一次 `_on_label_selected(row 0)`,之后被 `blockSignals` + 手动 `setCurrentRow(target_row)` + `_update_slice_display` 覆盖。最终状态正确,但有一次冗余调用。此为既有行为,不在本次修复范围。

### 变更 4: 默认选中第一个切片

**文件**: `_update_slice_display` (L804-817)
**改动**: 在 `self._update_nav_button_texts()` 之后追加:
```python
# 默认选中第一个切片并显示原图预览
slices = self.char_slices.get(char_text, [])
if slices:
    first_idx = self._current_page * self._current_page_size
    if 0 <= first_idx < len(slices):
        self._selected_indices = {first_idx}
        self._last_clicked_index = first_idx
        self._refresh_slice_selection_visuals()
        self._preview_slice(first_idx)
```

**安全性分析**:
- `_preview_slice` 调用 `_commit_pending_red_box_resize()`,但调用方已将 `_current_preview_index = None`,该方法在 `None` 时直接 return → 无副作用
- `_preview_slice` → `_show_line_preview` → `set_scene_pixmap` 重建场景,正常流程
- 覆盖所有进入集合的入口: `_on_label_selected`、`_on_next_step`、`_on_prev_step`、`_on_delete_slice`、`_delete_selected`、`_on_jump_char`(间接通过 currentItemChanged)

## Assumptions & Decisions

1. **手柄容差数值**: margin_out=3, margin_in=12, margin_mid=6。框内 12px 足够让用户轻松点中手柄,框外 3px 防止误点。角优先于边,角区域重叠时按 tl→tr→bl→br 顺序处理。
2. **已检查标记永久性**: `_checked_chars` 只增不减。即使集合被删除后重建(同字符),仍显示为已检查。符合用户"永久性"要求。
3. **已检查标记触发时机**: 仅 `_on_next_step` 标记。`_on_prev_step` 和 `_on_jump_char` 不标记(用户明确说"点击下一步时")。
4. **删除跳转的 original_row**: 在删除前从 `label_list.currentRow()` 获取,此时列表尚未重建,行号准确。
5. **默认选中第一个切片**: 对所有 `_update_slice_display` 调用生效,包括删除后留在同一集合的情况。用户说"无论何种方式进入一个集合时"。
6. **浅蓝色值**: `#b3d9ff`(淡蓝),与选中色 `#316ac5`(深蓝)有明显区分。
7. **所有 Edit 串行执行**: 同一文件的多个 Edit 不并行,避免竞争条件。

## Verification Steps

1. `python -m py_compile ui\vertical_check_window.py` — 语法验证
2. Grep 确认:
   - `margin_out` / `margin_in` / `margin_mid` 出现在 `_hit_red_rect_handle`
   - `_checked_chars` 出现在 `__init__`、`_on_next_step`、`_refresh_label_list`
   - `original_row` 出现在 `_on_delete_slice` 和 `_delete_selected`
   - `min(original_row` 出现在两个删除方法
   - 默认选中逻辑出现在 `_update_slice_display` 末尾
3. context7 复查 PyQt5 `QListWidgetItem.setBackground` / `QBrush` / `QColor` API 使用正确
4. 通读修改后代码确认:
   - 手柄判定逻辑符号正确(left/top 外侧为负,right/bottom 外侧为正)
   - `_checked_chars` 在 `_on_next_step` 的添加位置在 commit 之后、切换之前
   - `original_row` 在删除前捕获
   - 默认选中不触发无限递归(`_preview_slice` → `_commit_pending_red_box_resize` 在 `_current_preview_index is None` 时直接 return)
