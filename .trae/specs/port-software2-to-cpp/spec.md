# 软件2 C++ 重构规格说明书

## Why

当前软件2基于 Python + PyQt6 实现，在长期维护、部署分发和运行性能方面存在改进空间。用户要求使用 C++ 对其进行完整重构，同时保留现有所有功能与 UI 排版，以提升执行效率、降低运行时依赖，并为后续功能扩展提供更坚实的基础。由于目标运行环境包含 Windows 7，重构后的可执行程序必须兼容 Windows 7 SP1 64 位，因此选择 Qt5 作为 GUI 框架。

## What Changes

- 使用 C++ 与 Qt6 重写软件2全部源代码，保留原四阶段流程：**导入 → 纵校 → 横校 → 精修**。
- 保留所有窗口的 UI 排版、控件布局、样式风格及交互行为（包括步骤指示器、工具栏、右键菜单、对话框、进度提示等）。
- 保留数据模型结构（CharSlice、LineSlice、CorrectedChar、CorrectedLine、RefineTextItem 等）及其字段语义。
- 保留 JSON 导入格式：继续兼容 `lines.json` 与 `newchar.json`/`chars.json`。
- 保留 PDF 渲染与输出能力：导入 PDF 生成页面图像，最终生成红色文字版与透明文字版 PDF。
- 保留 OCR 数据解析与字符分组逻辑；软件2本身不运行 OCR 模型，仅加载并处理已有 OCR 结果。
- 构建系统改为 CMake，工程目录结构清晰规范。
- 关键重构优化：
  - 使用 Qt 信号槽替代 Python pyqtSignal。
  - 使用 C++ 标准容器（`std::vector`、`std::map`、`std::optional` 等）替代 Python list/dict。
  - 使用 RAII 管理资源（PDF 文档、图像、线程）。
  - 使用 nlohmann/json 处理 JSON 序列化/反序列化。
  - 使用 MuPDF（或 PDFium）替代 PyMuPDF 进行 PDF 渲染；使用 PoDoFo 或 PDFium 替代 reportlab 生成 PDF。

## Impact

- 新增能力：独立的 C++ 可执行程序，无需 Python 运行时即可运行软件2校对流程。
- 受影响代码：软件2全部 Python 源文件（`main.py`、`ui/*.py`、`models/*.py`、`ocr_engine/*.py`、`pdf_processor/*.py`）。
- 不影响：软件1 及其他项目代码。
- 构建与部署：需要新增 CMake 构建配置及第三方依赖获取脚本。

## ADDED Requirements

### Requirement: C++ 工程骨架

The system SHALL provide a CMake-based C++ project under `软件2_cpp/` (or an equivalent path) that compiles into a standalone GUI executable on Windows.

#### Scenario: Build succeeds
- **WHEN** the developer runs the documented CMake configure and build steps
- **THEN** the project compiles without errors and produces `横校工具2.exe` (or equivalent binary)

### Requirement: 数据模型移植

The system SHALL provide C++ structs/classes equivalent to the existing Python dataclasses in `models/data_models.py`, including but not limited to:

- `TextLine`
- `OCRPageResult`
- `OCRResult`
- `CharSlice`
- `LineSlice`
- `CorrectedChar`
- `CorrectedLine`
- `RefineTextItem`
- `TextBox`
- `flatten_bbox` utility

#### Scenario: Model compatibility
- **WHEN** the application loads existing `lines.json` and `chars.json`
- **THEN** the C++ models represent the same data semantics as the Python version

### Requirement: 导入阶段

The system SHALL implement the Import stage as a Qt widget equivalent to `ImportWindow`, supporting:

- Selecting a PDF file via file dialog.
- Auto-detecting `lines.json` and `newchar.json`/`chars.json` in the PDF directory.
- Loading PDF pages as `QImage` objects at 200 DPI.
- Loading JSON OCR results in a background worker thread.
- Grouping characters into a map keyed by character text.
- Emitting a signal with `(pageImages, ocrResults, charSlices)` when loading completes.
- Displaying progress logs in a read-only text area.

#### Scenario: Import completes successfully
- **WHEN** the user selects a PDF and clicks "开始加载"
- **THEN** the application renders the PDF, loads JSON, groups characters, and advances to the 纵校 stage

### Requirement: 纵校阶段

The system SHALL implement the Vertical Check stage as a Qt widget equivalent to `VerticalCheckWindow`, supporting:

- Left-side character list grouped by unique character text.
- Right-side grid of character slice thumbnails (90×90 pixels, 8 columns).
- Low-score slices highlighted with a yellow background and orange border.
- Top original-image preview area showing the PDF horizontal strip containing the selected line, with a red rectangle centered on the selected character.
- Mouse drag panning without boundary limits and Ctrl+wheel zooming in the preview area.
- Clicking a slice to modify its text via a dialog; deleting a slice via right-click menu.
- Keeping the UI on the current character group after modification or deletion.
- "下一步" button to emit the updated `charSlices` and `ocrResults`.
- "返回" button to go back to the Import stage.

#### Scenario: Modify a slice
- **WHEN** the user clicks a slice and changes its text
- **THEN** the slice text updates, the character list re-sorts/regroups as needed, and the view remains in the current character group

#### Scenario: Preview interactions
- **WHEN** the user drags the preview image
- **THEN** the image can be moved outside the preview area without boundary restriction

### Requirement: 横校阶段

The system SHALL implement the Horizontal Check stage as a Qt widget equivalent to `HorizontalCheckWindow`, supporting:

- Side-by-side views: left shows overlaid corrected text on page image; right shows original PDF page image.
- Page navigation via previous/next buttons, page label, and spin box.
- Toolbar buttons: back, previous, next, hand tool (pan), zoom in/out, zoom percentage input, fit width, fit height.
- Rendering each character in its bbox with Microsoft YaHei font, auto-shrinking if text exceeds bbox width.
- Ignored lines rendered in gray.
- Mouse hover to show a tooltip/preview of the original line slice image.
- Right-click context menu to modify line text or ignore/unignore a line.
- Linked scrolling between left and right views.
- "完成横校" button to emit a list of `CorrectedLine` objects.

#### Scenario: Modify line text
- **WHEN** the user right-clicks a line and edits its text
- **THEN** the displayed text updates and the corrected line data reflects the change

### Requirement: 精修阶段

The system SHALL implement the Refine stage as a Qt widget equivalent to `RefineWindow`, supporting:

- Page-by-page display of text items as movable/resizable red rectangles.
- Toolbar: back, previous, next, hand tool, drag/edit tool, add text tool, delete, zoom in/out/fit.
- MovableTextItem behavior: drag to move, drag handles to resize, double-click to edit text, right-click to delete.
- "导出 PDF" button that generates two PDFs (red text and transparent text) in a background thread with a progress dialog.
- "完成" button to finish the workflow and return to the Import stage.

#### Scenario: Export PDFs
- **WHEN** the user clicks "导出 PDF"
- **THEN** the application generates a red-text PDF and a transparent-text PDF, showing progress, and reports success when done

### Requirement: 全局样式与行为

The system SHALL preserve the existing application-wide stylesheet (Bootstrap 5 / Windows classic theme) and window behaviors, including:

- Step indicator at the top showing 导入/纵校/横校/精修 progress.
- Minimum window size of 1200×800.
- Consistent button, toolbar, input, list, and menu styles.
- Modal dialogs for warnings, text edits, and confirmations.

### Requirement: PDF 输出

The system SHALL implement PDF generation equivalent to `PDFOutputGenerator`, supporting:

- Drawing each page image as the background.
- Drawing corrected characters over the image in red or fully transparent.
- Auto-fitting font size to the character bbox width.
- Generating both a red-text PDF and a transparent-text PDF in sequence.
- Progress callbacks for UI progress dialog.

### Requirement: Windows 7 SP1 兼容性

The system SHALL be fully compatible with Windows 7 SP1 64-bit as a deployment target. To guarantee this:

- The GUI framework SHALL be Qt5 (Qt 5.12 LTS or Qt 5.15.2 with Windows 7 compatible configuration), not Qt6.
- The C++ standard SHALL be C++14 or C++17; all language features and standard library APIs used SHALL be supported by the selected compiler on Windows 7.
- The compiler toolchain SHALL be compatible with Windows 7 SP1 runtime. Recommended options:
  - MSVC 2017 / MSVC 2019 with Windows SDK that supports Windows 7 target (e.g., Windows 10 SDK with `_WIN32_WINNT=0x0601`).
  - MinGW-w64 7.x/8.x with `-D_WIN32_WINNT=0x0601`.
- The project SHALL define `_WIN32_WINNT=0x0601` and `WINVER=0x0601` globally to prevent accidental use of Windows 8/10-only APIs.
- System and third-party API calls SHALL be audited to avoid APIs introduced after Windows 7 (e.g., Direct2D 1.1+ features, certain COM interfaces, newer shell APIs).
- Third-party libraries SHALL be selected from versions known to run on Windows 7 SP1:
  - nlohmann/json v3.11.3 (header-only, no platform API dependency).
  - MuPDF/PoDoFo binaries built for Windows 7 runtime, or built from source with the same Windows target macros.
- Qt5 platform plugin and required image format plugins SHALL be deployed alongside the executable; Qt6-specific plugins SHALL NOT be used.
- The application SHALL NOT require Universal CRT (UCRT) features only available on Windows 8/10 when using MinGW; when using MSVC, the Visual C++ Redistributable for MSVC 2015-2019/2015-2022 is acceptable on Windows 7 SP1 with updates.

#### Scenario: Runs on Windows 7 SP1
- **WHEN** the built executable is launched on a Windows 7 SP1 64-bit machine with the required runtime installed
- **THEN** the application starts, all four workflow stages function, and PDF rendering/export completes without crashes or missing API errors

## MODIFIED Requirements

### Requirement: 运行环境与构建方式

原 Python 版本依赖 Python 解释器及 pip 包（PyQt6、PyMuPDF、reportlab、Pillow）。重构后：

- The system SHALL be buildable with CMake on Windows.
- The system SHALL statically or dynamically link Qt6 Widgets, Qt6 Core, Qt6 Gui.
- The system SHALL link a PDF rendering library (MuPDF or PDFium) and a PDF generation library (PoDoFo or PDFium).
- The system SHALL use nlohmann/json for JSON parsing.

**Reason**: Move from Python runtime to native C++ executable.
**Migration**: Provide build instructions and dependency setup scripts; keep input/output file formats unchanged so users can continue using existing JSON/PDF workflows.

## REMOVED Requirements

### Requirement: Python 运行时依赖

**Reason**: The application is being rewritten in C++.
**Migration**: The new C++ executable replaces the old Python entry point; data files (PDF/JSON) remain compatible.
