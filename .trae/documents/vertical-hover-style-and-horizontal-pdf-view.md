# 实施计划：纵校条目悬停样式 + 横校原PDF展示区

## 概述

两个任务：
1. 修复纵校界面左侧文字条目选中后鼠标悬停的样式问题
2. 横校界面右侧新增原PDF展示区域，悬停文字时在原PDF上画框

---

## 任务1：纵校条目悬停样式

### 当前状态

[vertical_check_window.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/ui/vertical_check_window.py#L178) 第178-183行：

```python
self.label_list.setStyleSheet(
    "QListWidget { font-size: 20px; }"
    "QListWidget::item { padding: 8px 12px; min-height: 36px; }"
    "QListWidget::item:selected { background-color: #0D6EFD; color: white; }"
    "QListWidget::item:hover { background-color: #e7f1ff; }"
)
```

问题：选中条目（深蓝底白字）鼠标悬停时，`::item:hover` 生效但只改了背景色没改文字色，导致浅蓝底+白字不可读。

### 修改方案

添加 `::item:selected:hover` 伪状态：

```python
self.label_list.setStyleSheet(
    "QListWidget { font-size: 20px; }"
    "QListWidget::item { padding: 8px 12px; min-height: 36px; }"
    "QListWidget::item:selected { background-color: #0D6EFD; color: white; }"
    "QListWidget::item:hover { background-color: #e7f1ff; color: black; }"
    "QListWidget::item:selected:hover { background-color: #e7f1ff; color: black; }"
)
```

---

## 任务2：横校原PDF展示区 + 悬停画框

### 当前状态

[horizontal_check_window.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/ui/horizontal_check_window.py) 当前布局：
- 顶部工具栏
- 中间单个 QGraphicsView（文字叠加视图）
- 底部完成按钮

用户需求：
- 保留当前左侧文字视图和悬停切片功能
- 右侧新增原PDF图像展示区域
- 两侧页数同步，翻页一起翻
- 鼠标悬停左侧文字时，右侧原PDF上在对应bbox位置画蓝色框
- 框样式与画框界面同款：蓝色2px边框，透明填充
- 鼠标移到别的文字时，旧框消失，新框出现

### 修改方案

#### 修改1：添加导入

```python
from PyQt6.QtWidgets import (
    ..., QGraphicsRectItem, ...
)
from PyQt6.QtGui import ..., QPen, QBrush
```

#### 修改2：添加实例变量

在 `__init__` 中添加：
- `self.pdf_scene` — 右侧原PDF场景
- `self.pdf_view` — 右侧原PDF视图
- `self._hover_rect_item` — 右侧场景中的蓝色框图元

#### 修改3：修改 `_init_ui` 布局

将单个 view 替换为 QHBoxLayout 包含两个 view：

```
原布局:
  toolbar
  self.view (stretch=1)
  bottom_layout

新布局:
  toolbar
  views_layout (QHBoxLayout)
    self.view (stretch=1) — 文字视图
    self.pdf_view (stretch=1) — 原PDF视图
  bottom_layout
```

右侧视图配置：
- 与左侧相同的渲染设置（抗锯齿等）
- 不需要文字交互，只显示图像和蓝色框
- 支持鼠标滚轮滚动浏览

#### 修改4：修改 `_render_page`

在渲染左侧场景后，也渲染右侧场景：

```python
# 渲染右侧原PDF场景
self.pdf_scene.clear()
self._hover_rect_item = None

if self.page_images and self.current_page < len(self.page_images):
    img = self.page_images[self.current_page]
    cache_key = (self.current_page, self.zoom_level, 'pdf')
    if cache_key not in self._pixmap_cache:
        pixmap = self._pil_to_pixmap(img)
        scaled_pixmap = pixmap.scaled(
            int(img.width * self.zoom_level),
            int(img.height * self.zoom_level),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._pixmap_cache[cache_key] = scaled_pixmap
    bg_item = QGraphicsPixmapItem(self._pixmap_cache[cache_key])
    self.pdf_scene.addItem(bg_item)
    w = img.width * self.zoom_level
    h = img.height * self.zoom_level
    self.pdf_scene.setSceneRect(QRectF(0, 0, w, h))
```

#### 修改5：修改 `eventFilter` 悬停逻辑

在鼠标悬停到文字时，在右侧场景添加蓝色框：

```python
# 移除旧框
if self._hover_rect_item is not None:
    self.pdf_scene.removeItem(self._hover_rect_item)
    self._hover_rect_item = None

# 添加新框
bbox = ls.bbox
rect = QRectF(
    bbox[0] * self.zoom_level,
    bbox[1] * self.zoom_level,
    (bbox[2] - bbox[0]) * self.zoom_level,
    (bbox[3] - bbox[1]) * self.zoom_level,
)
pen = QPen(Qt.GlobalColor.blue, 2)
brush = QBrush(Qt.GlobalColor.transparent)
rect_item = QGraphicsRectItem(rect)
rect_item.setPen(pen)
rect_item.setBrush(brush)
rect_item.setZValue(10)
self.pdf_scene.addItem(rect_item)
self._hover_rect_item = rect_item
```

#### 修改6：修改 `_remove_hover_pixmap`

同时移除右侧蓝色框：

```python
def _remove_hover_pixmap(self):
    if self._hover_pixmap_item is not None:
        self.scene.removeItem(self._hover_pixmap_item)
        self._hover_pixmap_item = None
    if self._hover_rect_item is not None:
        self.pdf_scene.removeItem(self._hover_rect_item)
        self._hover_rect_item = None
```

---

## 验证步骤

1. 运行应用，进入纵校阶段，选中一个条目后鼠标悬停，确认显示浅蓝底黑字
2. 进入横校阶段，确认左右两个视图并排显示
3. 翻页时两侧同步翻页
4. 鼠标悬停左侧文字时，右侧原PDF上出现蓝色框，框位置与文字bbox对应
5. 鼠标移到另一行文字时，旧框消失，新框出现在正确位置
6. 鼠标移开文字区域时，框消失
