# 横校窗口大量切片展示性能优化计划

## 问题分析

当用户点击一个包含大量切片的字符（如中文逗号"，"可能有数百甚至上千个）时，软件严重卡顿。

### 根因分析

`_update_slice_display` 方法在切换字符时，**同步一次性**完成以下所有操作：

1. **创建大量 SliceItemWidget 实例**：500+ 个 Widget 实例同时创建，每个都包含 QLabel、布局、样式表、信号连接
2. **PIL→QPixmap 转换**：每个切片都要调用 `_pil_to_pixmap`，涉及 `tobytes("raw", "RGBA")` 和 `QImage` 构造
3. **SmoothTransformation 缩放**：每个 pixmap 都用 `Qt.TransformationMode.SmoothTransformation` 缩放到 80×80，这是 **CPU 密集型操作**，对缩略图而言完全没必要
4. **QGridLayout 批量添加**：500+ 个 Widget 同时加入布局，触发大量布局计算
5. **无缓存机制**：每次切换字符都重新创建所有 Widget 和转换所有图像，即使之前已经看过

### 性能瓶颈量化估算

以 500 个切片为例：
- 500 次 PIL→QPixmap 转换：~500ms
- 500 次 SmoothTransformation 缩放：~1000ms（这是最大瓶颈）
- 500 个 Widget 创建+布局：~300ms
- **总计约 1.8 秒 UI 冻结**

## 优化方案

采用三层优化策略：

### 优化1：缩放模式改为 FastTransformation（立竿见影）

**修改位置**：`SliceItemWidget.__init__` 第69行

将 `Qt.TransformationMode.SmoothTransformation` 改为 `Qt.TransformationMode.FastTransformation`

**效果**：缩放速度提升 5-10 倍，80×80 缩略图视觉差异极小
**预计节省**：~800ms → ~100ms

### 优化2：分页展示（核心优化）

**原理**：每页只展示固定数量的切片（如 100 个），通过翻页按钮浏览更多切片。

**修改内容**：

1. 在 `HorizontalCheckWindow` 中新增分页状态变量：
   - `self._current_char_text`：当前展示的字符
   - `self._current_page`：当前页码（从 0 开始）
   - `self._page_size`：每页切片数（默认 100）

2. 修改 `_update_slice_display` 方法：
   - 只创建当前页的 SliceItemWidget
   - 在网格下方显示分页信息（如"第 1/5 页，共 483 个"）和翻页按钮

3. 新增分页导航控件：
   - "上一页"按钮
   - "下一页"按钮
   - 页码信息标签

4. 新增 `_on_prev_page` 和 `_on_next_page` 方法

**效果**：无论切片总数多少，单次最多创建 100 个 Widget，保证流畅
**预计耗时**：~200ms（100 个 Widget × FastTransformation）

### 优化3：QPixmap 缓存（减少重复转换）

**原理**：缓存已转换的 QPixmap，避免切换字符时重复进行 PIL→QPixmap 转换。

**修改内容**：

1. 在 `HorizontalCheckWindow` 中新增缓存字典：
   - `self._pixmap_cache`：键为 `(char_text, slice_index)`，值为 QPixmap

2. 修改 `_update_slice_display` 方法：
   - 创建 SliceItemWidget 前先检查缓存
   - 缓存命中则直接使用，未命中则转换后存入缓存

3. 修改 `_pil_to_pixmap` 方法：
   - 接受缓存键参数，内部检查缓存

**效果**：切换回之前看过的字符时，跳过 PIL→QPixmap 转换
**注意**：缓存会占用内存，需要设置上限。当缓存条目超过一定数量时清理最早的条目。使用 `collections.OrderedDict` 实现 LRU 缓存，上限设为 2000 个。

## 详细实施步骤

### 步骤1：修改 SliceItemWidget — FastTransformation

**文件**：`ui/horizontal_check_window.py`
**位置**：`SliceItemWidget.__init__` 第66-71行

```python
# 修改前
scaled = pixmap.scaled(
    80, 80,
    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
    Qt.TransformationMode.SmoothTransformation,
)

# 修改后
scaled = pixmap.scaled(
    80, 80,
    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
    Qt.TransformationMode.FastTransformation,
)
```

### 步骤2：在 HorizontalCheckWindow 中添加分页状态和缓存

**文件**：`ui/horizontal_check_window.py`
**位置**：`__init__` 方法

在 `self._init_ui()` 之前添加：
```python
self._current_char_text = ""
self._current_page = 0
self._page_size = 100
self._pixmap_cache = OrderedDict()
self._max_cache_size = 2000
```

在文件顶部导入区添加：
```python
from collections import OrderedDict
```

### 步骤3：修改 _init_ui — 添加分页导航控件

**文件**：`ui/horizontal_check_window.py`
**位置**：`_init_ui` 方法，在 scroll_area 和 bottom_layout 之间

在 `right_layout.addWidget(self.scroll_area, 1)` 之后、`bottom_layout` 之前添加分页导航：
```python
page_nav_layout = QHBoxLayout()
self.prev_page_btn = QPushButton("上一页")
self.prev_page_btn.clicked.connect(self._on_prev_page)
self.page_info_label = QLabel("")
self.page_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
self.next_page_btn = QPushButton("下一页")
self.next_page_btn.clicked.connect(self._on_next_page)
page_nav_layout.addWidget(self.prev_page_btn)
page_nav_layout.addStretch()
page_nav_layout.addWidget(self.page_info_label)
page_nav_layout.addStretch()
page_nav_layout.addWidget(self.next_page_btn)
right_layout.addLayout(page_nav_layout)
```

### 步骤4：修改 _update_slice_display — 分页 + 缓存

**文件**：`ui/horizontal_check_window.py`

```python
def _update_slice_display(self, char_text: str):
    self._current_char_text = char_text
    self._current_page = 0
    self._render_current_page()

def _render_current_page(self):
    # 清空现有控件
    for i in reversed(range(self.grid_layout.count())):
        widget = self.grid_layout.itemAt(i).widget()
        if widget is not None:
            widget.deleteLater()

    slices = self.char_slices.get(self._current_char_text, [])
    total = len(slices)
    total_pages = max(1, (total + self._page_size - 1) // self._page_size)

    start = self._current_page * self._page_size
    end = min(start + self._page_size, total)
    page_slices = slices[start:end]

    cols = 8
    for page_idx, char_slice in enumerate(page_idx, page_slices):
        global_idx = start + page_idx
        cache_key = (self._current_char_text, global_idx)
        if cache_key in self._pixmap_cache:
            pixmap = self._pixmap_cache[cache_key]
        else:
            pixmap = self._pil_to_pixmap(char_slice.image) if char_slice.image else QPixmap()
            self._pixmap_cache[cache_key] = pixmap
            if len(self._pixmap_cache) > self._max_cache_size:
                self._pixmap_cache.popitem(last=False)

        item_widget = SliceItemWidget(pixmap, global_idx)
        item_widget.right_clicked.connect(self._on_relocate)
        item_widget.delete_clicked.connect(self._on_delete_slice)
        row = page_idx // cols
        col = page_idx % cols
        self.grid_layout.addWidget(item_widget, row, col)

    # 更新分页信息
    self.page_info_label.setText(
        f"第 {self._current_page + 1}/{total_pages} 页，共 {total} 个"
    )
    self.prev_page_btn.setEnabled(self._current_page > 0)
    self.next_page_btn.setEnabled(self._current_page < total_pages - 1)
```

### 步骤5：新增分页导航方法

```python
def _on_prev_page(self):
    if self._current_page > 0:
        self._current_page -= 1
        self._render_current_page()

def _on_next_page(self):
    slices = self.char_slices.get(self._current_char_text, [])
    total_pages = max(1, (len(slices) + self._page_size - 1) // self._page_size)
    if self._current_page < total_pages - 1:
        self._current_page += 1
        self._render_current_page()
```

### 步骤6：修改 _on_relocate 和 _on_delete_slice — 适配分页

这两个方法中使用的 `slice_index` 现在是全局索引（因为 SliceItemWidget.index 是全局索引），所以逻辑不需要改变。但 `_refresh_label_list` 后需要重新渲染当前页：

在 `_on_relocate` 末尾，将 `self._refresh_label_list()` 后的选中逻辑保持不变，但需要确保选中后 `_on_label_selected` 会触发 `_update_slice_display` 重置分页。

在 `_on_delete_slice` 末尾同理。

### 步骤7：修改 SliceItemWidget.index 为全局索引

当前 `SliceItemWidget.__init__` 中的 `index` 参数在分页场景下需要是全局索引（用于定位 char_slices 列表中的元素），而不是页内索引。在步骤4中已经使用 `global_idx` 传入，所以不需要额外修改。

## 涉及文件汇总

| 文件 | 修改内容 |
|------|---------|
| `ui/horizontal_check_window.py` | FastTransformation缩放、分页展示、QPixmap缓存、分页导航控件和方法 |

仅修改 1 个文件，改动集中且风险可控。

## 预期效果

| 场景 | 优化前 | 优化后 |
|------|--------|--------|
| 500个切片的字符 | ~1.8秒卡顿 | ~200ms（100个/页+FastTransformation） |
| 1000个切片的字符 | ~3.6秒卡顿 | ~200ms |
| 再次切换回同一字符 | ~1.8秒 | ~50ms（缓存命中） |
