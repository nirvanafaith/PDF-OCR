# 修复 C++ 版纵校导入后闪退 Spec

## Why

用户通过 `run.bat` 启动应用，导入 PDF + JSON 后进入纵校阶段时应用直接闪退。根因已定位：`OCREngine::parse_and_group`（`d:\hx\2_cpp\src\processors\ocr_engine.cpp`）为 `chars.json` 中的每个字符都执行 `QImage::copy()` 深拷贝并保存到 `CharSlice::image`；进入纵校后，`VerticalCheckWindow` 初始化时通过 `QTimer::singleShot` 异步渲染首字符组切片，该路径（`refresh_label_list` → `on_label_selected` → `render_current_page`）未捕获异常，且在已占用大量内存的情况下再分配 UI 控件与 `QPixmap`，极易触发 `std::bad_alloc` 等内存异常并直接终止进程。

Python 参考实现虽也在 `parse_and_group` 中裁剪字符图像，但 PIL 的 `crop()` 返回的是延迟/视图对象，不会立即深拷贝所有像素；而 Qt 的 `QImage::copy()` 会立即分配完整像素内存。C++ 版需要改为按需裁剪，与 `HorizontalCheckWindow` 处理 `LineSlice` 的方式保持一致。

## What Changes

- **移除** `OcrEngine::parse_and_group` 中对 `slice.image = page_images[page_num].copy(...)` 的赋值（消除字符级图像深拷贝）
- **修改** `VerticalCheckWindow::char_slice_to_pixmap`：不再读取 `CharSlice::image`，改为根据 `slice.page_num` 与 `slice.bbox` 从 `page_images_` 按需裁剪并返回 `QPixmap`
- **保留** `CharSlice::image` 字段（`std::optional<QImage>`）在 `datamodels.h` 中不变，以备未来扩展；反序列化时继续保持 `std::nullopt`
- **添加** 纵校窗口关键初始化路径的异常捕获：
  - 构造函数中 `QTimer::singleShot(0, ...)` lambda
  - `on_label_selected`
  - `render_current_page`
  捕获 `std::exception`，写入日志并通过 `QMessageBox` 向用户提示，避免未捕获异常导致闪退

## Impact

- **受影响 spec**：`fix-cpp-horizontal-memory-and-vertical-preview`（同项目同期修复，处理方式一致）
- **受影响代码**：
  - `d:\hx\2_cpp\src\processors\ocr_engine.cpp`（停止 CharSlice 图像深拷贝）
  - `d:\hx\2_cpp\src\windows\verticalcheckwindow.cpp`（按需裁剪 + 异常捕获）
  - `d:\hx\2_cpp\src\windows\verticalcheckwindow.h`（无需改动签名，仅实现变更）
  - `d:\hx\2_cpp\src\models\datamodels.h`（无需改动，字段保留）

## ADDED Requirements

### Requirement: 字符切片零冗余内存
系统 SHALL 在 `parse_and_group` 中不为每个字符创建图像深拷贝，仅保留字符元数据（page_num、bbox、text、line_id、char_id、score）。字符图像 SHALL 在纵校窗口渲染时按需从 `page_images_` 裁剪。

#### Scenario: 大文档导入后进入纵校
- **WHEN** 用户导入包含大量字符（如 10,000+）的 PDF + JSON 并进入纵校
- **THEN** 导入阶段内存增量 < 100MB（仅元数据）
- **AND** 进入纵校阶段不闪退
- **AND** 首字符组切片正常显示

### Requirement: 纵校窗口关键路径异常捕获
系统 SHALL 在纵校窗口初始化与切片渲染的关键路径上捕获 `std::exception`，记录错误日志并向用户显示友好提示，而不是让未捕获异常终止进程。

#### Scenario: 纵校初始化或渲染时发生异常
- **WHEN** `QTimer::singleShot` 触发的初始化、标签选中或页面渲染过程中抛出异常
- **THEN** 异常被捕获并记录到日志
- **AND** 弹出 `QMessageBox::critical` 提示用户"纵校界面初始化失败：{错误信息}"
- **AND** 应用不闪退

### Requirement: 按需裁剪字符图像
系统 SHALL 在 `char_slice_to_pixmap` 中根据 `slice.page_num` 和 `slice.bbox` 从 `page_images_` 裁剪，返回对应的 `QPixmap`；若 `page_num` 无效或 `bbox` 无效，返回空 `QPixmap`。

#### Scenario: 渲染字符切片
- **WHEN** `render_current_page` 需要显示某个字符切片
- **THEN** `char_slice_to_pixmap` 从对应页面图像按 bbox 裁剪
- **AND** 切片缩略图正确显示
- **AND** 翻页时通过 `pixmap_cache_` 缓存避免重复裁剪

## MODIFIED Requirements

### Requirement: 字符切片构建流程
原 `parse_and_group` 为每个字符深拷贝图像并存储到 `CharSlice::image`。修改为仅存储元数据，图像在渲染阶段按需裁剪，显著降低导入阶段内存占用。

### Requirement: 纵校窗口错误处理
原纵校窗口初始化与渲染路径未捕获异常。修改后在关键路径添加 `try/catch`，将异常转化为用户可感知的错误提示，避免进程崩溃。

## REMOVED Requirements

### Requirement: 导入阶段为每个字符预生成图像
**Reason**：Python 版 PIL crop 为轻量视图，而 Qt `QImage::copy()` 为立即深拷贝，大文档下内存爆炸并导致纵校初始化崩溃。
**Migration**：字符图像改为纵校渲染时按需从 `page_images_` 裁剪，`CharSlice::image` 字段保留但不再填充。
