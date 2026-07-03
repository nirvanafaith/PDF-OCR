# 软件二纵校界面增强技术报告

## 任务概述

本次任务包含三个子任务：

1. **自动导入 JSON**：选择 PDF 后自动导入同目录下的 `lines.json` 与 `newchar.json`（若 `newchar.json` 不存在则使用 `chars.json`），并移除"自动查找"勾选框。
2. **原图展示框**：在纵校界面顶部增加原图预览区域，选中切片时以适合高度显示该切片所在行的整行图像，并用红框标出选中切片来源。
3. **低分切片提示**：根据每个字符的 `score` 得分，将当前展示切片中得分最低的 10% 底色显示为浅黄色。

## 当前代码分析

### 1. 数据导入：`软件2/ui/import_window.py`

当前导入界面包含三个文件选择输入框（PDF、lines.json、chars.json）和一个"自动查找 chars.json"复选框。用户需要分别选择三个文件，流程繁琐。

### 2. 字符切片数据模型：`软件2/models/data_models.py`

`CharSlice` 当前字段：

```python
@dataclass
class CharSlice:
    page_num: int
    bbox: List[float]
    image: object = None
    text: str = ""
    line_id: int = -1
    char_id: int = -1
```

缺少 `score` 字段，需要扩展以支持低分提示功能。

### 3. 字符切片构建：`软件2/ocr_engine/rapidocr_engine.py`

`parse_and_group` 方法从 `chars.json` 读取字符数据，构建 `CharSlice` 对象。当前未读取 `score` 字段，也未读取 `newchar.json`。

### 4. 纵校界面：`软件2/ui/vertical_check_window.py`

当前布局：

- 左侧：字符列表（`QListWidget`）
- 右侧：切片网格展示（`QScrollArea` + `QGridLayout`）
- 底部：翻页控件 + "下一步"按钮

需要在右侧区域顶部增加"原图展示框"，并在切片展示中加入低分提示底色。

## 实现方案

### 任务1：自动导入 JSON

#### 修改文件：`软件2/ui/import_window.py`

1. **移除"自动查找"复选框**及其相关事件处理 `_on_auto_chars_toggled`。
2. **PDF 选择后自动查找 JSON**：在 `_on_browse_pdf` 中，获取 PDF 所在目录，自动查找：
   - `lines.json`
   - `newchar.json`（优先）
   - `chars.json`（fallback）
3. **禁用 lines/chars 的浏览按钮和输入框**：这些文件由系统自动检测，用户无需手动选择。保留显示以提供透明度。
4. **`_check_load_enabled` 只需检查 PDF 路径**。

#### 修改文件：`软件2/ocr_engine/rapidocr_engine.py`

`load_results_from_file` 当前默认查找 `chars.json`。由于导入窗口会直接传入正确的 chars 路径（newchar 或 chars），该方法无需修改。

### 任务2：原图展示框

#### 修改文件：`软件2/ui/vertical_check_window.py`

1. **新增顶部预览区域**：
   - 在右侧 `QGroupBox("切片展示")` 内部、`QScrollArea` 上方增加一个固定的预览面板。
   - 使用 `QGraphicsView` + `QGraphicsScene` 显示原图，支持缩放和适应高度。
   - 预览区域高度固定为 200px（可调整），宽度自适应。

2. **新增 `_show_line_preview(char_slice)` 方法**：
   - 根据 `char_slice.page_num` 和 `char_slice.line_id`，从 `ocr_results` 的 `lines` 列表中找到对应行的 `box`。
   - 使用 `flatten_bbox` 将行 box 转为 `[x1, y1, x2, y2]`。
   - 从 `page_images[page_num]` 中裁剪整行区域。
   - 将裁剪后的图像转换为 `QPixmap` 并添加到 `QGraphicsScene`。
   - 在 scene 中添加红色矩形（`QGraphicsRectItem`），覆盖选中切片的 `bbox`。
   - 调用 `fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)` 使图像适应预览区域高度。

3. **在切片选中时触发预览**：
   - 为 `SliceItemWidget` 增加 `clicked` 信号（或利用现有右键/左键事件）。
   - 在 `_render_current_page` 中连接 `SliceItemWidget` 的 `clicked` 信号到 `_on_slice_selected`。
   - `_on_slice_selected(index)` 调用 `_show_line_preview`。

4. **切片点击事件处理**：
   - 在 `SliceItemWidget` 中重写 `mousePressEvent`，左键点击时发射 `clicked(self.index)` 信号。

#### 修改文件：`软件2/models/data_models.py`

为 `CharSlice` 增加 `score` 字段（可选，默认 1.0）。

### 任务3：低分切片提示

#### 修改文件：`软件2/ocr_engine/rapidocr_engine.py`

在 `parse_and_group` 中读取 `char_data.get("score", 1.0)`，传入 `CharSlice(score=score)`。

#### 修改文件：`软件2/ui/vertical_check_window.py`

1. **计算阈值**：在 `_render_current_page` 中，对当前页的所有切片 score 计算 10% 分位数。
   - 使用简单排序取索引：`sorted_scores[int(len(scores) * 0.1)]`（若不足 10 个则至少标黄 1 个）。
   - 更合理：取全局最低 10% 阈值，但在当前页中只标黄低于阈值的切片。

2. **标黄显示**：在创建 `SliceItemWidget` 时，若 `char_slice.score <= threshold`，设置其背景样式为浅黄色 `#fff3cd`。

3. **样式隔离**：通过动态设置 `setStyleSheet` 或在 `SliceItemWidget` 构造函数中传入 `warn_bg` 布尔参数实现。

## 界面排版设计

### 纵校界面布局调整

```
+-------------------------------------------------------------+
|  顶部步骤指示器（MainWindow 级别）                            |
+-------------------------------------------------------------+
|  纵校窗口 (VerticalCheckWindow)                              |
|  +------------------+  +----------------------------------+ |
|  |                  |  | 切片展示                          | |
|  |  字符列表         |  | +------------------------------+ | |
|  |  （左侧面板）      |  | | 原图预览区（固定高度 200px）  | | |
|  |                  |  | | [整行图像 + 红框标记选中切片]  | | |
|  |                  |  | +------------------------------+ | |
|  |                  |  | | 切片网格（分页）               | | |
|  |                  |  | | [ ][ ][ ][ ]                  | | |
|  |                  |  | | [ ][ ][ ][ ]                  | | |
|  |                  |  | +------------------------------+ | |
|  |                  |  | | 翻页控件 | 下一步              | | |
|  |                  |  | +----------------------------------+ |
|  +------------------+  +----------------------------------+ |
```

### 原图预览区设计

- 背景：浅灰色 `#f8f9fa`，带 1px 边框 `#dee2e6`
- 图像：居中显示，保持宽高比，适应预览区高度
- 红框：2px 红色实线，无填充，覆盖选中切片区域
- 无选中时：显示提示文本"请选择切片查看来源"

### 低分切片样式

- 正常切片：白色背景 + 浅灰边框
- 低分切片（最低 10%）：浅黄色背景 `#fff3cd` + 橙黄色边框 `#ffc107`
- 悬停效果：保留蓝色高亮，优先级高于底色提示

## 性能考虑

1. **原图预览按需裁剪**：只在选中切片时裁剪整行图像，不预先处理。
2. **QPixmap 缓存复用**：`_pil_to_pixmap` 已有缓存机制，整行预览可独立缓存（key = (page_num, line_id)）。
3. **分位数计算 O(n log n)**：每页最多 100 个切片，计算开销可忽略。

## 验证步骤

1. 启动软件2，选择 PDF 后自动填充 lines.json 和 newchar.json（或 chars.json）。
2. 点击"开始加载"，数据加载完成后进入纵校界面。
3. 左侧字符列表正常显示，右侧切片网格正常显示。
4. 点击任意切片，顶部原图预览区显示该行图像，并用红框标出选中切片位置。
5. 切换不同切片，红框位置正确更新。
6. 得分较低的切片底色显示为浅黄色。
7. 软件无报错、无闪退。
