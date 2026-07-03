# Checklist

## Bug #1：横校内存与 UI 修复验证

- [x] `OcrEngine::build_line_data` 中不再出现 `line_slice.image = page_image->copy(...)` 赋值
- [x] `LineSlice::image` 字段在 `datamodels.h` 中保留为 `std::optional<QImage>`（未来扩展用）
- [x] `MainWindow::setup_horizontal_stage` 不再创建 `QProgressDialog`
- [x] `MainWindow::setup_horizontal_stage` 不再调用 `QApplication::processEvents()`
- [x] `MainWindow::setup_horizontal_stage` 不再使用 `QtConcurrent::run`
- [x] `MainWindow::setup_horizontal_stage` 不再创建 `QFutureWatcher`
- [x] `MainWindow::setup_horizontal_stage` 同步调用 `build_line_data` 并立即构造 `HorizontalCheckWindow`
- [x] `MainWindow::on_line_data_ready` 已移除或合并（无悬挂槽函数）
- [x] `mainwindow.h` 中 `horiz_watcher_` 成员已移除
- [x] `mainwindow.h` 中 `QtConcurrent`、`QFutureWatcher` 相关 include 已移除（若无其他用途）
- [x] 编译通过，无 `horiz_watcher_` 未定义引用错误
- [ ] 运行时从纵校进入横校：UI 不回退到导入界面（需用户真实数据验证）
- [ ] 运行时从纵校进入横校：无"正在准备横校数据"无限弹窗（需用户真实数据验证）
- [ ] 运行时从纵校进入横校：内存增量 < 100MB（100 页文档）（需用户真实数据验证）
- [ ] 横校界面正常显示双视图与切片（需用户真实数据验证）

## Bug #2：纵校预览修复验证

- [x] `PreviewGraphicsView::mouseMoveEvent` 不再使用 `mapToScene()` 双点计算
- [x] `PreviewGraphicsView::mouseMoveEvent` 使用 `transform().m11()` 作为缩放因子
- [x] 平移 delta 计算公式为 `(event->pos() - pan_start_pos_) / current_scale`
- [ ] 鼠标拖拽原图：无漂移、无跳动、跟随鼠标（需用户 GUI 交互验证）
- [x] `PreviewGraphicsView::center_on_rect` 包含 `abs(target_scale - current_scale) > 0.01` 条件判断
- [x] 条件不满足时仅 `centerOn()`，不调用 `resetTransform()`/`scale()`
- [x] 条件满足时对 `target_scale` 进行 `min_zoom_`/`max_zoom_` 范围裁剪
- [ ] 用户手动缩放后切换行：缩放级别保留（需用户 GUI 交互验证）
- [x] `show_line_preview` 中 `pixmap_item->setPos(0, 0)`（相对坐标）
- [x] `show_line_preview` 中 `setSceneRect(0, 0, width, height)`（相对坐标）
- [x] 红框坐标基于裁剪偏移：`rect_x = cx1 - strip_left`，`rect_y = cy1 - strip_top`
- [x] `show_line_preview` 在 `center_on_rect()` 前调用 `fit_to_width()`
- [ ] 初始状态红框居中显示（需用户 GUI 交互验证）
- [ ] 原图可手动自由挪动、放缩（需用户 GUI 交互验证）
- [ ] 无边界限制或固定定位（需用户 GUI 交互验证）

## 构建与运行验证

- [x] CMake 配置成功
- [x] Ninja 构建成功，无警告（除第三方库）
- [x] 部署目录包含所有必需 DLL（含 libpodofo、legacy.dll、ossl-modules）
- [x] `run.bat` 启动器正常启动应用
- [x] 日志路径 `%LOCALAPPDATA%\hengxiao_tool2\logs\hengxiao_tool2.log` 正常写入
- [ ] 端到端：导入 PDF → 纵校（预览正常）→ 横校（无崩溃、无内存爆炸）流程完整（需用户真实数据验证）
