# 修复切片展示区域排列逻辑 - 从左上角开始排列

## 问题分析

当前切片展示区域使用 `QGridLayout` 直接放在 `scroll_content` 上，配合 `QScrollArea.setWidgetResizable(True)` 时，`scroll_content` 会扩展至填满整个视口区域。当切片数量较少（不足以填满整个区域）时，`QGridLayout` 默认将内容居中显示，导致切片从展示区域中央开始排列，而非从左上角开始。

## 修改方案

修改 `ui/horizontal_check_window.py` 中的 `_init_ui` 方法，将 `scroll_content` 的布局改为 `QVBoxLayout`（设置 `AlignTop | AlignLeft`），在其中嵌套一个 `grid_container` Widget 使用 `QGridLayout`，这样网格内容始终从左上角开始排列。

### 具体修改

**文件**: `ui/horizontal_check_window.py`

**修改 `_init_ui` 方法中第 116-118 行**：

当前代码：
```python
self.scroll_content = QWidget()
self.grid_layout = QGridLayout(self.scroll_content)
self.grid_layout.setSpacing(8)
```

改为：
```python
self.scroll_content = QWidget()
scroll_vlayout = QVBoxLayout(self.scroll_content)
scroll_vlayout.setContentsMargins(0, 0, 0, 0)
scroll_vlayout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
self.grid_container = QWidget()
self.grid_layout = QGridLayout(self.grid_container)
self.grid_layout.setSpacing(8)
scroll_vlayout.addWidget(self.grid_container)
```

**核心原理**：`QVBoxLayout` 设置 `AlignTop | AlignLeft` 后，内部的 `grid_container` 会被推到左上角，不会因为 `scroll_content` 被拉伸而居中。

## 验证方式

运行程序后，选择一个只有少量切片的字符（如只有 2 张图），确认切片从展示区域左上角开始从左至右排列，而非居中显示。
