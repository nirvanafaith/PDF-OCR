# 滚轮翻页 + interline_equation 导入

## 任务1：滚轮翻页

### 问题
当前画框窗口中，滚轮只能滚动当前页面，到达页面顶部/底部后无法继续翻页，必须点击"上一页/下一页"按钮。

### 当前行为
- Ctrl+滚轮：缩放（由 `calculate_wheel_zoom` 处理）
- 普通滚轮：QGraphicsView 默认滚动（由 eventFilter 返回 False 放行）

### 修改方案

在 `eventFilter` 中拦截 `QWheelEvent`，当 `calculate_wheel_zoom` 返回 None 时（普通滚轮），检测翻页条件：

1. 获取垂直滚动条 `v_bar = self.view.verticalScrollBar()`
2. 向上滚动（`angleDelta().y() > 0`）且滚动条已在顶部（`v_bar.value() == v_bar.minimum()`）→ 翻到上一页，滚动条设到底部
3. 向下滚动（`angleDelta().y() < 0`）且滚动条已在底部（`v_bar.value() == v_bar.maximum()`）→ 翻到下一页，滚动条设到顶部
4. 其他情况：让默认滚动处理执行（返回 False）

关键代码位置：`draw_box_window.py` 第332-336行

```python
# 当前代码
new_zoom = calculate_wheel_zoom(event, self._zoom)
if new_zoom is not None:
    self._zoom = new_zoom
    self._render_page()
    return True
```

修改为：

```python
new_zoom = calculate_wheel_zoom(event, self._zoom)
if new_zoom is not None:
    self._zoom = new_zoom
    self._render_page()
    return True

if isinstance(event, QWheelEvent):
    v_bar = self.view.verticalScrollBar()
    delta = event.angleDelta().y()
    if delta > 0 and v_bar.value() == v_bar.minimum():
        if self.current_page > 0:
            self.current_page -= 1
            self._render_page()
            QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                self.view.verticalScrollBar().maximum()))
        return True
    elif delta < 0 and v_bar.value() == v_bar.maximum():
        if self.current_page < self._page_count - 1:
            self.current_page += 1
            self._render_page()
            QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                self.view.verticalScrollBar().minimum()))
        return True

return False
```

注意：翻页后用 `QTimer.singleShot(0, ...)` 延迟设置滚动条位置，因为 `_render_page` 后滚动条还未更新。

## 任务2：导入 interline_equation 框

### 问题
当前 `TEXT_BLOCK_TYPES = {"text", "title"}`，遗漏了 `interline_equation` 类型。

### JSON结构
```json
{
    "bbox": [171, 440, 225, 450],
    "type": "interline_equation",
    "lines": [{"bbox": [...], "spans": [{"type": "interline_equation", "content": "...", "image_path": "..."}]}]
}
```

interline_equation 是顶层 para_block，有独立的 bbox，和 text/title 结构相同。

### 修改方案
将 `TEXT_BLOCK_TYPES` 从 `{"text", "title"}` 改为 `{"text", "title", "interline_equation"}`。

修改位置：`draw_box_window.py` 第46行

```python
TEXT_BLOCK_TYPES = {"text", "title", "interline_equation"}
```

### 影响统计
财务理论与实务JSON中有305个 interline_equation 块，修改后将被正确导入。

## 验证计划
1. 启动应用，加载PDF，测试滚轮翻页功能
2. 导入JSON，确认 interline_equation 框被正确显示
3. 确认手动绘制框与导入框共存正常
