# 横校与精修阶段重构 Spec

> 本文档同时作为任务 2 所要求的「Python 版本横校与精修功能技术报告」与 C++ 重构规范。
> change-id: `reimplement-horizontal-refine-stages`

## Why

当前 C++ 版本（`d:\hx\2_cpp`）的横校（`HorizontalCheckWindow`）虽然大体对应 Python 实现，但存在若干与 Python 版本语义不一致的差异（修改记录缺失、忽略状态存储方式不同、像素缓存策略不同、完成确认对话框信息不全）；精修阶段（`RefineWindow`）仅有 `mainwindow.cpp` 中的占位 `QLabel`，`MovableTextItem` 与 `PDFOutputWorker` 完全缺失。需要彻底移除并按 Python 版本（`d:\hx\software2`）重新实现，达成功能与界面双对齐，同时补齐异常处理、日志记录与 Windows 7 SP1 兼容性。

## What Changes

- **BREAKING**：删除现有 `src/windows/horizontalcheckwindow.h` / `.cpp` 的全部实现，按 Python `ui/horizontal_check_window.py` 重新实现。
- **BREAKING**：移除 `mainwindow.cpp` 中精修阶段占位逻辑（`create_placeholder_widget` 调用），新增 `RefineWindow` 完整实现。
- 新增 `MovableTextItem` 类（8 角缩放手柄、拖拽移动、右键编辑/删除、双击选中、缩放跟随）。
- 新增 `PDFOutputWorker`（`QThread` 子类）封装红色/透明双版本 PDF 生成流程，发射 `progress_signal` / `finished_signal` / `error_signal`。
- 在 `LineSlice` 数据结构中新增 `bool ignored` 字段，对齐 Python 动态属性 `ls._ignored` 的语义。
- `MainWindow` 横校阶段完成后，将 `horiz_widget_->page_lines()` 传递给 `RefineWindow`（而非 `corrected_lines_`），与 Python `main.py:191` 行为对齐。
- 新增 `utils/logger.h/.cpp`：单例日志器，写入应用目录下 `hengxiao_tool2.log`，记录时间戳、错误类型、堆栈追踪、上下文数据。
- 新增全局异常处理：`std::set_terminate`、`_set_se_translator`（SEH）、各阶段切换与 PDF 操作的 `try/catch` 包装。
- 引入 `backward-cpp`（header-only）提供 Windows 7 兼容的堆栈回溯（基于 DbgHelp，仅使用 Win7 可用 API）。
- 更新 `CMakeLists.txt`：新增源文件、`/DEBUG` 链接器选项生成 PDB、`/Zi` 编译选项、`backward-cpp` FetchContent。
- 验证编译环境（Qt 5.15.x、CMake >=3.16、vcpkg、MuPDF、PoDoFo、VS 2019 v142 工具集）并更新 `build.bat` / `deploy.bat` / `README.md`。

## Impact

- **Affected specs**：横校阶段、精修阶段、PDF 输出、异常处理与日志、Windows 7 兼容性。
- **Affected code**：
  - `src/windows/horizontalcheckwindow.h` / `.cpp`（完全重写）
  - `src/windows/refinewindow.h` / `.cpp`（新增）
  - `src/windows/mainwindow.h` / `.cpp`（替换精修占位、调整数据流）
  - `src/models/datamodels.h`（`LineSlice` 新增 `ignored` 字段、更新 JSON 序列化）
  - `src/processors/pdf_output_worker.h` / `.cpp`（新增）
  - `src/utils/logger.h` / `.cpp`（新增）
  - `src/utils/exception_handler.h` / `.cpp`（新增）
  - `src/main.cpp`（注册全局异常处理）
  - `CMakeLists.txt`、`build.bat`、`deploy.bat`、`README.md`

---

## ADDED Requirements

### Requirement: Logger 单例日志器

系统 SHALL 提供一个全局可访问的 `Logger` 单例（`utils/logger.h`），将所有日志条目写入应用可写目录下的 `hengxiao_tool2.log`。

每条日志 SHALL 包含：
- 时间戳（`yyyy-MM-dd HH:mm:ss.zzz`，使用 `GetSystemTimeAsFileTime` 而非 Win8+ 的 `GetSystemTimePreciseAsFileTime`）
- 日志级别（`INFO` / `WARNING` / `ERROR` / `FATAL`）
- 错误类型（C++ 异常 `what()`、SEH 异常代码、或自定义类别）
- 堆栈追踪（通过 `backward-cpp` 生成，需 PDB 符号）
- 上下文数据（文件名、行号、函数名、可选的自定义上下文字段）

#### Scenario: 普通日志写入
- **WHEN** 任意代码调用 `Logger::instance().info("导入完成", __FILE__, __LINE__)`
- **THEN** 日志文件追加一行包含时间戳、`INFO`、文件路径、行号、消息的记录

#### Scenario: 异常带堆栈
- **WHEN** 捕获到 `std::runtime_error` 并调用 `Logger::instance().error(ex, __FILE__, __LINE__, "横校阶段")`
- **THEN** 日志记录包含 `what()` 内容、完整堆栈追踪、上下文标签 "横校阶段"

### Requirement: 全局异常处理

系统 SHALL 在 `main.cpp` 启动早期注册：
1. `std::set_terminate` 处理器：捕获未捕获的 C++ 异常，记录 FATAL 日志后弹出 `QMessageBox` 提示并退出。
2. `_set_se_translator` 处理器：将 Windows SEH 异常（如访问违例）转换为可读日志记录，捕获堆栈后退出。

#### Scenario: 未捕获异常
- **WHEN** 任意线程抛出未被捕获的 C++ 异常
- **THEN** `terminate` 处理器记录 FATAL 日志（含堆栈），向用户显示错误对话框，进程以非零码退出

#### Scenario: 段错误
- **WHEN** 发生访问违例（SEH `EXCEPTION_ACCESS_VIOLATION`）
- **THEN** SEH 转换器记录 FATAL 日志（含异常代码与堆栈），进程退出

### Requirement: MovableTextItem 可拖拽文字项

系统 SHALL 提供 `MovableTextItem` 类（继承 `QGraphicsRectItem`），完整对齐 Python `ui/refine_window.py:31-518` 实现：

- 8 个缩放手柄（`topLeft`/`top`/`topRight`/`left`/`right`/`bottomLeft`/`bottom`/`bottomRight`），尺寸 `HANDLE_SIZE = 8` 像素
- 鼠标按下：命中手柄进入缩放模式；命中文字进入移动模式；命中空白取消其他选中
- 鼠标移动：缩放模式按手柄方向调整 `rect()` 并保持原点 `(0,0)`；移动模式按增量更新 `pos()`
- 鼠标释放：清除缩放/移动状态
- 悬停：根据手柄位置设置对应光标（`SizeFDiagCursor` / `SizeBDiagCursor` / `SizeVerCursor` / `SizeHorCursor` / `SizeAllCursor`）
- 双击：选中该项
- 右键菜单：`修改文字` / `删除`
- `activate()` / `deactivate()` 控制 `_activated` 状态，未激活时所有交互事件 `event.ignore()`
- `update_zoom(double new_zoom)` 按比例缩放位置、尺寸、字体
- `_edit_text()` 弹出对话框编辑文字内容

#### Scenario: 拖拽移动文字
- **WHEN** 用户在拖拽模式下按下鼠标左键拖动文字项
- **THEN** 文字项跟随鼠标移动，松开时位置保留

#### Scenario: 八角缩放
- **WHEN** 用户拖动 `topRight` 手柄
- **THEN** 矩形宽度随鼠标 X 增量增加，高度随鼠标 Y 增量减少，最小尺寸限制为 5

#### Scenario: 删除文字
- **WHEN** 用户右键选择「删除」
- **THEN** 关联的 `RefineTextItem.ignored = true`，图元 `setVisible(false)`

### Requirement: RefineWindow 精修窗口

系统 SHALL 提供 `RefineWindow` 类（继承 `QWidget`），完整对齐 Python `ui/refine_window.py:520-1406` 实现：

- 构造接收 `std::map<int, std::vector<LineSlice>> page_lines` 与 `std::vector<QImage> page_images`
- `_convert_chars()`：遍历 `page_lines`，跳过忽略行，将每个字符转为 `RefineTextItem` 存入 `page_items_`
- 工具栏包含：返回 / 翻页 / 缩放 / 手型工具 / 拖拽 / 新增文字 / 输出 / 确认完成
- 三种工具模式：手型（`ScrollHandDrag`）、拖拽（激活所有 `MovableTextItem`）、新增文字（`CrossCursor`）
- `_render_page()`：渲染页面背景图 + 为每个非忽略 `RefineTextItem` 创建 `MovableTextItem`；首次渲染延迟调用 `on_fit_height()`
- `_sync_current_page()`：将场景中 `MovableTextItem` 的位置反算回 `RefineTextItem.bbox`
- `_add_text_at(scene_pos)`：弹对话框输入文字，按平均字号为每个字符创建独立 `RefineTextItem`，水平排列
- `on_output()`：弹保存对话框，启动 `PDFOutputWorker` 生成红色与透明两个 PDF
- `on_finish_confirm()`：弹确认对话框，确认后启动 PDF 生成并发射 `finished_signal`
- `keyPressEvent`：拖拽模式下 `Delete` 键删除选中项
- 信号：`finished_signal()`、`output_complete_signal(QString, QString)`、`back_signal()`

#### Scenario: 拖拽工具切换
- **WHEN** 用户点击「拖拽」按钮
- **THEN** 关闭手型与新增文字模式，激活所有文字项的交互能力，光标变为箭头

#### Scenario: 新增文字
- **WHEN** 用户在新增文字模式下右键空白处选择「添加文字」并输入 "校正"
- **THEN** 在点击位置生成两个 `RefineTextItem`（"校"、"正"）水平排列，每个字符一个独立图元

#### Scenario: 输出 PDF
- **WHEN** 用户点击「输出」并选择保存路径 `out.pdf`
- **THEN** 系统生成 `out_红.pdf` 与 `out_透明.pdf`，进度对话框实时显示当前页与百分比

### Requirement: PDFOutputWorker 工作线程

系统 SHALL 提供 `PDFOutputWorker` 类（继承 `QThread`），完整对齐 Python `pdf_processor/pdf_output.py:135-211`：

- 构造接收 `PDFOutputGenerator*`、`std::vector<CorrectedChar>`、`std::vector<QImage>`、`red_path`、`transparent_path`
- 信号：`progress_signal(int, QString)`、`finished_signal()`、`error_signal(QString)`
- `run()`：先调用 `generate(text_color="red")`，再 `generate(text_color="transparent")`，每页回调进度
- 总步数 = `total_pages * 2`，红色阶段进度 = `current_page / total_steps`，透明阶段进度 = `(total_pages + current_page) / total_steps`
- 异常通过 `error_signal` 发射，线程自动 `deleteLater`

### Requirement: 横校完成确认对话框信息完整

横校完成确认对话框 SHALL 同时显示「修改文字」数量与「忽略行」数量，对齐 Python `_on_finish`。

#### Scenario: 完成确认
- **WHEN** 用户点击「完成横校」
- **THEN** 对话框显示 `修改文字：N 处\n忽略行：M 处`，确认后发射 `finished_signal`

---

## MODIFIED Requirements

### Requirement: LineSlice 数据结构

`LineSlice` 新增 `bool ignored = false` 字段，对齐 Python 动态属性 `ls._ignored`。该字段参与 `to_json` / `from_json` 序列化。横校的「忽略行」操作直接设置 `ls.ignored = true`，`build_corrected_lines()` 读取该字段构造 `CorrectedLine.ignored`。

### Requirement: HorizontalCheckWindow 横校窗口

完全重写 `horizontalcheckwindow.h` / `.cpp`，对齐 Python `ui/horizontal_check_window.py`：

- 构造接收 `std::map<int, std::vector<LineSlice>>` 与 `std::vector<QImage>`，按值移动存储
- `modifications_` 列表追踪 `{type: "modify_text"|"ignore", ...}` 操作记录
- `_render_page()` 双缓存：左侧场景缓存 key = `(page, zoom)`，右侧 PDF 场景缓存 key = `(page, zoom, 'pdf')`，与 Python 一致使用 `std::map<std::tuple<int,int,char>, QPixmap>` 或等价结构
- 忽略状态通过 `LineSlice::ignored` 字段（取代原 `std::set`）读取，渲染时灰色显示
- `_on_modify_text` 修改后调用 `_sync_chars_with_text` 同步字符级 bbox
- `_on_finish` 对话框显示修改数 + 忽略数两项统计
- 公开 `page_lines()` 访问器供 `MainWindow` 传递给 `RefineWindow`

### Requirement: MainWindow 阶段切换

`MainWindow::setup_refine_stage()` 不再创建占位 widget，而是构造 `RefineWindow` 并连接信号：

- 接收 `horiz_widget_->page_lines()`（横校修改后的行数据）与 `page_images_`
- 连接 `finished_signal` / `output_complete_signal` / `back_signal`
- `on_output_complete` 显示成功消息框
- `on_refine_finished` 清理所有阶段窗口并重置到导入阶段

### Requirement: datamodels.h JSON 序列化

`LineSlice` 的 `to_json` / `from_json` 新增 `ignored` 字段读写。

---

## REMOVED Requirements

### Requirement: 原有 HorizontalCheckWindow 实现

**Reason**：与 Python 版本存在多处语义差异（`std::set` 存储忽略行 vs Python `ls._ignored`、缺少 `modifications_` 列表、单缓存 vs 双缓存、完成对话框信息不全）。
**Migration**：删除 `horizontalcheckwindow.h` / `.cpp` 全部内容，按 Python 重新实现。`ignored_lines_` 集合改为 `LineSlice::ignored` 字段。

### Requirement: 精修阶段占位 widget

**Reason**：`create_placeholder_widget(QStringLiteral("精修阶段（占位，后续任务实现）"))` 仅为开发期占位，不提供任何实际功能。
**Migration**：删除 `mainwindow.cpp:264` 的占位调用与 `create_placeholder_widget` 函数，替换为 `RefineWindow` 构造。

---

## 技术报告：Python 版本横校与精修功能实现详解

### 1. 横校阶段（HorizontalCheckWindow）算法规范

**文件**：`d:\hx\software2\ui\horizontal_check_window.py`（894 行）

#### 1.1 数据结构

- `page_lines: dict[int, list[LineSlice]]` —— 页码到行切片列表的映射
- `page_images: list[PIL.Image]` —— 页面原始图像
- `zoom_level: float` —— 缩放比例，初始 1.0
- `modifications: list` —— 操作历史，元素为 `{"type": "modify_text", "old_text":..., "details":...}` 或 `{"type": "ignore", "text":..., "details":"ignored"}`
- `_pixmap_cache: dict` —— 像素图缓存，key 为 `(page, zoom)` 或 `(page, zoom, 'pdf')`

#### 1.2 渲染算法 `_render_page()`

1. `scene.clear()` 清空左侧场景；重置 `_hover_pixmap_item` / `_hover_rect_item`
2. 遍历当前页 `page_lines[current_page]` 的每个 `LineSlice`：
   - 读取 `ignored = hasattr(ls, "_ignored") and ls._ignored`，决定文字颜色（`Qt.gray` 或 `Qt.black`）
   - 若 `ls.chars` 为空：按行渲染 `QGraphicsTextItem`，字体大小 = `max((bbox[3]-bbox[1]) * zoom, 6)`，位置 `(bbox[0]*zoom, bbox[1]*zoom)`
   - 否则按字符级渲染：跳过 `bbox_valid=False` 的字符；计算 `pixel_size = max(int(bbox_height * zoom), 4)`；用 `QFontMetrics` 测量实际宽度，若超出目标宽度则按比例缩小 `pixel_size`；计算水平居中 `x_offset` 与垂直居中 `y_offset`；设置 `item.setData(0, id(ls))` 与 `item.setData(1, ls)`
3. 加载当前页图像：缓存 key 为 `(current_page, zoom_level)`，未命中则 `pil_to_pixmap` + `scaled(KeepAspectRatio, SmoothTransformation)`，缓存只保留最近一项（`self._pixmap_cache = {cache_key: scaled_pixmap}`，覆盖式）
4. 设置 `scene.setSceneRect(0, 0, w, h)`
5. 渲染右侧 PDF 场景：缓存 key 为 `(current_page, zoom_level, 'pdf')`，独立缓存
6. 更新页码标签、`page_spin`（blockSignals 防回环）、缩放输入框
7. 首次渲染延迟 100ms 调用 `_on_fit_height`

#### 1.3 悬停预览算法 `eventFilter`

- 仅处理 `view.viewport()` 与 `pdf_view.viewport()` 的事件
- `QWheelEvent`：先调用 `calculate_wheel_zoom(event, zoom_level)`，返回非 None 则更新缩放并重新渲染
- 滚轮到顶/底自动翻页：`delta > 0 && v_bar.value() == minimum() && current_page > 0` 时翻上一页，并通过 `QTimer.singleShot(0, ...)` 将滚动条设到 maximum
- `MouseMove`：将视口坐标映射到场景坐标，`scene.itemAt` 命中 `QGraphicsTextItem` 时读取 `data(1)` 获取 `LineSlice`
  - 若与当前 `hover_pixmap_item.data(0)` 相同则跳过
  - 否则 `_remove_hover_pixmap()` 清除旧预览
  - 缓存机制：`_slice_cache_id` / `_slice_cache_pixmap` 缓存上次切片图，命中跳过 `_make_slice_pixmap`
  - `_make_slice_pixmap(ls)`：从 `page_images[ls.page_num]` 裁剪 `[0, max(bbox[1]-20, 0), page_img.width, min(bbox[3]+20, page_img.height)]` 区域
  - 将切片按 `full_w / pixmap.width()` 比例放大到全宽，位置 `(0, ls.bbox[1]*zoom - pi_h)`，`setZValue(100)`
  - 右侧 PDF 场景画蓝色框：`QRectF(bbox[0]*zoom, bbox[1]*zoom, (bbox[2]-bbox[0])*zoom, (bbox[3]-bbox[1])*zoom)`，`QPen(blue, 2)`，`setZValue(10)`

#### 1.4 修改文字与字符同步 `_sync_chars_with_text`

- 字符数相同：逐个替换 `old_chars[i]["text"] = new_text[i]`，保留原 bbox
- 字符数不同：按行 bbox 等间距分配 `char_width = line_width / len(new_text)`，为每个字符生成新 dict `{"text": ch, "bbox": [x1, y1, x2, y2], "bbox_valid": True}`，整体替换 `ls.chars`

#### 1.5 完成确认 `_on_finish`

- 统计 `modify_count = sum(1 for m in modifications if m["type"] == "modify_text")`
- 统计 `ignore_count = sum(1 for m in modifications if m["type"] == "ignore")`
- 对话框显示 `修改文字：{modify_count} 处\n忽略行：{ignore_count} 处`
- 确认后 `_build_corrected_lines()` 遍历所有页面行切片，构造 `CorrectedLine(text, bbox, page_num, ignored)` 列表，发射 `finished_signal`

### 2. 精修阶段（RefineWindow + MovableTextItem）算法规范

**文件**：`d:\hx\software2\ui\refine_window.py`（1406 行）

#### 2.1 MovableTextItem 类（line 31-518）

继承 `QGraphicsRectItem`，封装可拖拽缩放的文字项：

- **构造**：根据 `RefineTextItem.bbox` 与 `zoom_level` 计算 `w = (x2-x1)*zoom`、`h = (y2-y1)*zoom`，`setPos(x1*zoom, y1*zoom)`，`setRect(0, 0, w, h)`；内嵌 `QGraphicsTextItem` 红色文字，字体 `pixelSize = max(int(h), 1)`；创建 8 个蓝色手柄（初始不可见）
- **缩放算法** `mouseMoveEvent`：
  - 根据 `handle` 名称判断影响维度：`topLeft/left/bottomLeft` 影响 `new_w = sr.width - delta.x` 且 `dx = delta.x`；`topRight/right/bottomRight` 影响 `new_w = sr.width + delta.x`
  - `topLeft/top/topRight` 影响 `new_h = sr.height - delta.y` 且 `dy = delta.y`；`bottomLeft/bottom/bottomRight` 影响 `new_h = sr.height + delta.y`
  - 最小尺寸 5：若 `new_w < 5` 则调整 `dx` 使宽度为 5；高度同理
  - `setPos(start_pos.x + dx, start_pos.y + dy)`、`setRect(0, 0, new_w, new_h)`、更新字体 `pixelSize = max(int(new_h), 1)`、重定位手柄、居中文字
- **移动算法**：`delta = scenePos - move_start_scene_pos`、`setPos(move_start_pos + delta)`
- **手柄命中** `_handle_at`：遍历 8 个手柄，`mapFromScene(scene_pos)` 后 `contains` 检测
- **光标映射** `_HANDLE_CURSORS`：`topLeft/bottomRight → SizeFDiagCursor`，`topRight/bottomLeft → SizeBDiagCursor`，`top/bottom → SizeVerCursor`，`left/right → SizeHorCursor`
- **右键菜单** `contextMenuEvent`：`修改文字`（弹对话框编辑）/ `删除`（`_data.ignored = True`、`setVisible(False)`）

#### 2.2 RefineWindow 类（line 520-1406）

- **数据转换** `_convert_chars`：遍历 `page_lines`，跳过 `ls._ignored` 行，为每个字符创建 `RefineTextItem(text, bbox, page_num, font_size=bbox[3]-bbox[1])` 存入 `page_items[page_num]`
- **三工具模式**：
  - 手型：`view.setDragMode(ScrollHandDrag)` + `OpenHandCursor`，停用所有 `MovableTextItem`
  - 拖拽：`NoDrag` + `ArrowCursor`，激活所有 `MovableTextItem`
  - 新增文字：`NoDrag` + `CrossCursor`，停用所有 `MovableTextItem`
- **新增文字** `_add_text_at`：弹对话框，按 `_get_avg_font_size()` 计算 `h = w = avg_font_size`，为每个字符创建 `RefineTextItem` 水平排列（`char_x = base_x + i*w`）
- **数据回写** `_sync_current_page`：遍历场景 `MovableTextItem`，`data.bbox = [pos.x/zoom, pos.y/zoom, (pos.x+w)/zoom, (pos.y+h)/zoom]`、`data.font_size = rect.height / zoom`
- **输出** `_on_output` / `_on_finish_confirm`：`_sync_current_page` → 文件保存对话框 → `_build_corrected_chars` → `_start_pdf_generation` 启动 `PDFOutputWorker`，显示 `QProgressDialog`，连接 `progress_signal`/`finished_signal`/`error_signal`

### 3. PDF 输出算法规范

**文件**：`d:\hx\software2\pdf_processor\pdf_output.py`（211 行）

#### 3.1 PDFOutputGenerator.generate

1. 按页码分组非忽略字符
2. 字体注册：`C:\Windows\Fonts\msyh.ttc` 存在则注册 `MicrosoftYaHei`，否则用 `Helvetica`
3. 逐页：`setPageSize((page_width, page_height))` → `drawImage(img, 0, 0)` → 遍历该页字符：
   - `font_size = bbox_height`，最小 1
   - `stringWidth` 测量文本宽度，若超过 `bbox_width` 则 `font_size *= bbox_width / text_w`
   - `lly = (page_height - y2) + (bbox_height - font_size) / 2`（PDF 坐标系 Y 轴向上）
   - `llx = x1 + (bbox_width - text_w) / 2`
   - `transparent` 模式：`setFillColor(Color(0,0,0,alpha=0))`；`red` 模式：`setFillColorRGB(1,0,0)`
   - `drawString(llx, lly, text)`
4. `c.save()`

#### 3.2 PDFOutputWorker.run

- `total_steps = total_pages * 2`
- 红色阶段进度 `percent = current_page / total_steps * 100`
- 透明阶段进度 `percent = (total_pages + current_page) / total_steps * 100`
- 成功发射 `finished_signal`，失败发射 `error_signal(str(e))`

### 4. UI 设计模式

- **步骤指示器**：顶部 4 步「导入 → 纵校 → 横校 → 精修」，当前步蓝色 `#0D6EFD`、已完成绿色 `#198754`、未开始灰色 `#e9ecef`
- **工具栏**：`QToolBar` 不可移动，`spacing: 6px; padding: 4px`，按钮扁平无圆角
- **横校双视图**：左侧文字叠加视图 + 右侧原 PDF 视图，并排 `QHBoxLayout`，滚动条双向联动
- **精修单视图**：单个 `QGraphicsView`，背景为页面图像，文字项浮于其上
- **右键菜单**：`CustomContextMenu` 策略，`QMenu.exec(mapToGlobal(pos))`
- **对话框**：`QDialog` 模态，`setMinimumWidth(400)`，按钮布局 `addStretch` + 确定 + 取消
- **全局样式**：`ui/styles.py` 的 `get_stylesheet()` 提供 Bootstrap 风格 QSS

### 5. 数据流图

```
[导入阶段 ImportWindow]
    │ 输出: page_images, ocr_results=(lines,chars), char_slices
    ▼
[纵校阶段 VerticalCheckWindow]
    │ 输入: char_slices, page_images, ocr_results
    │ 输出: updated_char_slices, updated_ocr_results
    ▼
[OCR Engine build_line_data]
    │ 输入: ocr_results, page_images, char_slices
    │ 输出: page_lines: {page_num: [LineSlice{chars:[{text,bbox,bbox_valid}]}]}
    ▼
[横校阶段 HorizontalCheckWindow]
    │ 输入: page_lines, page_images
    │ 操作: 修改文字(同步chars) / 忽略行(标记_ignored)
    │ 输出: corrected_lines (供主流程记录)
    │ 保留: page_lines (供精修阶段使用)
    ▼
[精修阶段 RefineWindow]
    │ 输入: horiz_widget.page_lines, page_images
    │ 转换: _convert_chars → page_items: {page_num: [RefineTextItem]}
    │ 操作: 拖拽/缩放/新增/删除/编辑文字
    │ 输出: PDFOutputWorker → 红色版PDF + 透明版PDF
    ▼
[完成] 弹出成功消息框 → 清理所有窗口 → 返回导入阶段
```

### 6. Windows 7 SP1 兼容性要点

- **Qt 版本**：5.15.x（禁用 Qt6，因 Qt6 依赖 Win10+ API）
- **系统 API 目标**：`_WIN32_WINNT=0x0601`、`WINVER=0x0601`（已在 `CMakeLists.txt:11` 配置）
- **时间 API**：使用 `GetSystemTimeAsFileTime`，禁用 `GetSystemTimePreciseAsFileTime`（Win8+）
- **DbgHelp**：`backward-cpp` 仅使用 `SymFromAddr`、`CaptureStackBackTrace` 等 Win7 可用 API
- **Visual Studio 工具集**：v142（VS 2019）或 v143（VS 2022）需安装 Win7 SDK 支持
- **C++ 运行时**：建议静态链接 `/MT` 避免目标机器缺少 VCRedist
- **第三方库**：MuPDF、PoDoFo 必须以 Win7 为目标编译；vcpkg 默认 triplet `x64-windows` 通常兼容，但需验证

### 7. 异常处理与日志规范

- **日志文件位置**：`%APPDATA%\hengxiao_tool2\logs\hengxiao_tool2.log`（Win7 兼容路径），按日轮转
- **日志格式**：`[2026-07-01 14:30:25.123] [ERROR] [横校阶段] mainwindow.cpp:155 std::runtime_error: lines.json 不存在`
- **堆栈格式**：紧跟日志条目，多行缩进显示
- **包装点**：
  - `MainWindow` 各阶段切换函数（`setup_horizontal_stage`、`setup_refine_stage` 等）
  - `OCREngine::load_results_from_file`、`build_line_data`
  - `PDFOutputGenerator::generate`、`PDFOutputWorker::run`
  - `HorizontalCheckWindow::render_page`、`RefineWindow::render_page`
  - 所有 `QFile`、`QImage::save`、`json::parse` 调用
