# PDF-OCR 项目技术审阅报告

> 本报告基于对 `e:\hx\` 下三个版本（`1/` Python v1、`2/` Python v2、`2_cpp/` C++ 版）全部源码的通读分析，对照 PyQt6 QThread、RapidOCR、PaddleOCR、Qt5/Qt6 的最佳实践，识别功能缺陷、性能瓶颈与代码质量问题，并评估数据持久化方案是否满足 BC 范式。
>
> 评估重点放在 `2/` 和 `2_cpp/`，`1/` 作为旧版仅做简略评估。

---

## 1. 项目概述

### 1.1 项目定位

PDF-OCR 是一款面向扫描书页 PDF 的字符级 OCR 桌面校对工具。核心流程为：

```
PDF 导入 → 字符级 OCR 识别 → 纵校（按字符分组校对）→ 横校（按行校对）→ 精修（输出 PDF）
```

### 1.2 版本演进

| 版本 | 目录 | 技术栈 | 流程阶段 | 角色 |
|------|------|--------|----------|------|
| v1 | [1/](file:///e:/hx/1) | PyQt6 + RapidOCR + PaddleOCR + PyMuPDF | 画框 → OCR 准备 | 基础版，含完整 OCR 推理 |
| v2 | [2/](file:///e:/hx/2) | PyQt6 + PyMuPDF + reportlab | 导入 → 纵校 → 横校 → 精修 | 增强版，仅做数据处理（不做 OCR 推理） |
| C++ | [2_cpp/](file:///e:/hx/2_cpp) | Qt5 + MuPDF + PoDoFo + nlohmann/json | 与 v2 一致 | v2 的 C++ 移植版，目标 Win7 SP1 兼容 |

### 1.3 关键依赖

**Python v2（[2/requirements.txt](file:///e:/hx/2/requirements.txt)）**：
- `PyQt6` — GUI 框架
- `PyMuPDF` (`fitz`) — PDF 解析与渲染
- `Pillow` — 图像处理
- `reportlab` — PDF 输出
- **注意：v2 不依赖 `rapidocr`/`paddlepaddle`/`onnxruntime`**，与 v1 不同

**C++ 版（[2_cpp/CMakeLists.txt](file:///e:/hx/2_cpp/CMakeLists.txt)）**：
- `Qt5`（非 Qt6，为 Win7 SP1 兼容）
- `MuPDF`（C API）
- `PoDoFo`（0.10.x API）
- `nlohmann/json`（FetchContent v3.11.3）
- `OpenSSL`（运行时通过 `main.cpp` 设置模块路径）
- `C++17` 标准

---

## 2. 架构分析

### 2.1 整体架构

三个版本均采用 **主窗口 + 阶段窗口（QStackedWidget）** 的架构：

- **MainWindow** 持有 `QStackedWidget`，按阶段切换子窗口
- **StepIndicator** 显示当前阶段
- 阶段窗口之间通过 Qt 信号传递数据

### 2.2 数据流

```
ImportWindow → (page_images, ocr_results, char_slices) → VerticalCheckWindow
            → (updated char_slices, updated ocr_results) → HorizontalCheckWindow
            → (corrected_lines) → RefineWindow
            → (red_pdf_path, transparent_pdf_path)
```

### 2.3 模块划分

| 模块 | Python v2 | C++ 版 | 职责 |
|------|-----------|--------|------|
| PDF 处理 | [2/pdf_processor/pdf_loader.py](file:///e:/hx/2/pdf_processor/pdf_loader.py) | [2_cpp/src/processors/pdf_processor.h](file:///e:/hx/2_cpp/src/processors/pdf_processor.h) | PDF → 图像 |
| OCR 引擎 | [2/ocr_engine/rapidocr_engine.py](file:///e:/hx/2/ocr_engine/rapidocr_engine.py) | [2_cpp/src/processors/ocr_engine.h](file:///e:/hx/2_cpp/src/processors/ocr_engine.h) | JSON 加载、解析、分组 |
| PDF 输出 | [2/pdf_processor/pdf_output.py](file:///e:/hx/2/pdf_processor/pdf_output.py) | [2_cpp/src/processors/pdf_output_generator.h](file:///e:/hx/2_cpp/src/processors/pdf_output_generator.h) | 校对后 PDF 生成 |
| 数据模型 | [2/models/data_models.py](file:///e:/hx/2/models/data_models.py) | [2_cpp/src/models/datamodels.h](file:///e:/hx/2_cpp/src/models/datamodels.h) | dataclass / struct 定义 |
| UI 主窗口 | [2/main.py](file:///e:/hx/2/main.py) | [2_cpp/src/windows/mainwindow.cpp](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp) | 阶段调度 |
| UI 阶段窗口 | [2/ui/*.py](file:///e:/hx/2/ui) | [2_cpp/src/windows/*.cpp](file:///e:/hx/2_cpp/src/windows) | 各阶段交互界面 |
| 样式 | [2/ui/styles.py](file:///e:/hx/2/ui/styles.py) | [2_cpp/resources/styles.qss](file:///e:/hx/2_cpp/resources/styles.qss) | QSS 样式表 |
| 缩放 | [2/ui/zoom_utils.py](file:///e:/hx/2/ui/zoom_utils.py) | [2_cpp/src/utils/zoom_utils.cpp](file:///e:/hx/2_cpp/src/utils/zoom_utils.cpp) | 滚轮缩放计算 |

### 2.4 线程模型

| 场景 | Python v2 | C++ 版 | 评估 |
|------|-----------|--------|------|
| PDF 导入 | `ImportWorker(QObject)` + `moveToThread()` | `ImportWorker(QObject)` + `moveToThread()` | ✓ 符合 worker object pattern |
| PDF 输出 | `PDFOutputWorker(QThread)` 继承 `run()` | — | ✗ 违反最佳实践 |
| 横校数据构建 | 主线程同步调用 `build_line_data` | `QtConcurrent::run` + `QFutureWatcher` | C++ 版更优 |
| 纵校修改 flush | 主线程同步 | 主线程同步 | 大字符组时可能卡顿 |

---

## 3. 功能缺陷清单

### 3.1 必须修复（Critical）

#### 3.1.1 横校 pixmap 缓存被整体替换（缓存完全失效）

- **位置**：[2/ui/horizontal_check_window.py:293](file:///e:/hx/2/ui/horizontal_check_window.py#L293)
- **现象**：
  ```python
  if cache_key not in self._pixmap_cache:
      pixmap = self._pil_to_pixmap(img)
      scaled_pixmap = pixmap.scaled(...)
      self._pixmap_cache = {cache_key: scaled_pixmap}   # ← BUG
  ```
- **问题**：每次缓存未命中时，使用 `self._pixmap_cache = {cache_key: scaled_pixmap}` **整体替换**字典，而非 `self._pixmap_cache[cache_key] = scaled_pixmap` 增量插入。导致缓存永远只保留 1 个条目，每次翻页/缩放都重新缩放整页图像。
- **影响**：横校阶段每次翻页、缩放、悬停预览都会触发整页图像重新缩放（`O(页宽 × 页高)` 像素操作），严重卡顿。
- **对比**：同文件下方第 309 行 `self._pixmap_cache[pdf_cache_key] = pdf_scaled` 写法正确，证实第 293 行是笔误。
- **修复**：将第 293 行改为 `self._pixmap_cache[cache_key] = scaled_pixmap`。

#### 3.1.2 OCREngine 死代码引用未初始化属性

- **位置**：[2/ocr_engine/rapidocr_engine.py:30](file:///e:/hx/2/ocr_engine/rapidocr_engine.py#L30) 与 [2/ocr_engine/rapidocr_engine.py:68](file:///e:/hx/2/ocr_engine/rapidocr_engine.py#L68)
- **现象**：
  ```python
  def __init__(self):
      """软件2仅使用数据处理方法，不需要OCR模型。"""
      self.results = None     # 仅初始化 results

  def _recognize_page(self, page_image, page_idx, output_callback=None):
      ...
      result = self.engine(page_image, ...)   # ← 引用 self.engine
  ```
- **问题**：`__init__` 仅初始化 `self.results`，但 `_recognize_page`/`_recognize_page_batch` 方法仍引用 `self.engine`。若误调用会抛 `AttributeError`。
- **影响**：v2 不做 OCR 推理，故当前未触发；但属于死代码 + 潜在崩溃风险，且误导后续维护者。
- **修复**：删除 `_recognize_page`、`_recognize_page_batch`、`run_ocr`、`_optimize_char_boxes` 等推理相关方法，或显式 `raise NotImplementedError("v2 不支持 OCR 推理")`。

#### 3.1.3 C++ 版横校「返回」按钮触发悬空指针访问

- **位置**：[2_cpp/src/windows/mainwindow.cpp:245-256](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L245)
- **现象**：
  ```cpp
  void MainWindow::on_horizontal_back()
  {
      if (horiz_widget_) {
          stack_->removeWidget(horiz_widget_);
          horiz_widget_->deleteLater();
          horiz_widget_ = nullptr;
      }
      current_stage_ = 1;
      step_indicator_->set_current(1);
      stack_->setCurrentWidget(vert_widget_);   // ← vert_widget_ 可能已为 nullptr
  }
  ```
- **问题**：从横校返回纵校时，`vert_widget_` 在 `on_vertical_finished`（[mainwindow.cpp:148-152](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L148)）中已被 `deleteLater()` 释放并置空。此处调用 `stack_->setCurrentWidget(vert_widget_)` 会传入 `nullptr`，行为未定义（Qt 通常静默忽略，但仍属逻辑错误）。
- **影响**：从横校返回后界面可能卡住，无法回到纵校阶段。
- **修复**：返回纵校前需重建 `VerticalCheckWindow`（携带原 `char_slices_` 与 `ocr_results_`），或在纵校完成后不立即销毁纵校窗口，改为隐藏并保留。

---

### 3.2 建议修改（Major）

#### 3.2.1 PDFOutputWorker 继承 QThread 重写 run()，违反 worker object pattern

- **位置**：[2/pdf_processor/pdf_output.py:135](file:///e:/hx/2/pdf_processor/pdf_output.py#L135)
- **现象**：
  ```python
  class PDFOutputWorker(QThread):
      progress_signal = pyqtSignal(int, str)
      finished_signal = pyqtSignal()
      error_signal = pyqtSignal(str)
      def __init__(self, generator, corrected_chars, page_images, ...):
          ...
      def run(self):
          ...
  ```
- **问题**：继承 `QThread` 重写 `run()` 是 PyQt6 的反模式。Qt 官方推荐 **worker object pattern**：`Worker(QObject)` + `moveToThread(QThread)` + 信号槽触发 `run()` 槽函数。
- **影响**：
  - 无法在 Worker 中定义多个槽函数响应外部信号（如取消、暂停）
  - 错误处理与资源清理流程更复杂
  - 与项目内 `ImportWorker`（[2/ui/import_window.py](file:///e:/hx/2/ui/import_window.py)）的写法不一致，风格不统一
- **修复**：改为 `class PDFOutputWorker(QObject)` + `moveToThread()`，参考 `ImportWorker` 实现。

#### 3.2.2 v2 主线程同步调用 build_line_data 阻塞 UI

- **位置**：[2/main.py:165](file:///e:/hx/2/main.py#L165)
- **现象**：
  ```python
  def _setup_horizontal_stage(self):
      page_lines = self.ocr_engine.build_line_data(   # ← 主线程同步
          self.ocr_results, self.page_images, self.char_slices
      )
      self.horiz_widget = HorizontalCheckWindow(page_lines, self.page_images)
  ```
- **问题**：`build_line_data` 需遍历所有行 + 字符构建 `LineSlice`，并按页分组，大文档（数百页）时耗时数秒，期间 UI 完全冻结。
- **对比**：C++ 版 [2_cpp/src/windows/mainwindow.cpp:199-203](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L199) 使用 `QtConcurrent::run` + `QFutureWatcher` 异步执行，并显示模态进度对话框。
- **影响**：用户感知明显卡顿；纵校→横校切换时窗口无响应。
- **修复**：参考 C++ 版，用 `QThread` + worker object pattern 异步执行，并显示 `QProgressDialog`。

#### 3.2.3 C++ 横校使用裸指针存入 QGraphicsItem 上下文

- **位置**：[2_cpp/src/windows/horizontalcheckwindow.cpp:204](file:///e:/hx/2_cpp/src/windows/horizontalcheckwindow.cpp#L204) 与 [2_cpp/src/windows/horizontalcheckwindow.cpp:258](file:///e:/hx/2_cpp/src/windows/horizontalcheckwindow.cpp#L258)
- **现象**：
  ```cpp
  item->setData(0, QVariant::fromValue(
      static_cast<quintptr>(reinterpret_cast<quintptr>(ls_ptr))));
  ...
  return reinterpret_cast<LineSlice*>(ptr_val);
  ```
- **问题**：将 `LineSlice*` 裸指针转 `quintptr` 存入 `QGraphicsTextItem` 的 `data(0)`。若 `page_lines_`（`std::map<int, std::vector<LineSlice>>`）发生元素移动（如 `std::vector` 扩容、`sync_chars_with_text` 中 `ls.chars = std::move(new_chars)` 引发 `vector` 重建），则存入的指针变为悬空。
- **影响**：在「修改文字」对话框确认后调用 `render_page()` 重建场景前，若用户再次悬停同一 item，可能读到已释放内存。
- **修复**：改为存储 `(page_num, line_index)` 二元组，运行时通过 `page_lines_[page_num][line_index]` 查找；或用 `std::shared_ptr<LineSlice>` + `QVariant` 自定义类型注册。

#### 3.2.4 v1 LazyPageLoader LRU 实现效率低

- **位置**：[1/pdf_processor/pdf_loader.py:183-186](file:///e:/hx/1/pdf_processor/pdf_loader.py#L183)（v1 与 v2 同）
- **现象**：
  ```python
  while len(self._cache_order) > self._max_cache:
      oldest = self._cache_order.pop(0)   # ← O(n) 操作
      if oldest in self._cache:
          del self._cache[oldest]
  ```
- **问题**：使用 `list.pop(0)` 淘汰最旧页，时间复杂度 `O(n)`（n 为缓存大小）。C++ 版 [2_cpp/src/processors/lazy_page_loader.cpp](file:///e:/hx/2_cpp/src/processors/lazy_page_loader.cpp) 用 `std::list` + `unordered_map` 实现 `O(1)` LRU，明显更优。
- **影响**：当前 `max_cache=5` 影响小，但若调大缓存或扩展使用场景会成为瓶颈。
- **修复**：改用 `collections.OrderedDict` + `move_to_end()`。

---

### 3.3 仅供参考（Minor）

#### 3.3.1 测试脚本硬编码绝对路径

- **位置**：[2/test_import_thread.py:11-13](file:///e:/hx/2/test_import_thread.py#L11)
- **现象**：路径硬编码为 `c:\Users\E-VR\Documents\trae_projects\横校\...`，访问私有属性 `window._worker = None`、`window._on_load()`。
- **影响**：仅作者本机可用，无法在 CI 或他人机器运行。

#### 3.3.2 C++ 横校缓存键精度受限

- **位置**：[2_cpp/src/windows/horizontalcheckwindow.cpp:268](file:///e:/hx/2_cpp/src/windows/horizontalcheckwindow.cpp#L268)
- **现象**：`int cache_key = current_page_ * 10000 + static_cast<int>(zoom_level_ * 100);`
- **问题**：zoom_level 精度截断到 0.01，且若 `current_page_ * 10000 + zoom*100` 溢出 int 范围（page > 214747）会冲突。实际项目页数远小于此，但设计脆弱。

#### 3.3.3 v1/v2 代码大量重复

- `pdf_loader.py`、`styles.py`、`zoom_utils.py` 在 v1 和 v2 中几乎完全相同。
- `data_models.py` 中 v1 与 v2 仅 `CharSlice.score` 字段差异。
- 建议：抽取公共库或共享子模块，避免双份维护。

#### 3.3.4 v2 CharSliceMap 排序使用首字符 unicode

- **位置**：[2_cpp/src/windows/verticalcheckwindow.cpp:454-460](file:///e:/hx/2_cpp/src/windows/verticalcheckwindow.cpp#L454)
- **现象**：仅用 `a.at(0).unicode()` 排序，空字符串排最前。
- **问题**：多字符字符串（如「的。」）仅按首字符排序，次序不稳定。Python 版 [2/ui/vertical_check_window.py](file:///e:/hx/2/ui/vertical_check_window.py) 行为一致，但属于设计选择，不算 bug。

#### 3.3.5 C++ 版析构顺序风险

- **位置**：[2_cpp/src/windows/mainwindow.cpp:60-63](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L60)
- **现象**：`ocr_engine_ = new OCREngine();` 析构 `delete ocr_engine_;`。若构造函数 `setup_ui`/`setup_import_stage` 抛异常，`ocr_engine_` 泄漏。
- **影响**：Qt 异常罕见，但建议改用 `std::unique_ptr`。

#### 3.3.6 v2 精修阶段未实际实现

- **位置**：[2_cpp/src/windows/mainwindow.cpp:262-269](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L262)
- **现象**：C++ 版精修阶段为占位 `create_placeholder_widget("精修阶段（占位，后续任务实现）")`。
- **影响**：C++ 版当前无法完成端到端流程，缺少 PDF 输出能力。Python v2 的 `RefineWindow` 已实现。

---

## 4. 性能瓶颈与优化建议

### 4.1 主线程阻塞

| 位置 | 操作 | 影响 | 建议 |
|------|------|------|------|
| [2/main.py:165](file:///e:/hx/2/main.py#L165) | `build_line_data` 同步执行 | 大文档卡顿数秒 | 异步化（参考 C++ 版 QtConcurrent） |
| [2_cpp/src/windows/verticalcheckwindow.cpp:850](file:///e:/hx/2_cpp/src/windows/verticalcheckwindow.cpp#L850) | `flush_pending_modifications` 调 `refresh_label_list()` 重建整个字符列表 | 切换字符时短暂卡顿 | 增量更新而非全量重建 |

### 4.2 缓存设计问题

#### 4.2.1 横校 pixmap 缓存键设计

- **位置**：[2_cpp/src/windows/horizontalcheckwindow.cpp:122](file:///e:/hx/2_cpp/src/windows/horizontalcheckwindow.cpp#L122) 与 [2_cpp/src/windows/horizontalcheckwindow.cpp:268](file:///e:/hx/2_cpp/src/windows/horizontalcheckwindow.cpp#L268)
- **问题**：缓存键为 `(page, zoom_level)`，缩放级别变化即缓存失效。用户每次 Ctrl+滚轮缩放都会触发整页重缩放。
- **建议**：缓存原图 `QPixmap`，按需 `scaled()` 即时缩放（Qt 内部对 `scaled()` 有优化）；或采用多级缩放缓存策略。

#### 4.2.2 纵校 pixmap 缓存前缀匹配

- **位置**：[2_cpp/src/windows/verticalcheckwindow.cpp:836-841](file:///e:/hx/2_cpp/src/windows/verticalcheckwindow.cpp#L836)
- **现象**：
  ```cpp
  for (const QString& key : pixmap_cache_.keys()) {
      if (key.startsWith(char_text + ":") || ...) {
          keys_to_remove.append(key);
      }
  }
  ```
- **问题**：`QCache::keys()` 返回所有键，遍历是 `O(n)`（n 为缓存总条目数，最大 2000）。每次 flush 修改都遍历 2000 个字符串。
- **建议**：维护 `char_text → cache_keys` 反向索引，或直接 `clear()` 整个缓存（纵校修改是低频操作）。

### 4.3 OCR 引擎数据处理

- **位置**：[2_cpp/src/processors/ocr_engine.cpp:140-147](file:///e:/hx/2_cpp/src/processors/ocr_engine.cpp#L140)
- **问题**：`build_line_data` 中 `line_chars_map[line_id].push_back(char_data)` 按 `line_id` 全局分组，但 `line_id` 在页内唯一，跨页会冲突。后续循环 `page_lines_list` 时仍按 `line_id` 查 `line_chars_map[line_id]`，导致**跨页同 line_id 的字符被错误归并到第一页的行**。
- **影响**：多页文档中，第二页及之后的行可能引用第一页同 line_id 的字符，导致横校文字叠加错误。
- **修复**：`line_chars_map` 改为 `std::map<std::pair<int,int>, std::vector<json>>`（键为 `(page_num, line_id)`），并同步更新查找逻辑。
- **严重程度**：建议修改（Major），影响多页文档正确性。

### 4.4 PDF 渲染重复

- **位置**：[2/pdf_processor/pdf_loader.py:60-63](file:///e:/hx/2/pdf_processor/pdf_loader.py#L60)
- **现象**：`convert_to_images` 一次性渲染所有页面到内存，无并行化。
- **建议**：用 `QtConcurrent::mapped` 或 `concurrent.futures` 并行渲染；或采用懒加载（`LazyPageLoader` 已存在但未使用）。

### 4.5 横校悬停预览重复缩放

- **位置**：[2_cpp/src/windows/horizontalcheckwindow.cpp:402-419](file:///e:/hx/2_cpp/src/windows/horizontalcheckwindow.cpp#L402)
- **现象**：每次鼠标移动到新行都重新 `make_slice_pixmap` + `scaled()`，即使同一行已预览过。
- **现状**：已用 `slice_cache_id_` + `slice_cache_pixmap_` 做单条目缓存（仅缓存最近一次）。
- **建议**：扩展为按 `(page, line_index)` 的多条目缓存。

---

## 5. 代码质量评估

### 5.1 内聚性

| 模块 | 评估 | 说明 |
|------|------|------|
| `OCREngine`（v2/C++） | 中等 | 包含 JSON 加载、字符分组、行数据构建三类职责，建议拆分为 `JsonLoader` + `CharGrouper` + `LineBuilder` |
| `VerticalCheckWindow` | 中等 | 单文件 1261 行（C++），含 `PreviewGraphicsView` + `SliceItemWidget` + `VerticalCheckWindow` 三类，建议拆分头文件 |
| `HorizontalCheckWindow` | 较好 | 单一职责（横校交互） |
| `PDFProcessor` | 高 | 仅 PDF → 图像 |

### 5.2 耦合度

| 耦合点 | 评估 | 说明 |
|--------|------|------|
| MainWindow ↔ 阶段窗口 | 低 | 通过信号传递数据，窗口间无直接引用 |
| 阶段窗口 ↔ OCREngine | 中 | 窗口直接调用 `engine.build_line_data`，C++ 版 MainWindow 持有 `OCREngine*` |
| UI ↔ JSON | 高 | [2_cpp/src/windows/verticalcheckwindow.cpp:641-655](file:///e:/hx/2_cpp/src/windows/verticalcheckwindow.cpp#L641) 直接遍历 `ocr_results_.first`（`std::vector<json>`）查找行 box，UI 层操作 JSON 数据结构，违反层级 |
| datamodels ↔ nlohmann/json | 高 | [2_cpp/src/models/datamodels.h](file:///e:/hx/2_cpp/src/models/datamodels.h) 在数据结构内嵌 `to_json`/`from_json`，与 JSON 库强绑定 |

### 5.3 层级违规

1. **UI 层直接操作 JSON**：[2_cpp/src/windows/verticalcheckwindow.cpp:1095-1120](file:///e:/hx/2_cpp/src/windows/verticalcheckwindow.cpp#L1095) `update_ocr_results_char` 在 UI 窗口中直接遍历并修改 `ocr_results_.second`（`std::vector<json>`）。应封装到 `OCREngine::update_char(...)`。
2. **MainWindow 承担数据中转**：[2_cpp/src/windows/mainwindow.cpp:112-123](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L112) `on_import_finished` 拷贝 `page_images_`、`ocr_results_`、`char_slices_` 三份大数据到 MainWindow 成员，再传给下个阶段窗口。深拷贝 `std::vector<QImage>` 在大文档下耗时。建议用 `std::shared_ptr` 共享所有权。

### 5.4 重复代码

| 重复内容 | 位置 | 建议 |
|----------|------|------|
| `pdf_loader.py` | v1 与 v2 完全相同 | 抽取公共模块 |
| `styles.py` | v1 与 v2 完全相同 | 抽取公共模块 |
| `zoom_utils.py` / `zoom_utils.h` | 三版本逻辑相同 | — |
| `StepIndicator` | Python v2 `main.py` 与 C++ `stepindicator.cpp` 逻辑相同 | — |
| `flatten_bbox` | Python v2 `data_models.py` 与 C++ `datamodels.h` | — |

### 5.5 命名与风格

- Python v2 使用 `snake_case`，符合 PEP 8
- C++ 版混用：成员变量用 `trailing_underscore_`（如 `pdf_path_`），局部变量用 `snake_case`，符合 Google C++ Style Guide
- **不一致点**：C++ 信号用 `finished_signal`（带 `_signal` 后缀），Qt 惯例是 `finished`（无后缀），避免与 `QObject` 内置信号冲突时再加后缀

### 5.6 错误处理

- Python v2：广泛使用 `try/except` + 自定义 `RuntimeError`，覆盖 PDF 加载、JSON 解析、图像处理
- C++ 版：`try/catch (const std::exception&)` + `throw std::runtime_error`，但 `json::exception` 在 `show_line_preview` 中单独捕获（[verticalcheckwindow.cpp:755](file:///e:/hx/2_cpp/src/windows/verticalcheckwindow.cpp#L755)），其他地方未捕获可能崩溃

---

## 6. 数据持久化与数据库范式评估

### 6.1 数据持久化方案

项目使用 **JSON 文件** 作为持久化存储，无传统数据库。核心数据文件：

| 文件 | 结构 | 示例 |
|------|------|------|
| `lines.json` | 数组，每元素为一行记录 | [1/json/27424 智慧工地技术 正文1-1/lines.json](file:///e:/hx/1/json/27424%20%E6%99%BA%E6%85%A7%E5%B7%A5%E5%9C%B0%E6%8A%80%E6%9C%AF%20%E6%AD%A3%E6%96%871-1/lines.json) |
| `chars.json` / `newchar.json` | 数组，每元素为一字符记录 | — |

**lines.json 字段**（基于 [1/json/27424 智慧工地技术 正文1-1/lines.json:3-24](file:///e:/hx/1/json/27424%20%E6%99%BA%E6%85%A7%E5%B7%A5%E5%9C%B0%E6%8A%80%E6%9C%AF%20%E6%AD%A3%E6%96%871-1/lines.json#L3)）：

```json
{
  "line_id": 0,
  "text": "智慧工地技术",
  "score": 0.99988,
  "box": [[529.53, 437.16], [991.18, 437.16], [991.18, 521.64], [529.53, 521.64]],
  "page_num": 0
}
```

**chars.json 字段**（基于 [2_cpp/src/processors/ocr_engine.cpp:79-83](file:///e:/hx/2_cpp/src/processors/ocr_engine.cpp#L79) 解析逻辑）：

```json
{
  "char_id": 0,
  "line_id": 0,
  "page_num": 0,
  "char": "智",
  "score": 0.99,
  "box": [x1, y1, x2, y2]
}
```

### 6.2 候选键分析

#### 6.2.1 lines.json

- **关系模式**：`R_lines = { line_id, page_num, text, score, box }`
- **候选键**：`(page_num, line_id)` —— `line_id` 在页内唯一（由 [1/ocr_engine/rapidocr_engine.py:72-73](file:///e:/hx/1/ocr_engine/rapidocr_engine.py#L72) `line_id_counter` 每页重置确认）
- **函数依赖**：
  - `(page_num, line_id) → {text, score, box}`
  - 无其他非平凡函数依赖

#### 6.2.2 chars.json

- **关系模式**：`R_chars = { char_id, line_id, page_num, char, score, box }`
- **候选键**：`(page_num, line_id, char_id)` —— `char_id` 在行内唯一（由 `char_id_counter` 每行重置确认），`line_id` 在页内唯一
- **函数依赖**：
  - `(page_num, line_id, char_id) → {char, score, box}`
  - 无其他非平凡函数依赖

### 6.3 BCNF 评估

**BCNF 定义**：对关系模式 R 中的每个非平凡函数依赖 `X → Y`，X 必须是超键（superkey）。

#### lines.json

| 函数依赖 | 决定因素 | 是否超键 | 满足 BCNF |
|---------|---------|---------|----------|
| `(page_num, line_id) → text` | `(page_num, line_id)` | ✓ 候选键 | ✓ |
| `(page_num, line_id) → score` | `(page_num, line_id)` | ✓ 候选键 | ✓ |
| `(page_num, line_id) → box` | `(page_num, line_id)` | ✓ 候选键 | ✓ |

**结论**：lines.json 满足 BCNF ✓

#### chars.json

| 函数依赖 | 决定因素 | 是否超键 | 满足 BCNF |
|---------|---------|---------|----------|
| `(page_num, line_id, char_id) → char` | `(page_num, line_id, char_id)` | ✓ 候选键 | ✓ |
| `(page_num, line_id, char_id) → score` | `(page_num, line_id, char_id)` | ✓ 候选键 | ✓ |
| `(page_num, line_id, char_id) → box` | `(page_num, line_id, char_id)` | ✓ 候选键 | ✓ |

**结论**：chars.json 满足 BCNF ✓

### 6.4 潜在风险（非范式违规）

虽然满足 BCNF，但存在以下设计风险：

1. **跨表参照无强制约束**：chars.json 的 `(page_num, line_id)` 应外键引用 lines.json，但 JSON 无外键机制。若两文件不同步（如 lines.json 缺少某 line_id），chars.json 中对应字符将成为孤儿数据。
2. **page_num 冗余存储**：chars.json 每条记录都存 `page_num`，若 line_id 全局唯一则可省略。当前 line_id 页内唯一的设计使冗余必要。
3. **无事务保证**：纵校修改 `ocr_results_.second`（[2_cpp/src/windows/verticalcheckwindow.cpp:1095](file:///e:/hx/2_cpp/src/windows/verticalcheckwindow.cpp#L1095)）在内存中完成，但**不写回 chars.json**。若需保存校对结果，需额外实现持久化逻辑。
4. **score 精度丢失**：JSON 浮点数在 `double` ↔ `json` 间转换可能有精度损失，但 OCR 评分场景影响可忽略。

### 6.5 综合结论

**数据持久化方案满足 BC 范式（BCNF）**。lines.json 与 chars.json 均无传递依赖、部分依赖，所有非主属性完全依赖于候选键。但项目未使用关系型数据库，无外键约束与事务保证，校对结果的持久化能力有限。建议在后续迭代中：

- 引入 SQLite 存储校对结果，建立 `lines` 与 `chars` 两表 + 外键
- 或在 JSON 中增加版本号与校对时间戳，支持增量保存

---

## 7. 改进建议汇总

### 7.1 优先级 P0（必须修复）

| # | 问题 | 位置 | 修复方式 |
|---|------|------|----------|
| 1 | 横校 pixmap 缓存被整体替换 | [2/ui/horizontal_check_window.py:293](file:///e:/hx/2/ui/horizontal_check_window.py#L293) | 改为 `self._pixmap_cache[cache_key] = scaled_pixmap` |
| 2 | OCREngine 死代码引用 `self.engine` | [2/ocr_engine/rapidocr_engine.py:68](file:///e:/hx/2/ocr_engine/rapidocr_engine.py#L68) | 删除推理相关方法或抛 `NotImplementedError` |
| 3 | C++ 横校返回触发悬空指针 | [2_cpp/src/windows/mainwindow.cpp:255](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L255) | 返回前重建 VerticalCheckWindow 或保留实例 |

### 7.2 优先级 P1（建议修改）

| # | 问题 | 位置 | 修复方式 |
|---|------|------|----------|
| 4 | PDFOutputWorker 继承 QThread | [2/pdf_processor/pdf_output.py:135](file:///e:/hx/2/pdf_processor/pdf_output.py#L135) | 改为 worker object pattern |
| 5 | v2 build_line_data 主线程阻塞 | [2/main.py:165](file:///e:/hx/2/main.py#L165) | 异步化 + QProgressDialog |
| 6 | C++ 横校裸指针存入 QGraphicsItem | [2_cpp/src/windows/horizontalcheckwindow.cpp:204](file:///e:/hx/2_cpp/src/windows/horizontalcheckwindow.cpp#L204) | 改存 `(page, line_idx)` 索引 |
| 7 | LazyPageLoader LRU 效率低 | [1/pdf_processor/pdf_loader.py:184](file:///e:/hx/1/pdf_processor/pdf_loader.py#L184) | 改用 OrderedDict |
| 8 | C++ build_line_data 跨页 line_id 冲突 | [2_cpp/src/processors/ocr_engine.cpp:140-147](file:///e:/hx/2_cpp/src/processors/ocr_engine.cpp#L140) | line_chars_map 键改为 `(page_num, line_id)` |

### 7.3 优先级 P2（仅供参考）

| # | 问题 | 位置 | 修复方式 |
|---|------|------|----------|
| 9 | 测试脚本硬编码路径 | [2/test_import_thread.py:11](file:///e:/hx/2/test_import_thread.py#L11) | 改为命令行参数或环境变量 |
| 10 | v1/v2 代码重复 | pdf_loader.py / styles.py / zoom_utils.py | 抽取共享模块 |
| 11 | UI 层直接操作 JSON | [2_cpp/src/windows/verticalcheckwindow.cpp:1095](file:///e:/hx/2_cpp/src/windows/verticalcheckwindow.cpp#L1095) | 封装到 OCREngine |
| 12 | MainWindow 深拷贝大对象 | [2_cpp/src/windows/mainwindow.cpp:116-118](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L116) | 用 shared_ptr 共享所有权 |
| 13 | C++ 精修阶段未实现 | [2_cpp/src/windows/mainwindow.cpp:264](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L264) | 移植 RefineWindow |
| 14 | C++ MainWindow 裸 new OCREngine | [2_cpp/src/windows/mainwindow.cpp:54](file:///e:/hx/2_cpp/src/windows/mainwindow.cpp#L54) | 改用 unique_ptr |
| 15 | 校对结果未持久化 | — | 增加 SQLite 或 JSON 写回 |

### 7.4 架构性建议

1. **统一线程模式**：全项目采用 worker object pattern（`Worker(QObject)` + `moveToThread()`），废弃 `QThread` 继承重写 `run()` 的写法。
2. **引入数据层抽象**：将 JSON 读写、OCR 结果管理封装到独立的 `OcrResultRepository` 类，UI 层仅通过接口访问，避免 UI 直接操作 `nlohmann::json`。
3. **公共代码抽取**：v1 与 v2 的 `pdf_loader.py`、`styles.py`、`zoom_utils.py` 抽取为共享包，减少维护成本。
4. **校对结果持久化**：纵校/横校的修改应能写回 `newchar.json` 或数据库，当前仅在内存中修改，关闭程序即丢失。
5. **多页文档回归测试**：针对 §4.3 的跨页 `line_id` 冲突，建议补充多页测试用例验证。

---

## 附录：评估范围与依据

### 已通读文件清单

**1/ 目录（Python v1）**：
- `main.py`、`requirements.txt`、`models/data_models.py`、`ocr_engine/rapidocr_engine.py`、`pdf_processor/pdf_loader.py`、`ui/draw_box_window.py`、`ui/ocr_prepare_window.py`、`ui/styles.py`、`ui/zoom_utils.py`

**2/ 目录（Python v2）**：
- `main.py`、`requirements.txt`、`models/data_models.py`、`ocr_engine/rapidocr_engine.py`、`pdf_processor/pdf_loader.py`、`pdf_processor/pdf_output.py`、`ui/import_window.py`、`ui/vertical_check_window.py`、`ui/horizontal_check_window.py`、`ui/refine_window.py`、`ui/styles.py`、`ui/zoom_utils.py`、`test_import_thread.py`

**2_cpp/ 目录（C++ 版）**：
- `CMakeLists.txt`、`README.md`、`build.bat`、`deploy.bat`、`start.bat`、`resources/styles.qss`
- `src/main.cpp`、`src/models/datamodels.h`
- `src/processors/pdf_processor.h/cpp`、`src/processors/lazy_page_loader.h/cpp`、`src/processors/ocr_engine.h/cpp`、`src/processors/pdf_output_generator.h/cpp`
- `src/utils/json_utils.h/cpp`、`src/utils/style_manager.h/cpp`、`src/utils/zoom_utils.h/cpp`
- `src/windows/mainwindow.h/cpp`、`src/windows/importwindow.h/cpp`、`src/windows/verticalcheckwindow.h/cpp`、`src/windows/horizontalcheckwindow.h/cpp`、`src/windows/stepindicator.h/cpp`

### 评估依据

- **PyQt6 QThread 最佳实践**：Qt 官方文档推荐 worker object pattern（`QObject` + `moveToThread()`），不推荐继承 `QThread` 重写 `run()`（除非需要覆盖线程事件循环行为）
- **RapidOCR API**：`RapidOCR(params={...})`，支持 `return_word_box`、`return_single_char_box`（v1 使用）
- **PaddleOCR v5 API**：`ocr_version="PP-OCRv5"`，`result[0]["dt_polys"]`、`rec_texts`
- **BC 范式定义**：对每个非平凡函数依赖 `X → Y`，X 必须是超键
- **nlohmann/json**：v3.11.3，自定义 `to_json`/`from_json` 支持用户类型序列化
- **PoDoFo**：0.10.x API，与 0.9.x 接口不兼容

### 未读取/异常文件

无读取失败。`chars.json` 因体积过大（31MB）仅通过 Grep 抽样验证字段结构，未影响评估完整性。

---

**报告完成日期**：2026-07-05
**评估版本**：v1 / v2 / C++ 版（基于 `e:\hx\` 当前工作区状态）
