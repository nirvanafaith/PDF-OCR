# 移除横校与精修阶段 Spec

## Why

当前 `d:\hx\2_cpp` 项目实现了完整的「导入 → 纵校 → 横校 → 精修」四阶段流程。用户希望暂时停用横校与精修两个阶段，仅保留导入与纵校功能，同时保持 UI 顶部的步骤指示器继续显示四阶段进度，并通过占位符页面告知用户后续阶段仍在开发中。这样可以减少二进制体积、消除 PDF 输出依赖（PoDoFo）、降低运行期内存占用，同时不影响核心校对功能。

## What Changes

- **删除** 横校阶段窗口实现：`horizontalcheckwindow.h/.cpp`
- **删除** 精修阶段窗口实现：`refinewindow.h/.cpp`
- **删除** 精修专用可拖拽文字组件：`movabletextitem.h/.cpp`
- **删除** PDF 输出生成器与工作线程：`pdf_output_generator.h/.cpp`、`pdf_output_worker.h/.cpp`
- **删除** `OCREngine::build_line_data` 方法（仅横校调用）
- **清理** `datamodels.h` 中仅被横校/精修使用的数据类型：`CorrectedLine`、`CorrectedChar`、`RefineTextItem`、`LineSlice`、`HorizontalCheckData`、`FinalCharList` 及其 JSON 序列化函数
- **新增** 轻量级占位窗口 `PlaceholderWindow`，显示阶段标题、描述文字与「上一步」「下一步」按钮
- **重构** `mainwindow.h/.cpp`：
  - 移除 `HorizontalCheckWindow`、`RefineWindow`、`OCREngine` 的前向声明、成员与槽函数
  - 移除 `setup_horizontal_stage`、`setup_refine_stage` 及对应槽实现
  - 新增 `PlaceholderWindow* horiz_placeholder_` 与 `refine_placeholder_` 成员
  - 新增 `setup_horizontal_placeholder`、`setup_refine_placeholder` 及对应槽函数
  - 调整 `on_vertical_finished` 进入横校占位页；精修占位页「完成」后重置回导入阶段
- **更新** `CMakeLists.txt`：从 `SOURCES`/`HEADERS` 列表移除已删除文件，添加 `placeholderwindow.cpp/.h`
- **保留** `StepIndicator` 四阶段指示器、`OCREngine::load_results_from_file` 与 `parse_and_group`、`PDFProcessor`、`lazy_page_loader` 及导入/纵校全部代码
- **保留** `main.cpp` 中 `OPENSSL_MODULES` 环境变量设置（防御性代码，移除风险高于收益）
- **保留** `build.bat`、`deploy.bat` 不变（CMake 自动发现源文件，部署脚本按通用规则复制 DLL）

**BREAKING**: 横校与精修阶段不再可用。原「纵校完成 → 横校」流程改为「纵校完成 → 横校占位页 → 精修占位页 → 完成重置」。PDF 输出功能完全移除。

## Impact

- **Affected specs**: 无（本仓库首次建立 spec）
- **Affected code**:
  - `src/windows/mainwindow.h/.cpp`（核心重构）
  - `src/windows/placeholderwindow.h/.cpp`（新增）
  - `src/processors/ocr_engine.h/.cpp`（删除 `build_line_data`）
  - `src/models/datamodels.h`（清理数据类型）
  - `CMakeLists.txt`（源文件列表更新）
  - 删除 10 个文件：`horizontalcheckwindow.{h,cpp}`、`refinewindow.{h,cpp}`、`movabletextitem.{h,cpp}`、`pdf_output_generator.{h,cpp}`、`pdf_output_worker.{h,cpp}`
- **Unaffected code**: `importwindow.*`、`verticalcheckwindow.*`、`stepindicator.*`、`pdf_processor.*`、`lazy_page_loader.*`、`utils/*`、`main.cpp`

## ADDED Requirements

### Requirement: 占位符窗口

系统 SHALL 提供一个轻量级 `PlaceholderWindow` QWidget，用于在已删除阶段的位置显示提示信息。

#### Scenario: 构造占位窗口
- **WHEN** 以 `(title, description, parent)` 构造 `PlaceholderWindow`
- **THEN** 窗口中央显示 `title`（大字号）与 `description`（普通字号），底部布局「上一步」「下一步」两个按钮

#### Scenario: 用户点击「下一步」
- **WHEN** 用户点击「下一步」按钮
- **THEN** 窗口发射 `next_signal()`

#### Scenario: 用户点击「上一步」
- **WHEN** 用户点击「上一步」按钮
- **THEN** 窗口发射 `back_signal()`

### Requirement: 横校占位阶段

系统 SHALL 在纵校完成后切换到横校占位页面，并将 `StepIndicator` 当前索引设为 2。

#### Scenario: 纵校完成进入横校占位
- **WHEN** `VerticalCheckWindow` 发射 `finished_signal`
- **THEN** 主窗口销毁纵校窗口，构造横校占位 `PlaceholderWindow`（标题「横校」、描述「横校功能正在开发中，敬请期待」），加入 `QStackedWidget` 并设为当前页，`StepIndicator::set_current(2)`

#### Scenario: 横校占位「下一步」
- **WHEN** 横校占位页发射 `next_signal`
- **THEN** 主窗口切换到精修占位页，`StepIndicator::set_current(3)`

#### Scenario: 横校占位「上一步」
- **WHEN** 横校占位页发射 `back_signal`
- **THEN** 主窗口销毁横校占位页，重建纵校窗口并设为当前页，`StepIndicator::set_current(1)`

### Requirement: 精修占位阶段

系统 SHALL 在横校占位「下一步」后切换到精修占位页面。

#### Scenario: 进入精修占位
- **WHEN** 横校占位页发射 `next_signal`
- **THEN** 主窗口构造精修占位 `PlaceholderWindow`（标题「精修」、描述「精修功能正在开发中，敬请期待」，「下一步」按钮文字改为「完成」），加入 `QStackedWidget` 并设为当前页

#### Scenario: 精修占位「完成」
- **WHEN** 精修占位页发射 `next_signal`
- **THEN** 主窗口清理所有阶段窗口与数据，重置 `current_stage_=0`，重新调用 `setup_import_stage()` 回到导入阶段

#### Scenario: 精修占位「上一步」
- **WHEN** 精修占位页发射 `back_signal`
- **THEN** 主窗口销毁精修占位页，切换回横校占位页，`StepIndicator::set_current(2)`

## REMOVED Requirements

### Requirement: 横校阶段交互窗口
**Reason**: 用户要求删除横校环节代码
**Migration**: 由 `PlaceholderWindow`（标题「横校」）替代，原 `HorizontalCheckWindow`、`OCREngine::build_line_data` 及相关数据类型 `LineSlice`、`CorrectedLine`、`HorizontalCheckData` 全部删除

### Requirement: 精修阶段交互窗口与 PDF 输出
**Reason**: 用户要求删除精修环节代码
**Migration**: 由 `PlaceholderWindow`（标题「精修」）替代，原 `RefineWindow`、`MovableTextItem`、`PDFOutputGenerator`、`PDFOutputWorker` 及相关数据类型 `RefineTextItem`、`CorrectedChar`、`FinalCharList` 全部删除；PDF 输出功能不再可用
