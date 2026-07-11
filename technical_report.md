# PDF-OCR 项目技术报告

本报告基于 hengxiao_tool2 代码库（下载于 2026-07-10，最新提交 `cab040d`）编写，全面审查了 software1（PyQt6 完整 OCR 管线）、software2（PyQt5 校对+精修）两大子系统的源代码实现，涵盖模块结构、核心算法、线程模型、数据模式 BCNF 验证、差异分析、代码质量评估及 C++ 加速模块迁移等内容。

**2026-07-11 更新**：C++ pybind11 加速模块已从共享的 `software_common/native/` 迁移至各子系统内部（`software1/native/` 和 `software2/native/`），实现完全解耦。software2 新增 H4 热点（`pil_to_qimage_buffer`）并接线 H3 批量裁切和 H4 像素转换。`software_common/` 目录已删除。

---

## 一、项目总览

### 1.1 仓库信息

| 属性 | 值 |
|------|-----|
| 源仓库 | `https://github.com/nirvanafaith/hengxiao_tool2` |
| 最新提交 | `cab040d` (2026-07-10) |
| 提交信息 | `fix: pdf_output 按 y 基线分组替代 line_id (CorrectedChar 无 line_id 属性)` |
| 总提交数 | 4 |
| 语言占比 | Python 88.8%, HTML 7.0%, C++ 3.3%, Other 0.9% |
| 目标仓库（推送） | `https://github.com/nirvanafaith/PDF-OCR` |

### 1.2 提交历史

| 提交 | 日期 | 信息 |
|------|------|------|
| `8a00a86` | 2026-07-06 | feat: C++ 加速优化版 software2 (hengxiao_tool2) |
| `a4ecea6` | 2026-07-10 | feat: PP-OCRv6升级 + 线程安全修复 + DPI对齐 + newchar优先恢复 |
| `90823c0` | 2026-07-10 | feat: DPI统一300 + DBSCAN行合并 + PyMuPDF双层PDF |
| `cab040d` | 2026-07-10 | fix: pdf_output 按 y 基线分组替代 line_id |

### 1.3 两大子系统（含内嵌 C++ 加速模块）

```
software1 (PyQt6)                       software2 (PyQt5)
┌─────────────────────────────┐         ┌─────────────────────────────┐
│ 完整 OCR 管线                │         │ 后处理/校对/精修             │
│ RapidOCR PP-OCRv6           │         │ 无 OCR 模型                 │
│ DPI=300                     │         │ DPI=200                     │
│ 画框→OCR准备                 │         │ 导入→纵校→横校→精修          │
│                             │         │                             │
│ ┌─ native/ (C++ 加速) ──┐   │         │ ┌─ native/ (C++ 加速) ──┐   │
│ │ H1: pixmap→QImage     │   │         │ │ H1: pixmap→QImage     │   │
│ │ H2: 字符框优化         │   │         │ │ H2: 字符框优化         │   │
│ │ H3: 批量裁切           │   │         │ │ H3: 批量裁切           │   │
│ │ 透明回退到 Python      │   │         │ │ H4: PIL→QImage buffer │   │
│ └───────────────────────┘   │         │ │ 透明回退到 Python      │   │
│                             │         │ └───────────────────────┘   │
└─────────────────────────────┘         └─────────────────────────────┘
```

**架构变更说明**：C++ 加速模块已从共享的 `software_common/native/` 迁移至各子系统内部，每个子系统独立持有自己的 `native/` 目录，实现完全解耦。software2 比 software1 多一个 H4 热点（`pil_to_qimage_buffer`），用于消除 PIL→QPixmap 转换链中的多次像素拷贝。

---

## 二、software1 详细分析（PyQt6 完整 OCR 管线）

### 2.1 模块结构

| 路径 | 行数 | 职责 |
|------|------|------|
| `main.py` | 197 | 主窗口，管理"画框→OCR准备"两阶段流程 |
| `ocr_engine/rapidocr_engine.py` | 1012 | OCR 引擎核心，基于 RapidOCR PP-OCRv6 |
| `ocr_engine/line_merger.py` | 130 | DBSCAN 行合并后处理 **（新增）** |
| `ocr_engine/char_refiner_cv.py` | 673 | OpenCV 连通域+投影法字符框精修 **（新增）** |
| `pdf_processor/pdf_loader.py` | 235 | PDF→PIL 图像渲染，LRU 惰性加载 |
| `models/data_models.py` | 249 | dataclass 数据模型 |
| `ui/draw_box_window.py` | 934 | 画框窗口，支持 MinerU JSON 导入 |
| `ui/ocr_prepare_window.py` | 709 | OCR 准备窗口，QThread+Worker 后台执行 |
| `ui/styles.py` | 241 | 全局 QSS 样式表 |
| `ui/zoom_utils.py` | 28 | Ctrl+滚轮缩放计算 |
| `native/` | - | C++ pybind11 加速模块（H1/H2/H3 + 透明回退） **（迁移至子系统内）** |

### 2.2 OCR 引擎核心算法

#### 2.2.1 RapidOCR PP-OCRv6 推理

- **检测参数**：`limit_side_len=2880`, `box_thresh=0.4`, `unclip_ratio=1.8`（DBNet）
- **线程安全**：`ThreadPoolExecutor(max_workers=3)`，每线程持有独立 RapidOCR 实例（线程局部变量），避免框坐标污染
- **GPU 检测**：通过探测 `cublasLt64_12.dll` 文件存在性判断 GPU 可用性
- **区域限定 OCR**：`regions` 参数支持只对指定矩形区域做 OCR，通过框重叠过滤

#### 2.2.2 DBSCAN 行合并 `line_merger.py` **（新增）**

```
输入: lines[], chars[]
策略:
  1. 按 page_num 分组行
  2. 每页内提取 y_center = (y1+y2)/2, height = y2-y1
  3. eps = median(heights) * 0.3（中位高度自适应阈值）
  4. DBSCAN(eps, min_samples=1) 对 y_center 聚类
  5. 同簇按 x_center 排序合并:
     - bbox = 并集(min x1/y1, max x2/y2)
     - text = ' '.join(行文本)
     - score = 按文本长度加权平均
  6. 全局 line_id/char_id 从 0 连续重映射
输出: (merged_lines, merged_chars)
```

**算法正确性**：DBSCAN `min_samples=1` 保证单行也能成簇；`eps` 基于中位高度自适应，避免固定阈值在不同字号下的退化。

#### 2.2.3 OpenCV 字符框精修 `char_refiner_cv.py` **（新增）**

替代旧的 numpy 逐字符边缘优化，采用多层次 CV 算法：

```
流程:
  1. 按 line_id 分组字符，按 char_id 排序
  2. 验证: 字符数 == len(line_text)（不匹配则跳过）
  3. 裁切行图像（+2px padding）
  4. Otsu 二值化(THRESH_BINARY_INV) + 形态学开运算(2x2 kernel)去噪
  5. connectedComponentsWithStats(connectivity=8) 获取连通域
  6. 过滤小连通域(宽<3 或 高<5)
  7. 合并过分割小连通域(宽度 < avg_width/3)
  8. 垂直投影法: col_sum = binary.sum(axis=0)
     - 1D 高斯平滑(5x1核)减少假谷值
     - 找连续低值区域(< max*0.05)中点作为字符边界
  9. 融合: 连通域粗框 + 投影谷值细化 x 边界
 10. 粘连字符: Distance Transform + Watershed 分割
     - 失败回退到投影法
 11. 验证: CV 切分数 == 字符数（不匹配保留原 OCR 框）
```

**关键设计**：切分数验证机制确保 CV 精修失败时保留原始 OCR 框，不会引入新错误。Watershed 优先 + 投影法回退的双策略保证鲁棒性。

### 2.3 线程模型

| 场景 | 实现 |
|------|------|
| OCR 推理 | `OCRWorker(QObject)` + `moveToThread(QThread)` |
| 数据加载 | `DataLoadWorker(QObject)` + `moveToThread(QThread)` |
| 批量 OCR | `ThreadPoolExecutor(max_workers=3)` + 线程局部 RapidOCR |

### 2.4 数据流

```
PDF → PDFProcessor.convert_to_images(dpi=300)
    → DrawBoxWindow (用户画框/导入JSON)
    → OCRPrepareWindow (OCR参数配置)
    → OCREngine.run_ocr(regions)
      → RapidOCR 检测+识别
      → _optimize_char_boxes (native/numpy)
      → char_refiner_cv.refine_chars_for_page (OpenCV精修)
      → line_merger.merge_lines (DBSCAN合并)
    → 输出 chars.json + lines.json
```

---

## 三、software2 详细分析（PyQt5 校对+精修）

### 3.1 模块结构

| 路径 | 行数 | 职责 |
|------|------|------|
| `main.py` | 623 | 主窗口，管理"导入→纵校→横校→精修"四阶段 |
| `ocr_engine/rapidocr_engine.py` | 372 | 精简版引擎（无OCR模型，仅数据处理） |
| `pdf_processor/pdf_loader.py` | 235 | PDF→PIL 图像（DPI=200） |
| `pdf_processor/pdf_output.py` | 265 | PyMuPDF 双层 PDF 输出 **（重写）** |
| `models/data_models.py` | 338 | 数据模型（含 to_dict/from_dict） |
| `ui/import_window.py` | 458 | 导入窗口（JSON加载/工程恢复） |
| `ui/vertical_check_window.py` | 2281 | 纵校窗口（最复杂模块） |
| `ui/horizontal_check_window.py` | 1587 | 横校窗口（双视图滚动同步） |
| `ui/refine_window.py` | 2035 | 精修窗口（8手柄缩放+PDF输出） |
| `ui/styles.py` | 291 | 全局 QSS 样式表 |
| `ui/zoom_utils.py` | 28 | Ctrl+滚轮缩放计算 |
| `session_manager.py` | 290 | 工程会话管理 **（新增）** |
| `undo_commands.py` | 384 | 撤销/重做命令 **（新增）** |
| `runtime_hook_stderr.py` | 41 | PyInstaller runtime hook **（新增）** |
| `hengxiao_tool2.spec` | 141 | PyInstaller 打包配置 **（新增）** |
| `native/` | - | C++ pybind11 加速模块（H1/H2/H3/H4 + 透明回退） **（迁移至子系统内）** |

### 3.2 四阶段流程

```
Stage 0: 导入 (ImportWindow)
  → 自动探测 lines.json + newchar.json/chars.json
  → ImportWorker 后台加载: PDF→图像 + JSON解析 + 字符分组
  → 或: SessionManager.load() 恢复已保存工程

Stage 1: 纵校 (VerticalCheckWindow) — 竖排文本
  → 按字符内容分组，逐组检查
  → 修改文字、删除错误字符、新增字符、红框拖拽/缩放
  → 8手柄非对称命中检测（角优先于边）
  → O(1) 索引表 + 双层 LRU 缓存(pixmap 2000 + 行预览 100)
  → QUndoStack 撤销/重做（4种命令）

Stage 2: 横校 (HorizontalCheckWindow) — 横排文本
  → 双 QGraphicsView 并排（左=文字叠加，右=原始PDF）
  → 4向滚动同步
  → 方向自适应字号（按宽高比判断横排/竖排）
  → 画框模式（行框重定位/新文本段）
  → QUndoStack（3种命令）

Stage 3: 精修 (RefineWindow)
  → 8手柄缩放 + 拖拽移动 + 右键删除
  → 跨页 undo（_item_id_map 唯一ID映射）
  → 三种工具模式: hand / drag / add_text
  → PDFOutputWorker 后台生成红色+透明双层 PDF
  → QUndoStack（4种命令）
```

### 3.3 会话管理 `session_manager.py` **（新增）**

```
工程路径: ~/Documents/hengxiao_tool2_projects/<PDF名>_<时间戳>/
工程文件:
  project.json       - 断点状态（阶段、源PDF、保存时间）
  ocr_results.json   - OCR 识别结果（lines + chars）
  char_slices.json   - 纵校字符切片
  page_lines.json    - 横校行数据
  refine_items.json  - 精修文字项

特性:
  - 首次保存自动生成工程文件夹名
  - 60秒自动保存定时器（静默失败不弹窗）
  - 断点恢复: 根据 stage 跳转到对应阶段
  - skip_build 模式: 断点恢复时跳过 build_line_data
  - CharSlice.image 恢复: 按 bbox 从 page_images 重新裁切
```

### 3.4 撤销/重做系统 `undo_commands.py` **（新增）**

| 阶段 | 命令类 | COMMAND_ID | 功能 |
|------|--------|-----------|------|
| 纵校 | `ModifyCharCommand` | 1001 | 修改字符文本 |
| 纵校 | `DeleteSliceCommand` | 1002 | 删除切片 |
| 纵校 | `ModifyRedBoxCommand` | 1003 | 红框拖拽/缩放 |
| 纵校 | `MoveSliceCommand` | 1004 | 切片移动到新字符集合 |
| 横校 | `ModifyLineTextCommand` | 2001 | 修改行文本 |
| 横校 | `ToggleIgnoreCommand` | 2002 | 忽略/取消忽略 |
| 横校 | `RelocateLineFrameCommand` | 2003 | 重新定位行框 |
| 精修 | `MoveTextItemCommand` | 3001 | 移动文字项 |
| 精修 | `ResizeTextItemCommand` | 3002 | 缩放文字项 |
| 精修 | `DeleteTextItemCommand` | 3003 | 删除文字项 |
| 精修 | `AddTextItemCommand` | 3004 | 新增文字项 |

**设计模式**：命令对象只调用窗口的 `_apply_xxx` 辅助方法，不直接操作数据。`QUndoStack.push()` 时首次执行 `redo()`，`undo()` 反向操作。`mergeWith()` 默认返回 False（不合并连续命令）。

### 3.5 PyMuPDF 双层 PDF 输出 `pdf_output.py` **（重写）**

经 context7 查询 PyMuPDF 官方文档验证，TextWriter API 使用正确：

```python
# 1. 打开原 PDF，保留矢量层
doc = fitz.open(pdf_path)

# 2. 按 page_num 分组字符（过滤 ignored）
# 3. 按 y 基线分组（CorrectedChar 无 line_id，用 y 中心聚类）
line_groups = self._group_by_baseline(page_chars)
# threshold = max(median_height * 0.3, 5.0)

# 4. 逐行 TextWriter.append + write_text
tw = fitz.TextWriter(page.rect)
tw.append((pdf_x, pdf_y), line_text, font=font, fontsize=font_size)

if text_color == "transparent":
    tw.write_text(page, render_mode=3)      # 不可见但可选/可复制
else:
    tw.write_text(page, render_mode=0, color=(1, 0, 0))  # 可见红色

# 5. 字体: 优先 msyh.ttc（微软雅黑），回退 fitz.Font('china-s')
```

**API 验证结果**（context7 `/pymupdf/pymupdf`）：
- `TextWriter(rect)` 构造函数接受 rect-like 参数 ✓
- `append(pos, text, font, fontsize)` 参数与官方文档一致 ✓
- `write_text(page, color, opacity, overlay)` 接受 color 参数 ✓
- `render_mode` 是 PyMuPDF 的文本渲染模式参数（0=填充, 3=不可见）✓

### 3.6 线程模型

| 场景 | 实现 |
|------|------|
| PDF 导入 | `ImportWorker(QObject)` + `moveToThread()` |
| 行数据构建 | `BuildLineDataWorker(QObject)` + `moveToThread()` |
| PDF 输出 | `PDFOutputWorker(QThread)` 重写 `run()` |

---

## 四、C++ 加速模块详细分析（各子系统内嵌 native/）

### 4.1 架构变更概述

C++ pybind11 加速模块已从共享的 `software_common/native/` 迁移至各子系统内部：

| 子系统 | native 路径 | 热点 | 说明 |
|--------|------------|------|------|
| software1 | `software1/native/` | H1, H2, H3 | 完整 OCR 管线加速 |
| software2 | `software2/native/` | H1, H2, H3, **H4** | 校对/精修加速，新增 H4 像素转换 |

**迁移收益**：
- 完全解耦：各子系统独立持有 native 模块，不再共享依赖
- 路径简化：`_try_native()` 从 6 级目录上溯查找改为直接 `from native import ...`
- 按需扩展：software2 新增 H4 热点不影响 software1
- `software_common/` 目录已删除

### 4.2 模块结构（每个子系统内一致）

| 路径 | 行数 | 职责 |
|------|------|------|
| `native/__init__.py` | 130+ | Python 入口，延迟加载+透明回退 |
| `native/include/hxnative.h` | 53+ | C++ 内部声明 |
| `native/src/hxnative.cpp` | 442+ | pybind11 绑定+实现 |
| `native/tests/test_golden.py` | 295 | 逐字节等价性验证 |
| `native/tests/bench_perf.py` | 304 | 性能基准对比 |
| `native/_hxnative.cp38-win_amd64.pyd` | 二进制 | 编译后的扩展（Python 3.8） |
| `native/cmakelists.txt` | - | CMake 构建配置 |

### 4.3 四个加速热点

| 热点 | 函数 | 替代 | GIL | 子系统 |
|------|------|------|-----|--------|
| H1 | `pixmap_bytes_to_qpixmap_buffer` | fitz pixmap→QImage 直通，跳过 PIL | 不释放（访问Python buffer） | software1, software2 |
| H2 | `optimize_char_boxes` | 整页字符边界框批量优化，替代 numpy 逐字符切片 | 释放（纯C++计算） | software1, software2 |
| H3 | `batch_crop_qimage` | 批量字符裁切，替代 PIL.Image.crop | 释放（纯C++计算） | software1, software2 |
| **H4** | `pil_to_qimage_buffer` | **PIL→QImage buffer 统一转换，消除多次 tobytes/convert 拷贝** | 不释放（访问Python buffer） | **software2 独有** |

### 4.4 H4 详细设计（software2 新增）

**问题**：`_pil_to_pixmap` 原实现链路为 `PIL Image → convert("RGBA") → tobytes() → H1 pixmap_bytes_to_qpixmap_buffer → QImage`，存在多次像素拷贝。

**H4 方案**：接受原始像素 buffer + 源模式(RGB/RGBA) + 尺寸，C++ 内完成 RGB→RGBA 扩展（alpha=255）和行间紧凑化，一次调用替代整个转换链。

```cpp
// hxnative.cpp H4 核心逻辑
py::bytes pil_to_qimage_buffer_impl(py::object samples, int width, int height,
                                     std::string mode, int stride) {
    // 1. 获取 buffer 指针
    // 2. RGB 模式: 扩展为 RGBA (每像素追加 0xFF)
    // 3. RGBA 模式: 行间紧凑化（stride > width*4 时拷贝紧凑行）
    // 4. 返回紧凑 RGBA bytes，直接用于 QImage(Format_RGBA8888)
}
```

**接线位置**：`vertical_check_window.py`、`horizontal_check_window.py`、`refine_window.py` 的 `_pil_to_pixmap()` 方法。

### 4.5 H3 批量裁切接线（software2 新启用）

H3 此前已导入但从未调用。迁移后正式接线至三处：

| 位置 | 文件 | 方法 | 说明 |
|------|------|------|------|
| 字符分组裁切 | `ocr_engine/rapidocr_engine.py` | `parse_and_group` | 按页收集所有字符 bbox，每页一次 `batch_crop_qimage` |
| 重新裁切 | `main.py` | `_recrop_char_slice_images` | 同上模式，批量裁切替代逐字符 crop |
| 行数据构建 | `ocr_engine/rapidocr_engine.py` | `build_line_data` | 行循环内收集 crop_coords，页面循环结束后批量裁切 |

**回退策略**：native 不可用时或调用失败时，自动回退到逐字符 `PIL.Image.crop()`。

### 4.6 透明回退机制

```python
# native/__init__.py 核心逻辑（各子系统内一致）
_native = None

def _try_load():
    global _native
    if _native is not None:
        return _native
    try:
        _native = importlib.import_module("._hxnative", __package__)
    except Exception:
        _native = False  # 标记为不可用
    return _native if _native else None

def pixmap_bytes_to_qpixmap_buffer(samples, width, height, n, stride=0):
    native = _try_load()
    if native is None:
        return None  # 调用方自行回退到 PIL
    try:
        return native.pixmap_bytes_to_qimage_buffer(samples, width, height, n, stride)
    except Exception:
        return None  # 运行期错误降级
```

**调用方简化**（迁移后）：
```python
# 迁移前：6 级目录上溯查找 software_common
for _ in range(6):
    _candidate = os.path.join(_candidate, "..")
    ...
from software_common.native import has_native, ...

# 迁移后：直接本地导入
from native import has_native, ...
```

**设计优点**：所有公共函数在 native 不可用时返回 `None`，调用方透明回退到 Python/PIL/numpy 实现，应用功能与外观完全不变。

### 4.7 构建方式

```bat
:: software1
cd software1\native
cmake -S . -B build -A x64
cmake --build build --config Release

:: software2
cd software2\native
cmake -S . -B build -A x64
cmake --build build --config Release

:: Windows 7 SP1 兼容模式
cmake -S . -B build -A x64 -DHXNATIVE_WIN7_COMPAT=ON
```

---

## 五、JSON 数据模式与 BCNF 验证

### 5.1 lines.json

```json
{
  "line_id": 0,
  "page_num": 0,
  "text": "智慧工地技术",
  "score": 0.99988,
  "box": [[529.53, 437.16], [991.18, 437.16], [991.18, 521.64], [529.53, 521.64]]
}
```

| 字段 | 类型 | 函数依赖 |
|------|------|---------|
| line_id | int | ← 候选键的一部分 |
| page_num | int | ← 候选键的一部分 |
| text | string | → 依赖 (page_num, line_id) |
| score | float | → 依赖 (page_num, line_id) |
| box | [[x,y],...] | → 依赖 (page_num, line_id) |

**候选键**：(page_num, line_id)
**BCNF 验证**：所有非主属性（text, score, box）都完全且仅依赖候选键，无传递依赖 → **满足 BCNF** ✓

### 5.2 chars.json / newchar.json

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

| 字段 | 类型 | 函数依赖 |
|------|------|---------|
| char_id | int | ← 候选键的一部分 |
| line_id | int | ← 候选键的一部分 |
| page_num | int | ← 候选键的一部分 |
| char | string | → 依赖 (page_num, line_id, char_id) |
| score | float | → 依赖 (page_num, line_id, char_id) |
| box | [x1,y1,x2,y2] | → 依赖 (page_num, line_id, char_id) |

**候选键**：(page_num, line_id, char_id)
**BCNF 验证**：所有非主属性都完全且仅依赖候选键 → **满足 BCNF** ✓

### 5.3 工程会话文件

| 文件 | 键 | 非主属性 | BCNF |
|------|-----|---------|------|
| project.json | source_pdf_path | stage, breakpoints, saved_at, project_name | ✓ |
| ocr_results.json | (文件级) | lines[], chars[] | ✓ |
| char_slices.json | char_text | [slice_dict, ...] | ✓ |
| page_lines.json | page_num_str | [line_dict, ...] | ✓ |
| refine_items.json | page_num_str | [item_dict, ...] | ✓ |

所有 JSON 模式均无传递依赖、部分依赖，**满足 BCNF** ✓

---

## 六、与当前代码的差异分析

### 6.1 新增模块

| 模块 | 说明 |
|------|------|
| `software1/native/` | C++ pybind11 加速（H1/H2/H3 + 透明回退）**（迁移至子系统内）** |
| `software2/native/` | C++ pybind11 加速（H1/H2/H3/**H4** + 透明回退）**（迁移至子系统内，含新增 H4）** |
| `software1/ocr_engine/line_merger.py` | DBSCAN 行合并 |
| `software1/ocr_engine/char_refiner_cv.py` | OpenCV 字符框精修 |
| `software2/session_manager.py` | 工程会话管理（60s自动保存） |
| `software2/undo_commands.py` | 11种 QUndoCommand 撤销/重做 |
| `software2/runtime_hook_stderr.py` | PyInstaller stderr 重定向 |
| `software2/hengxiao_tool2.spec` | PyInstaller 打包配置 |

### 6.2 重大修改

| 文件 | 旧实现 | 新实现 |
|------|--------|--------|
| `software2/pdf_processor/pdf_output.py` | reportlab 生成 PDF | PyMuPDF TextWriter 双层 PDF |
| `software2/main.py` | PyQt6, 无会话管理 | PyQt5, 集成 SessionManager |
| `software1/ocr_engine/rapidocr_engine.py` | PP-OCRv5, numpy 优化 | PP-OCRv6, native+numpy, 线程安全 |
| `software1/pdf_processor/pdf_loader.py` | DPI 默认值 | DPI=300 统一 |
| `software2/pdf_processor/pdf_loader.py` | DPI 默认值 | DPI=200, 抑制 MuPDF 字体错误 |
| **C++ 模块架构** | `software_common/native/` 共享 | **迁移至 `software1/native/` 和 `software2/native/`，完全解耦** |
| **software2 H3 接线** | H3 已导入但从未调用 | **正式接线至 parse_and_group / _recrop_char_slice_images / build_line_data** |
| **software2 H4 新增** | 无 H4，PIL→QPixmap 多次拷贝 | **新增 `pil_to_qimage_buffer`，C++ 内完成 RGB→RGBA 扩展+紧凑化** |
| **software2 UI `_pil_to_pixmap`** | H1 + Python tobytes/convert 链 | **改用 H4 一次调用，QImage 统一 Format_RGBA8888** |
| **software1/2 `_try_native()`** | 6 级目录上溯查找 software_common | **直接 `from native import ...`，路径查找逻辑移除** |
| **software2 `hengxiao_tool2.spec`** | 引用 software_common/native | **改为引用 native/，binaries/pathex/hiddenimports 全部更新** |
| **`software_common/`** | 共享 C++ 模块目录 | **已删除（确定无用后移除）** |

### 6.3 PyQt 版本变化

| 子系统 | 当前版本 | 新版本 |
|--------|---------|--------|
| software1 | PyQt6 | PyQt6（不变） |
| software2 | PyQt6 | **PyQt5**（变更，为 Win7 兼容） |

---

## 七、代码质量评估

### 7.1 优点

1. **高内聚低耦合**：模块划分清晰（models/ocr_engine/pdf_processor/ui 四层），窗口间通过 Qt 信号通信，无直接引用
2. **透明回退设计**：C++ 加速模块缺失时自动回退到 Python，功能完全不变
3. **完善的撤销/重做**：11种命令类覆盖全部交互操作，COMMAND_ID 便于扩展
4. **工程会话持久化**：60s 自动保存 + 断点恢复，解决"关闭即丢失"问题
5. **多层次缓存**：LRU 缓存（PDF页 5/pixmap 2000/行预览 100）+ O(1) 索引表
6. **线程安全**：线程局部 RapidOCR 实例避免框坐标污染
7. **算法鲁棒性**：CV 精修有切分数验证 + Watershed/投影法双策略 + 失败保留原框

### 7.2 已识别问题

| # | 严重度 | 问题 | 位置 |
|---|--------|------|------|
| 1 | 中 | 文件过长：vertical_check(2281行)、refine(2035行)、horizontal(1587行) | software2/ui/ |
| 2 | 中 | 代码重复：`_try_native()` 在4个UI文件中逐字重复（迁移后路径查找已简化，但函数体仍重复） | draw_box/vertical/horizontal/refine |
| 3 | 中 | 代码重复：`zoom_utils.py`、`styles.py`、`data_models.py` 在 software1/2 高度重复 | 两版本间 |
| 4 | 低 | PyQt5/PyQt6 分裂：同一项目内 Qt 版本不一致 | software1 vs software2 |
| 5 | 低 | 硬编码路径：`.spec` 中 `_hxnative_pyd = 'd:/hx/...'` | hengxiao_tool2.spec |
| 6 | 低 | 硬编码字体：`"Microsoft YaHei"` 跨平台不可用 | refine_window.py |
| 7 | 低 | 动态属性 `_ignored` 不在 dataclass 字段中 | data_models.py |
| 8 | 低 | GPU 检测通过 DLL 文件名而非功能探测 | rapidocr_engine.py |
| 9 | 信息 | H1 "零拷贝"名不副实：std::string 构造时复制了 buffer | hxnative.cpp |
| 10 | 信息 | `CharListDelegate` 硬编码 `#b3d9ff` 绕过 QSS | vertical_check_window.py |

### 7.3 算法性能评估

| 算法 | 时间复杂度 | 评估 |
|------|-----------|------|
| DBSCAN 行合并 | O(n log n)（scikit-learn 实现） | 优秀，eps 自适应 |
| OpenCV 字符精修 | O(n×h×w)（n=行数） | 良好，有切分数验证保护 |
| PyMuPDF 双层 PDF | O(pages × chars_per_page) | 优秀，TextWriter 批量写入 |
| LRU 缓存 | O(1) 查找/插入 | 优秀 |
| O(1) 索引表 | O(n) 构建, O(1) 查找 | 优秀 |
| Watershed 分割 | O(h×w) per 连通域 | 良好，有投影法回退 |

---

## 八、下载覆盖计划

### 8.1 保留项（不覆盖）

- `.trae/specs/` — 历史规格文档
- `.trae/documents/` — 历史计划文档
- `.trae/scripts/` — 辅助脚本
- `创意提案文档.md` — 参赛材料（不上传 GitHub）
- `showcase.html` — 参赛材料（不上传 GitHub）

### 8.2 覆盖项

- `software1/` — 全量覆盖（含 `native/` C++ 加速模块）
- `software2/` — 全量覆盖（含 `native/` C++ 加速模块，含 H4）
- `README.md` — 覆盖
- `.gitignore` — 覆盖
- `technical_report.md` — 更新（基于本报告）
- **`software_common/` — 已删除，不再推送**

### 8.3 GitHub 更新计划

- 目标仓库：`https://github.com/nirvanafaith/PDF-OCR`
- 推送文件：software1/（含 native/）、software2/（含 native/）、README.md、technical_report.md、.gitignore
- 不推送：`.trae/`、`创意提案文档.md`、`showcase.html`、`backup_native_migration_20260711/`
