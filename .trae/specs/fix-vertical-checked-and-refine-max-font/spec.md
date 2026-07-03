# 纵校已检查标记修复与精修拖拽字号优化 Spec

## Why
纵校"已检查"浅蓝标记功能未生效：`_on_next_step` 标记 `_checked_chars` 后依赖 `_flush_pending_modifications` 间接刷新列表，但无挂起修改时不会调用 `_refresh_label_list`，导致背景色从未应用。精修 `MovableTextItem` 拖拽缩放后字号仅取框高 `new_h`，未校验字符宽度溢出，无法实现"框内能容纳的最大字体"。

## What Changes
- 修复纵校已检查标记：`_on_next_step` 标记 `_checked_chars` 后立即更新当前行 item 的 `setBackground` 为浅蓝 `#b3d9ff`，不依赖列表重建
- 精修字号优化：`MovableTextItem` 新增 `_calculate_max_font_size(text, frame_w, frame_h)` 方法，以框高为候选字号，用 `QFontMetrics` 测量字符宽高，超出框宽/框高时按比例缩小，最小 1px
- `mouseMoveEvent` 和 `update_zoom` 中的字号设置替换为调用新方法

## Impact
- Affected specs: enhance-vertical-check-nav-and-preview（已检查标记修复）, add-refine-stage-and-fix-tooltip（精修字号优化）
- Affected code:
  - `d:\hx\software2\ui\vertical_check_window.py`：`_on_next_step` 方法（L1288-1289 附近）
  - `d:\hx\software2\ui\refine_window.py`：`MovableTextItem` 类（新增方法 + 修改 `mouseMoveEvent` L333-335、`update_zoom` L512-513）

## ADDED Requirements

### Requirement: 纵校已检查标记即时生效
系统 SHALL 在用户点击"下一步"标记当前集合为"已检查"后，立即将该集合在字符列表中的对应条目背景色设为浅蓝 `#b3d9ff`，无需等待列表重建。

#### Scenario: 无修改点击下一步
- **WHEN** 用户未修改任何切片字符即点击"下一步"
- **THEN** 当前集合被加入 `_checked_chars`，当前行 item 立即显示浅蓝底色

#### Scenario: 有修改点击下一步
- **WHEN** 用户修改了切片字符后点击"下一步"，`_flush_pending_modifications` 触发 `_refresh_label_list`
- **THEN** 列表重建时浅蓝底色通过 `_refresh_label_list` 中的逻辑应用（原逻辑保留），即时更新逻辑也执行（双重保证）

### Requirement: 精修拖拽字号为框内最大字体
系统 SHALL 在 `MovableTextItem` 拖拽缩放时，计算框内能容纳的最大字体大小，使字符既不超出框宽也不超出框高。

#### Scenario: 横排框（宽>高）
- **WHEN** 用户将框拖拽为宽矩形（宽 > 高）
- **THEN** 字号以框高为候选，若字符宽度超出框宽则按比例缩小字号

#### Scenario: 竖排框（高>宽）
- **WHEN** 用户将框拖拽为高矩形（高 > 宽）
- **THEN** 字号以框高为候选，若字符宽度超出框宽则按比例缩小字号

#### Scenario: 字号下限保护
- **WHEN** 计算出的字号小于 1 像素
- **THEN** 使用 1 像素作为最小字号

#### Scenario: 缩放变更
- **WHEN** 页面缩放级别变化时 `update_zoom` 被调用
- **THEN** 文字项的字号同样使用最大字体算法重新计算

## MODIFIED Requirements

### Requirement: 纵校"下一步"按钮处理
`_on_next_step` 方法在标记 `_checked_chars` 后，SHALL 立即更新当前行 item 的背景色为浅蓝 `#b3d9ff`，而非仅依赖后续的 `_refresh_label_list` 调用。

### Requirement: MovableTextItem 字号计算
`MovableTextItem.mouseMoveEvent` 和 `MovableTextItem.update_zoom` 中的字号计算 SHALL 从仅取框高改为调用 `_calculate_max_font_size` 方法，综合考虑框宽和框高约束。

## Assumptions & Decisions

1. **即时更新策略**：在 `_on_next_step` 的 `self._checked_chars.add(...)` 之后、`_flush_pending_modifications()` 之前，直接获取 `self.label_list.currentRow()` 对应 item 并设置 `setBackground`。此时 current_row 仍指向被标记的项，flush 可能改变列表但已设置的颜色会随 item 保留或随重建应用。
2. **字号算法**：候选字号 = `int(frame_h)`（框高，场景像素）。用 `QFontMetrics.horizontalAdvance(text)` 测量字符宽度，`ascent() + descent()` 测量字符高度。若超出框宽则 `candidate = int(candidate * frame_w / char_w)`，若超出框高则 `candidate = int(candidate * frame_h / char_h)`，最小 1px。
3. **不修改 `_sync_current_page`**：该方法（L794-817）在翻页/缩放/输出前同步 bbox 到数据模型，已正常工作。字号优化仅影响视觉显示，不影响数据同步。
4. **不修改 QSS**：`QListWidget::item:selected` 的 `#316ac5` 覆盖 `setBackground` 是设计行为（选中=深蓝，未选中=浅蓝），非 bug。
5. **不修改拖拽激活流程**：当前"拖拽"按钮 → `_on_drag_toggle` → `activate()` 的流程不变，用户需先切换到拖拽模式才能交互。
6. **`QFontMetrics` 已 import**：`refine_window.py` L22 已 `from PyQt5.QtGui import ... QFontMetrics ...`，无需新增 import。
7. **`QBrush`/`QColor` 已 import**：`vertical_check_window.py` 已使用 `QBrush(QColor("#b3d9ff"))`（L1332），无需新增 import。
