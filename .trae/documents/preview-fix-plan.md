# 纵校原图预览区增强技术报告

## 任务概述

本次任务针对软件 2 纵校阶段顶部"原图预览"区域存在的 4 个问题进行全面修正与增强：

1. **修复宽度异常 bug**：切换字符列表时，原图预览区域宽度会突然变大，且随着点击越来越宽。
2. **增加交互能力**：在原图预览区域内支持鼠标拖拽平移图像，并支持按住 `Ctrl` + 鼠标滚轮进行缩放。
3. **显示完整 PDF 横条**：预览区不再只显示行切片本身，而是显示该行切片所在 PDF 页面的完整横向条带，并将红框（选中字符）保持在预览区正中央。
4. **修复纵向拉伸**：部分图像会上下拉伸超出展示区域，要求初始显示时以预览区宽度为基准，保持宽高比，图像宽度与展示区域宽度相等。

## 当前问题分析

### 1. 宽度异常 bug

当前实现中 `QGraphicsView` 被放置在 `QStackedWidget` 内，仅设置了 `minimumHeight` 与 `maximumHeight`，未对宽度做任何约束。`QGraphicsView` 默认会根据 `sceneRect()` 的 size hint 向父布局请求空间。当 `fitInView()` 以 `KeepAspectRatioByExpanding` 模式调用后，`sceneRect()` 的宽度可能远大于视图可视宽度，导致 `QGraphicsView` 的 `sizeHint` 被撑大，进而使 `QStackedWidget` / `preview_group` 在水平方向上不断扩展，出现"越点越大"的现象。

### 2. 缺少交互

当前 `preview_view` 为原生 `QGraphicsView`，未重写鼠标事件与滚轮事件。用户无法拖拽平移，也无法缩放查看细节。

### 3. 只显示行切片，而非 PDF 横条

当前 `_show_line_preview` 会根据 OCR 结果中的 `line_box` 从整页图像中裁剪出整行区域进行显示。用户要求看到的是"行切片所在 PDF 那一整个横条"，即应基于整页图像渲染，但只关注包含目标行的水平条带区域，并通过红框标出选中字符。这样可以在保留页面上下文的同时突出当前字符。

### 4. 红框未居中

当前实现使用 `fitInView(pixmap_item, KeepAspectRatioByExpanding)` 后调用 `centerOn(rect_item)`。`KeepAspectRatioByExpanding` 会填满 viewport，可能导致图像在水平或垂直方向上被裁剪，红框在视觉上不一定位于 viewport 正中央。此外，当显示整页横条时，需要精确计算红框在 scene 中的位置并正确居中。

### 5. 图像上下拉伸超出区域

`KeepAspectRatioByExpanding` 会在保持比例的前提下将图像放大至完全覆盖 viewport。当行切片较矮而预览区较高时，图像会被纵向拉伸（等比放大）以填满高度，导致水平方向上超出 viewport，用户只能通过水平滚动查看。用户要求初始显示"宽度相等即可"，即以预览区宽度为基准进行等比缩放，高度自适应，若高度超出则通过滚动条查看，而不是被强制填满高度。

## 实现方案

### 修改文件

- `软件2/ui/vertical_check_window.py`

### 核心改动

#### 1. 自定义 `PreviewGraphicsView` 类

继承 `QGraphicsView`，实现：

- **鼠标拖拽平移**：
  - 在 `mousePressEvent` 中检测左键按下，记录按下时的鼠标位置与当前滚动条值，并设置拖拽光标。
  - 在 `mouseMoveEvent` 中计算鼠标偏移量，调整 `horizontalScrollBar()` 与 `verticalScrollBar()` 的值，实现图像平移。
  - 在 `mouseReleaseEvent` 中恢复光标。
- **Ctrl + 滚轮缩放**：
  - 在 `wheelEvent` 中检测 `event.modifiers() & Qt.KeyboardModifier.ControlModifier`。
  - 若按住 Ctrl，根据滚轮 `angleDelta().y()` 计算缩放因子，调用 `scale(factor, factor)` 进行以视图中心为锚点的缩放。
  - 限制最小与最大缩放倍数，避免过度缩放。
  - 未按住 Ctrl 时按默认方式处理滚轮事件（垂直滚动）。
- **初始适配方法**：
  - 提供 `fit_to_width()` 方法，在加载新图像后调用，根据 viewport 宽度与 scene 宽度计算缩放比例，使图像宽度等于 viewport 宽度，保持宽高比。

#### 2. 调整预览区布局约束

- 将 `PreviewGraphicsView` 的 `sizePolicy` 设置为：水平方向 `Expanding`，垂直方向 `Fixed`。
- 设置固定高度（如 240px），避免高度变化导致布局抖动。
- 确保 `preview_group` 与 `preview_stack` 不会根据 scene 内容请求额外宽度。可通过 `preview_view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)` 与关闭滚动条自动显示来避免尺寸抖动。
- 为 `QGraphicsView` 设置 `Qt.ScrollBarPolicy.ScrollBarAsNeeded`，允许在缩放后自然出现滚动条。

#### 3. 修改 `_show_line_preview` 渲染逻辑

- 改为基于整页 `page_image` 渲染，而不是裁剪行区域。
- 计算"横条"区域：取选中字符所在行的 `line_box` 的 `y1` 与 `y2`，并在上下各增加一定边距（如 20% 行高或固定像素），得到条带区域 `strip_box`。
- 将整页图像转换为 `QPixmap` 并添加到 scene，scene 的坐标系与页面像素坐标系一致。
- 添加红框 `QGraphicsRectItem`，坐标直接使用 `char_slice.bbox`（无需再做相对偏移）。
- 调用 `fit_to_width()` 使整页图像宽度适配预览区宽度。
- 调用 `centerOn(rect_item)` 将视图中心对准红框。
- 为增强可读性，可在红框背后添加半透明遮罩，或仅使用红色矩形边框。

#### 4. 缓存与性能

- 原有的 `_line_preview_cache` 缓存的是行切片 pixmap。改为整页渲染后，可改为按 `page_num` 缓存整页 `QPixmap`，减少重复转换。
- 红框与遮罩为临时 scene item，每次切换切片时重新创建，不缓存。

### 界面排版设计

```
+-------------------------------------------------------------+
|  纵校窗口 (VerticalCheckWindow)                              |
|  +------------------+  +----------------------------------+ |
|  |                  |  | 原图预览                          | |
|  |  字符列表         |  | +------------------------------+ | |
|  |  （左侧面板）      |  | | [整页横条，红框字符居中]      | | |
|  |                  |  | | 支持：拖拽平移 / Ctrl+滚轮缩放 | | |
|  |                  |  | +------------------------------+ | |
|  |                  |  +----------------------------------+ |
|  |                  |  | 切片展示                          | |
|  |                  |  | +------------------------------+ | |
|  |                  |  | | [ ][ ][ ][ ]                  | | |
|  |                  |  | | [低分切片浅黄色底色边框]       | | |
|  |                  |  | +------------------------------+ | |
|  |                  |  | | 翻页控件 | 下一步              | | |
|  |                  |  +----------------------------------+ |
|  +------------------+  +----------------------------------+ |
```

## 关键算法

### 1. 拖拽平移

```python
# mousePressEvent
drag_start_pos = event.pos()
h_scroll_start = horizontalScrollBar().value()
v_scroll_start = verticalScrollBar().value()

# mouseMoveEvent
delta = event.pos() - drag_start_pos
horizontalScrollBar().setValue(h_scroll_start - delta.x())
verticalScrollBar().setValue(v_scroll_start - delta.y())
```

### 2. Ctrl + 滚轮缩放

```python
if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
    delta = event.angleDelta().y()
    factor = 1.1 if delta > 0 else 0.9
    self.scale(factor, factor)
    event.accept()
else:
    super().wheelEvent(event)
```

### 3. 宽度适配

```python
def fit_to_width(self):
    scene_rect = self.scene().sceneRect()
    viewport_width = self.viewport().width()
    if scene_rect.width() <= 0 or viewport_width <= 0:
        return
    factor = viewport_width / scene_rect.width()
    self.resetTransform()
    self.scale(factor, factor)
```

### 4. 横条区域计算

```python
line_flat = flatten_bbox(line_box)
strip_top = max(0, line_flat[1] - strip_padding)
strip_bottom = min(page_height, line_flat[3] + strip_padding)
# scene 仍使用整页坐标，仅通过 centerOn 与滚动保证条带区域可见
```

## 验证步骤

1. 启动软件 2，导入 PDF 与 JSON，进入纵校界面。
2. 选择不同字符，观察原图预览区宽度是否保持稳定，不再随点击变大。
3. 点击切片，预览区显示整页横条，红框标出的字符位于预览区正中央。
4. 按住鼠标左键拖拽，图像跟随移动；松开鼠标后光标恢复。
5. 按住 Ctrl 并滚动鼠标滚轮，图像以视图中心为锚点放大/缩小。
6. 未按住 Ctrl 时滚动滚轮，图像垂直滚动。
7. 切换不同高度的行，图像初始宽度始终等于预览区宽度，高度自适应，无纵向拉伸超出区域的情况。
8. 低分切片仍正确显示浅黄色底色与橙黄色边框。

---

# 补充：无边界拖拽与切换字符时宽度异常修复

## 新增任务概述

1. **去掉边界判断，允许图片拖出框**：当前拖拽平移依赖滚动条，sceneRect 限制了拖动范围，用户要求能够将图像完全拖出预览框。
2. **修复切换字符列表时预览区异常变大**：用户发现点击切片显示预览后，再切换左侧字符列表，预览区会突然变大。

## 问题分析

### 1. 拖拽受边界限制

`PreviewGraphicsView` 初次实现通过修改 `horizontalScrollBar().value()` 与 `verticalScrollBar().value()` 来平移视图。滚动条的取值范围由 `sceneRect` 决定，因此图像无法移出 scene 边界。

### 2. 切换字符列表时预览区变大

布局链为：

```
main_layout (QHBoxLayout)
└── right_column_layout (QVBoxLayout)
    ├── preview_group
    │   └── preview_stack
    │       ├── hint_page
    │       └── preview_view (PreviewGraphicsView)
    └── right_group
        └── scroll_area
            └── scroll_content
                └── grid_container
                    └── grid_layout
                        └── SliceItemWidget (固定 90x90)
```

当某个字符对应切片数量较多时，`grid_layout` 的 size hint 基于 8 列网格计算，宽度较大。`scroll_area.setWidgetResizable(True)` 会使 `scroll_content` 跟随 viewport，但 `scroll_content` 的 minimum size hint 仍受 `grid_container` 影响。`right_group` 的 size hint 因此变大，进而撑大 `right_column_layout`。由于 `preview_group` 与 `right_group` 处于同一垂直布局，`preview_group` 也会分配到更大的宽度；而 `preview_view` 的水平 size policy 为 `Expanding`，会填满 `preview_group` 的可用宽度，导致预览区视觉上异常变大。

## 实现方案

### 1. 无边界拖拽

- 在 `PreviewGraphicsView` 中隐藏滚动条（`ScrollBarAlwaysOff`），因为不再需要滚动条限制。
- 将 view 的 `alignment` 设置为 `Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop`。Qt 文档指出：默认的 scene alignment 会导致 `translate()` 没有视觉效果，必须设置左上角对齐后，通过 `translate()` 才能实现自由平移。
- 在 `mousePressEvent` 中记录 viewport 中的鼠标位置。
- 在 `mouseMoveEvent` 中计算鼠标在 viewport 中的偏移量，将其除以当前缩放比例得到 scene 坐标偏移，然后调用 `self.translate(-scene_dx, -scene_dy)`，实现图像跟随鼠标无边界平移。
- 每次鼠标移动后更新起始位置，避免平移速度累积。

### 2. 修复宽度异常

- 在 `_init_ui` 中为 `grid_container` 设置 sizePolicy：`Expanding`（水平）+ `Preferred`（垂直），使其填满 `scroll_content` 而不是基于内容请求宽度。
- 重写 `scroll_area` 的 `resizeEvent`，在滚动区域大小变化时将 `grid_container` 的最大宽度限制为 `scroll_area.viewport().width()`，确保网格容器不会撑大上层布局。
- 为 `preview_stack` 设置 sizePolicy：`Expanding`（水平）+ `Fixed`（垂直），进一步约束预览堆栈的尺寸行为。
- 保留 `preview_view` 的 `Fixed` 垂直 size policy 与固定高度，确保预览区高度稳定。

## 关键代码变更

### PreviewGraphicsView 初始化

```python
self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
```

### 无边界平移

```python
def mousePressEvent(self, event):
    if event.button() == Qt.MouseButton.LeftButton:
        self._panning = True
        self._pan_start_pos = event.pos()
        self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        event.accept()

def mouseMoveEvent(self, event):
    if self._panning:
        delta = event.pos() - self._pan_start_pos
        scale = self.transform().m11()
        if scale != 0:
            self.translate(-delta.x() / scale, -delta.y() / scale)
        self._pan_start_pos = event.pos()
        event.accept()
```

### grid_container 宽度限制

```python
self.grid_container.setSizePolicy(
    QSizePolicy.Policy.Expanding,
    QSizePolicy.Policy.Preferred,
)

def _on_scroll_area_resized(self):
    viewport_width = self.scroll_area.viewport().width()
    if viewport_width > 0:
        self.grid_container.setMaximumWidth(viewport_width)
```

## 验证步骤（补充）

1. 点击切片显示预览后，切换左侧字符列表，观察预览区宽度是否保持稳定。
2. 在预览区按住左键拖拽，确认图像可以无限制地拖出预览框。
3. 拖出框后释放鼠标，再次拖拽仍能正常移动。
4. 切换字符或点击新切片后，视图自动回到以红框为中心、宽度适配的初始状态。
5. Ctrl+滚轮缩放、普通滚轮行为保持不变。
