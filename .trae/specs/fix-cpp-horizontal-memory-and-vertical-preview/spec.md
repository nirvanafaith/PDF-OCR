# 修复 C++ 版横校内存爆炸与纵校预览异常 Spec

## Why

当前 C++ Qt5 重构版（`d:\hx\2_cpp`）存在两个严重阻断性 Bug：

1. **横校阶段内存爆炸 + UI 异常回退**：从纵校点击"下一步"进入横校后，UI 异常跳回导入界面，弹窗"正在准备横校数据"永不停止，内存逐渐占满至 100%。根因是 `build_line_data` 为每页每行创建 `QImage::copy()` 深拷贝（100 页文档约 1.7GB），而该 `LineSlice::image` 字段从未被 `HorizontalCheckWindow` 使用（其 `make_slice_pixmap` 按需从 `page_images_` 裁剪）。同时 `setup_horizontal_stage` 中的 `QApplication::processEvents()` 在模态进度对话框上下文中触发事件重入，导致 `on_import_finished` 被二次调用，UI 回退到导入界面。`QProgressDialog` 使用范围 (0,0) 表示"未知进度"且无更新机制，配合后台线程内存耗尽，弹窗永不关闭。

2. **纵校原图预览异常**：上方原图预览中的图片异常居左居上，无法自由移动。根因有四：(a) 平移计算使用 `mapToScene()` 获取两点，但 `centerOn()` 后变换矩阵已变，导致 delta 漂移；(b) `center_on_rect` 总是调用 `resetTransform()+scale()`，重置用户的缩放/平移状态（Python 版仅在 |target-current|>0.01 时重置）；(c) 场景坐标系使用页面坐标（非零原点），Python 版使用相对坐标（0 起算）；(d) 缺少 `fit_to_width()` 前置调用。

参考可正常工作的 Python 版（`d:\hx\software2`）进行对照修复。

## What Changes

### Bug #1：横校内存与 UI 修复
- **移除** `OcrEngine::build_line_data` 中对 `line_slice.image = page_image->copy(...)` 的赋值（消除冗余深拷贝）
- **重构** `MainWindow::setup_horizontal_stage` 为同步执行（对齐 Python `_setup_horizontal_stage`）
- **移除** `QProgressDialog`、`QtConcurrent::run`、`QFutureWatcher`、`QApplication::processEvents()`
- **简化** `MainWindow::on_line_data_ready`（合并入 `setup_horizontal_stage` 或移除）
- **移除** `MainWindow` 的 `horiz_watcher_` 成员及相关 include

### Bug #2：纵校预览修复
- **修复** `PreviewGraphicsView::mouseMoveEvent` 平移计算：改用视口 delta 除以缩放因子的方式（对齐 Python）
- **修复** `PreviewGraphicsView::center_on_rect`：仅在 |target_scale - current_scale| > 0.01 时调用 `resetTransform()+scale()`，否则保留当前变换仅 `centerOn()`
- **修复** `VerticalCheckWindow::show_line_preview` 场景坐标系：使用相对坐标（`setPos(0,0)`、`setSceneRect(0,0,w,h)`、红框 `rect_x = cx1 - crop_x1`）
- **新增** `show_line_preview` 中 `fit_to_width()` 前置调用（在 `center_on_rect()` 之前）

## Impact

- **受影响 spec**：无（所有现有 spec 均针对 Python 版本）
- **受影响代码**：
  - `d:\hx\2_cpp\src\processors\ocr_engine.cpp`（移除 image 深拷贝）
  - `d:\hx\2_cpp\src\processors\ocr_engine.h`（无需改动，签名不变）
  - `d:\hx\2_cpp\src\windows\mainwindow.cpp`（重构 setup_horizontal_stage）
  - `d:\hx\2_cpp\src\windows\mainwindow.h`（移除 horiz_watcher_ 成员）
  - `d:\hx\2_cpp\src\windows\verticalcheckwindow.cpp`（修复 PreviewGraphicsView 与 show_line_preview）
  - `d:\hx\2_cpp\src\models\datamodels.h`（无需改动，LineSlice::image 字段保留以备将来使用）

## ADDED Requirements

### Requirement: 横校数据构建零冗余内存
系统 SHALL 在构建横校数据时不为每行创建图像深拷贝，仅保留元数据（bbox/polygon/text/chars），横校窗口按需从 `page_images_` 裁剪。

#### Scenario: 大文档横校数据构建
- **WHEN** 用户处理 100 页 PDF 文档并从纵校进入横校
- **THEN** `build_line_data` 在主线程同步完成，内存增量 < 50MB（仅元数据）
- **AND** 不出现"正在准备横校数据"无限弹窗
- **AND** UI 不回退到导入界面

### Requirement: 横校阶段同步切换
系统 SHALL 在 `setup_horizontal_stage` 中同步执行 `build_line_data`，不使用 `QtConcurrent`、`QFutureWatcher`、`QProgressDialog` 或 `processEvents()`。

#### Scenario: 纵校完成进入横校
- **WHEN** 纵校完成信号触发 `on_vertical_finished`
- **THEN** `setup_horizontal_stage` 同步调用 `build_line_data` 并立即构造 `HorizontalCheckWindow`
- **AND** 主线程短暂阻塞（数据量小，<500ms）后 UI 切换到横校界面
- **AND** 不触发任何重入事件

### Requirement: 纵校原图预览自由平移
系统 SHALL 在 `PreviewGraphicsView` 中实现稳定的鼠标拖拽平移，平移 delta 基于视口坐标除以当前缩放因子计算，不受 `centerOn()` 后变换矩阵变化影响。

#### Scenario: 鼠标拖拽原图
- **WHEN** 用户在纵校原图预览中按住鼠标左键拖拽
- **THEN** 图像跟随鼠标移动，无漂移、无跳动
- **AND** 释放鼠标后停止平移

### Requirement: 红框居中初始视图保留用户缩放
系统 SHALL 在 `center_on_rect` 中仅当目标缩放与当前缩放差值 > 0.01 时重置变换矩阵，否则保留用户当前缩放仅调用 `centerOn()` 居中。

#### Scenario: 用户缩放后切换行
- **WHEN** 用户已手动放大原图，然后点击下一行
- **THEN** 红框居中显示，但用户缩放级别保留
- **AND** 不强制重置到 fit-to-width 缩放

### Requirement: 纵校预览相对坐标系
系统 SHALL 在 `show_line_preview` 中使用相对坐标系（0 起算）设置场景矩形与图元位置，红框坐标基于裁剪偏移量计算。

#### Scenario: 显示行预览
- **WHEN** `show_line_preview` 被调用显示某行
- **THEN** `pixmap_item->setPos(0, 0)`
- **AND** `setSceneRect(0, 0, width, height)`
- **AND** 红框 `rect_x = cx1 - crop_x1`，`rect_y = cy1 - crop_y1`
- **AND** 红框初始居中显示

## MODIFIED Requirements

### Requirement: 横校数据构建流程
原 C++ 实现使用 `QtConcurrent::run` + `QFutureWatcher` + `QProgressDialog` + `processEvents()` 异步构建。修改为对齐 Python 版的同步构建方式：直接在主线程调用 `build_line_data`，无进度对话框，无事件重入风险。

### Requirement: 纵校预览交互
原 C++ 实现平移使用 `mapToScene()` 双点计算导致漂移，`center_on_rect` 总是重置变换。修改为对齐 Python 版的视口 delta/缩放因子计算方式与条件重置变换。

## REMOVED Requirements

### Requirement: 横校数据构建进度对话框
**Reason**: Python 版无此对话框，且 C++ 实现因 (0,0) 范围永不更新导致永久卡死。
**Migration**: 移除 `QProgressDialog`，数据构建改为同步瞬时完成，无需进度反馈。
