# PDF阅读窗口Ctrl+滚轮缩放功能实施计划

## 概述

为所有包含PDF阅读窗口的组件（DrawBoxWindow、RefineWindow、VerticalCheckWindow）实现Ctrl+鼠标滚轮缩放功能，统一缩放行为和参数。

## 涉及窗口

| 窗口 | 缩放变量 | 缩放标签 | eventFilter已有功能 |
|------|---------|---------|-------------------|
| DrawBoxWindow | `_zoom` | 无 | 鼠标绘制矩形框 |
| RefineWindow | `zoom_level` | 有(`zoom_label`) | 拖拽模式点击检测 |
| VerticalCheckWindow | `zoom_level` | 有(`zoom_label`) | 鼠标悬停预览 |

## 实施步骤

### 步骤1：创建共享缩放工具模块 `ui/zoom_utils.py`

新建 `ui/zoom_utils.py`，定义统一的缩放常量和辅助函数：

- `ZOOM_MIN = 0.25` — 最小缩放级别
- `ZOOM_MAX = 5.0` — 最大缩放级别
- `ZOOM_STEP_BUTTON = 0.25` — 按钮点击缩放步长
- `ZOOM_STEP_WHEEL = 0.1` — Ctrl+滚轮缩放步长
- `calculate_wheel_zoom(event, current_zoom)` 函数：
  - 检查事件是否为 `QWheelEvent` 实例
  - 检查是否按住 Ctrl 键（`event.modifiers() & Qt.KeyboardModifier.ControlModifier`）
  - 根据滚轮方向（`event.angleDelta().y()`）计算新缩放值
  - 正值（向上滚）→ 放大，负值（向下滚）→ 缩小
  - 将结果限制在 `[ZOOM_MIN, ZOOM_MAX]` 范围内
  - 返回新缩放值；若非Ctrl+滚轮事件则返回 `None`
  - 包含异常处理：捕获可能的属性访问异常，返回 `None`

### 步骤2：修改 `DrawBoxWindow`（`ui/draw_box_window.py`）

1. **新增导入**：在文件顶部导入 `QWheelEvent` 和 `zoom_utils` 中的常量与函数
2. **添加缩放标签**：在 `_init_ui` 的工具栏中，在"放大"和"缩小"按钮之间添加 `QLabel` 显示当前缩放百分比（如"100%"）
3. **修改 `eventFilter`**：在现有鼠标事件处理之前，添加滚轮事件检测：
   - 调用 `calculate_wheel_zoom(event, self._zoom)`
   - 若返回有效值，更新 `self._zoom` 并调用 `self._render_page()`
   - 返回 `True` 拦截事件，防止默认滚动行为
4. **修改 `_on_zoom_in`**：添加 `ZOOM_MAX` 上限检查
5. **修改 `_on_zoom_out`**：使用 `ZOOM_MIN` 替代硬编码的 `0.25`
6. **修改 `_render_page`**：在更新 `page_label` 后，同步更新缩放标签文本

### 步骤3：修改 `RefineWindow`（`ui/refine_window.py`）

1. **新增导入**：在文件顶部导入 `QWheelEvent` 和 `zoom_utils` 中的常量与函数
2. **修改 `eventFilter`**：在现有鼠标按下事件处理之前，添加滚轮事件检测：
   - 调用 `calculate_wheel_zoom(event, self.zoom_level)`
   - 若返回有效值，先调用 `self._sync_current_page()` 同步数据，再更新 `self.zoom_level` 并调用 `self._render_page()`
   - 返回 `True` 拦截事件
3. **修改 `_on_zoom_in`**：添加 `ZOOM_MAX` 上限检查
4. **修改 `_on_zoom_out`**：使用 `ZOOM_MIN` 替代硬编码的 `0.25`

### 步骤4：修改 `VerticalCheckWindow`（`ui/vertical_check_window.py`）

1. **新增导入**：导入 `zoom_utils` 中的常量与函数（`QWheelEvent` 已导入）
2. **修改 `eventFilter`**：在现有鼠标移动事件处理之前，添加滚轮事件检测：
   - 调用 `calculate_wheel_zoom(event, self.zoom_level)`
   - 若返回有效值，更新 `self.zoom_level` 并调用 `self._render_page()`
   - 返回 `True` 拦截事件
3. **修改 `_on_zoom_in`**：添加 `ZOOM_MAX` 上限检查
4. **修改 `_on_zoom_out`**：使用 `ZOOM_MIN` 替代硬编码的 `0.25`

## 技术要点

### 1. 准确捕获Ctrl+滚轮组合事件
- 在 `eventFilter` 中检测 `isinstance(event, QWheelEvent)`
- 通过 `event.modifiers() & Qt.KeyboardModifier.ControlModifier` 判断Ctrl键
- 通过 `event.angleDelta().y()` 判断滚轮方向（正=上=放大，负=下=缩小）

### 2. 统一实现
- 所有PDF窗口共享 `zoom_utils.py` 中的常量和计算逻辑
- 缩放步长、范围限制完全一致
- 行为模式统一：Ctrl+上滚放大，Ctrl+下滚缩小

### 3. 缩放比例和范围
- 滚轮步长：0.1（比按钮的0.25更精细，体验更流畅）
- 最小缩放：0.25（25%）
- 最大缩放：5.0（500%）
- 按钮步长保持0.25不变

### 4. 流畅性保障
- 滚轮步长0.1比按钮步长0.25更小，缩放过渡更平滑
- 复用现有的 `_render_page()` 渲染逻辑，无需额外优化
- 拦截事件返回 `True`，防止默认滚动行为干扰

### 5. 异常处理
- `calculate_wheel_zoom` 内部捕获属性访问异常
- 缩放值强制限制在 `[ZOOM_MIN, ZOOM_MAX]` 范围
- 无效事件返回 `None`，不触发任何操作

### 6. 缩放状态实时反馈
- DrawBoxWindow 新增缩放百分比标签
- RefineWindow 和 VerticalCheckWindow 已有 `zoom_label`，在 `_render_page` 中自动更新
- 每次缩放操作后通过 `_render_page()` 刷新界面，标签同步更新

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `ui/zoom_utils.py` | 新建 | 共享缩放常量和辅助函数 |
| `ui/draw_box_window.py` | 修改 | 添加Ctrl+滚轮缩放、缩放标签、范围限制 |
| `ui/refine_window.py` | 修改 | 添加Ctrl+滚轮缩放、范围限制 |
| `ui/vertical_check_window.py` | 修改 | 添加Ctrl+滚轮缩放、范围限制 |
