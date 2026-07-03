# 默认"适合高度"显示 + 窗口最大化时自动适配

## 问题分析

当前三个PDF显示窗口（软件1的DrawBoxWindow、软件2的HorizontalCheckWindow和RefineWindow）存在两个问题：

1. **首次加载默认"适合宽度"**：三个窗口的 `_first_render` 逻辑都调用 `_on_fit_width`，用户要求改为"适合高度"
2. **窗口最大化后不自动适配**：三个窗口都没有重写 `resizeEvent`，最大化后PDF不会自动重新适配

## 修改方案

### 修改1：首次加载改为"适合高度"

三个文件中，将 `_first_render` 触发的 `_on_fit_width` 改为 `_on_fit_height`：

| 文件 | 行号 | 当前代码 | 修改为 |
|------|------|----------|--------|
| `软件1/ui/draw_box_window.py` | ~516 | `QTimer.singleShot(100, self._on_fit_width)` | `QTimer.singleShot(100, self._on_fit_height)` |
| `软件2/ui/horizontal_check_window.py` | ~326 | `QTimer.singleShot(100, self._on_fit_width)` | `QTimer.singleShot(100, self._on_fit_height)` |
| `软件2/ui/refine_window.py` | ~791 | `QTimer.singleShot(100, self._on_fit_width)` | `QTimer.singleShot(100, self._on_fit_height)` |

### 修改2：窗口最大化时触发"适合高度"

在三个窗口中添加 `resizeEvent` 方法，检测窗口状态变化（特别是最大化），自动触发适合高度。

实现逻辑：
- 重写 `resizeEvent` 方法
- 检测 `windowState()` 是否包含 `Qt.WindowState.WindowMaximized`
- 如果是最大化状态，调用 `_on_fit_height()`
- 避免重复触发：记录上一次是否为最大化状态，只在状态变化时触发

具体代码（以DrawBoxWindow为例，其他两个窗口类似）：

```python
def resizeEvent(self, event):
    super().resizeEvent(event)
    is_maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized)
    if is_maximized and not getattr(self, '_was_maximized', False):
        if self._lazy_loader is not None:
            QTimer.singleShot(50, self._on_fit_height)
    self._was_maximized = is_maximized
```

注意：
- DrawBoxWindow 用 `self._lazy_loader is not None` 判断是否已加载PDF
- HorizontalCheckWindow 和 RefineWindow 用 `self.page_images` 判断
- RefineWindow 的 `_on_fit_height` 内部已有 `_sync_current_page()` 调用，无需额外处理
- 使用 `QTimer.singleShot(50, ...)` 延迟触发，确保窗口尺寸已更新完毕

### 需要修改的文件清单

1. `软件1/ui/draw_box_window.py`
   - 修改 `_first_render` 触发：`_on_fit_width` → `_on_fit_height`
   - 添加 `resizeEvent` 方法
   - 添加 `_was_maximized` 属性初始化

2. `软件2/ui/horizontal_check_window.py`
   - 修改 `_first_render` 触发：`_on_fit_width` → `_on_fit_height`
   - 添加 `resizeEvent` 方法
   - 添加 `_was_maximized` 属性初始化

3. `软件2/ui/refine_window.py`
   - 修改 `_first_render` 触发：`_on_fit_width` → `_on_fit_height`
   - 添加 `resizeEvent` 方法
   - 添加 `_was_maximized` 属性初始化

## 验证步骤

1. 运行软件1，导入PDF，确认首次显示为"适合高度"（PDF顶天立地）
2. 点击窗口最大化按钮，确认PDF自动适配为"适合高度"
3. 运行软件2，导入数据进入横校，确认首次显示为"适合高度"
4. 横校窗口最大化，确认自动适配
5. 进入精修，确认首次显示为"适合高度"
6. 精修窗口最大化，确认自动适配
