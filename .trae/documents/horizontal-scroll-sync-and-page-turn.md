# 实施计划：横校左右视图滚动联动 + 右侧翻页

## 概述

在横校界面的左右两个PDF视图之间添加滚动联动机制，并在右侧原PDF视图添加翻页功能。

---

## 当前状态

[horizontal_check_window.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/ui/horizontal_check_window.py) 中：
- 左侧 `self.view` 有 eventFilter 处理缩放、翻页、悬停
- 右侧 `self.pdf_view` 无 eventFilter，无滚动联动
- 两个视图共享 `current_page`、`zoom_level`、`_render_page()`

---

## 修改方案

### 修改1：安装右侧视图的事件过滤器

在 `_init_ui` 中，`self.pdf_view` 创建后添加：

```python
self.pdf_view.viewport().installEventFilter(self)
```

### 修改2：扩展 eventFilter 处理右侧视图翻页

在 eventFilter 中，现有逻辑处理 `obj is self.view.viewport()`。添加 `elif obj is self.pdf_view.viewport():` 分支，处理右侧视图的滚轮翻页：

```python
elif obj is self.pdf_view.viewport():
    if isinstance(event, QWheelEvent):
        v_bar = self.pdf_view.verticalScrollBar()
        delta = event.angleDelta().y()
        if delta > 0 and v_bar.value() == v_bar.minimum():
            if self.current_page > 0:
                self.current_page -= 1
                self._render_page()
                QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                    self.view.verticalScrollBar().maximum()))
                QTimer.singleShot(0, lambda: self.pdf_view.verticalScrollBar().setValue(
                    self.pdf_view.verticalScrollBar().maximum()))
            return True
        elif delta < 0 and v_bar.value() == v_bar.maximum():
            if self.current_page < self.total_pages - 1:
                self.current_page += 1
                self._render_page()
                QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                    self.view.verticalScrollBar().minimum()))
                QTimer.singleShot(0, lambda: self.pdf_view.verticalScrollBar().setValue(
                    self.pdf_view.verticalScrollBar().minimum()))
            return True
return False
```

### 修改3：添加滚动条联动

在 `_init_ui` 中，两个视图创建后连接滚动条信号：

```python
# 滚动条联动
self.view.verticalScrollBar().valueChanged.connect(self._on_left_v_scroll)
self.view.horizontalScrollBar().valueChanged.connect(self._on_left_h_scroll)
self.pdf_view.verticalScrollBar().valueChanged.connect(self._on_right_v_scroll)
self.pdf_view.horizontalScrollBar().valueChanged.connect(self._on_right_h_scroll)
```

添加4个联动方法：

```python
def _on_left_v_scroll(self, value):
    self.pdf_view.verticalScrollBar().blockSignals(True)
    self.pdf_view.verticalScrollBar().setValue(value)
    self.pdf_view.verticalScrollBar().blockSignals(False)

def _on_left_h_scroll(self, value):
    self.pdf_view.horizontalScrollBar().blockSignals(True)
    self.pdf_view.horizontalScrollBar().setValue(value)
    self.pdf_view.horizontalScrollBar().blockSignals(False)

def _on_right_v_scroll(self, value):
    self.view.verticalScrollBar().blockSignals(True)
    self.view.verticalScrollBar().setValue(value)
    self.view.verticalScrollBar().blockSignals(False)

def _on_right_h_scroll(self, value):
    self.view.horizontalScrollBar().blockSignals(True)
    self.view.horizontalScrollBar().setValue(value)
    self.view.horizontalScrollBar().blockSignals(False)
```

使用 `blockSignals(True/False)` 防止信号循环触发。

---

## 验证步骤

1. 运行应用，进入横校阶段
2. 滚动左侧视图，右侧视图同步滚动
3. 滚动右侧视图，左侧视图同步滚动
4. 右侧视图滚到底部，继续下滚触发翻到下一页
5. 右侧视图滚到顶部，继续上滚触发翻到上一页
6. 左侧视图翻页功能不受影响
