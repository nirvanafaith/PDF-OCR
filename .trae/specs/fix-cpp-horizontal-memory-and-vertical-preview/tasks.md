# Tasks

- [x] Task 1: 移除 `OcrEngine::build_line_data` 中的冗余图像深拷贝
  - [x] SubTask 1.1: 定位 `d:\hx\2_cpp\src\processors\ocr_engine.cpp` 中 `line_slice.image = page_image->copy(x1, y1, x2 - x1, y2 - y1)` 所在行（约 239-247 行）
  - [x] SubTask 1.2: 删除该 copy 赋值块（保留边界坐标计算日志若存在），`line_slice.image` 保持默认 `std::nullopt`
  - [x] SubTask 1.3: 确认 `LineSlice::image` 字段在 `datamodels.h` 中保留（未来可能使用），仅停止填充
  - [x] SubTask 1.4: 运行 sequentialthinking 验证此改动不影响 `HorizontalCheckWindow::make_slice_pixmap`（其从 `page_images_` 按需裁剪，不读取 `ls->image`）

- [x] Task 2: 重构 `MainWindow::setup_horizontal_stage` 为同步执行
  - [x] SubTask 2.1: 在 `d:\hx\2_cpp\src\windows\mainwindow.cpp` 中移除 `QProgressDialog` 创建代码
  - [x] SubTask 2.2: 移除 `QApplication::processEvents()` 调用（消除重入风险）
  - [x] SubTask 2.3: 移除 `QFutureWatcher` 创建、`connect` 与 `setFuture` 代码
  - [x] SubTask 2.4: 移除 `QtConcurrent::run` lambda，改为直接同步调用 `ocr_engine_->build_line_data(ocr_results_, page_images_, char_slices_)`
  - [x] SubTask 2.5: 同步构造 `HorizontalCheckWindow` 并切换 stacked widget（对齐 Python `_setup_horizontal_stage`）
  - [x] SubTask 2.6: 在 `d:\hx\2_cpp\src\windows\mainwindow.h` 中移除 `horiz_watcher_` 成员声明及相关 include（`QtConcurrent`、`QFutureWatcher`）
  - [x] SubTask 2.7: 移除或合并 `MainWindow::on_line_data_ready` 槽函数（其逻辑并入 `setup_horizontal_stage`）
  - [x] SubTask 2.8: 运行 sequentialthinking 验证无其他代码引用 `horiz_watcher_` 或 `on_line_data_ready`

- [x] Task 3: 修复 `PreviewGraphicsView::mouseMoveEvent` 平移计算漂移
  - [x] SubTask 3.1: 在 `d:\hx\2_cpp\src\windows\verticalcheckwindow.cpp` 中定位 `PreviewGraphicsView::mouseMoveEvent`（约 83-94 行）
  - [x] SubTask 3.2: 替换 `mapToScene()` 双点计算为视口 delta 除以缩放因子方式（对齐 Python `vertical_check_window.py`）：
    ```cpp
    QPointF delta = event->pos() - pan_start_pos_;
    double current_scale = transform().m11();
    if (current_scale != 0) {
        QPointF delta_scene(delta.x() / current_scale, delta.y() / current_scale);
        centerOn(pan_start_center_ - delta_scene);
    }
    ```
  - [x] SubTask 3.3: 运行 context7 查询 Qt5 QGraphicsView 确认 `transform().m11()` 为当前 x 缩放因子
  - [x] SubTask 3.4: 运行 sequentialthinking 验证此修复在等比缩放（m11==m22）下行为正确

- [x] Task 4: 修复 `PreviewGraphicsView::center_on_rect` 保留用户缩放
  - [x] SubTask 4.1: 在 `verticalcheckwindow.cpp` 中定位 `center_on_rect`（约 127-150 行）
  - [x] SubTask 4.2: 添加条件判断：仅当 `target_scale > 0 && std::abs(target_scale - current_scale) > 0.01` 时执行 `resetTransform(); scale(target_scale, target_scale);`
  - [x] SubTask 4.3: 否则保留当前变换，仅调用 `centerOn(target_rect.center())`
  - [x] SubTask 4.4: 对 `target_scale` 进行 `min_zoom_`/`max_zoom_` 范围裁剪
  - [x] SubTask 4.5: 运行 sequentialthinking 验证此修复不会破坏 `fit_to_width` 路径（其内部也会调用 `center_on_rect` 或类似逻辑）

- [x] Task 5: 修复 `VerticalCheckWindow::show_line_preview` 场景坐标系并新增 fit_to_width 前置调用
  - [x] SubTask 5.1: 在 `verticalcheckwindow.cpp` 中定位 `show_line_preview`（约 636-758 行）
  - [x] SubTask 5.2: 将 `pixmap_item->setPos(strip_left, strip_top)` 改为 `pixmap_item->setPos(0, 0)`
  - [x] SubTask 5.3: 将 `setSceneRect(strip_left, strip_top, strip_pixmap.width(), strip_pixmap.height())` 改为 `setSceneRect(0, 0, strip_pixmap.width(), strip_pixmap.height())`
  - [x] SubTask 5.4: 将红框坐标从页面坐标 `rect_x = cx1; rect_y = cy1;` 改为相对坐标 `rect_x = cx1 - strip_left; rect_y = cy1 - strip_top;`
  - [x] SubTask 5.5: 在 `center_on_rect()` 调用之前新增 `fit_to_width()` 调用（对齐 Python `show_line_preview` 末尾的 `fit_to_width(); center_on_rect(...)` 顺序）
  - [x] SubTask 5.6: 运行 context7 查询 Qt5 确认 `fit_to_width` 在 QGraphicsView 中的典型实现（`fitInView` with `Qt::KeepAspectRatio`）
  - [x] SubTask 5.7: 运行 sequentialthinking 验证红框居中 + 用户可自由拖拽缩放无边界限制

- [x] Task 6: 构建与端到端验证
  - [x] SubTask 6.1: 设置 PATH 环境变量 `C:\msys64\mingw64\bin` 优先
  - [x] SubTask 6.2: 在 `d:\hx\2_cpp\build` 执行 CMake 配置与 Ninja 构建
  - [x] SubTask 6.3: 修复编译错误（无编译错误）
  - [x] SubTask 6.4: 部署到 `deploy` 目录（手动复制 exe，deploy.bat 有编码问题但 deploy 目录已存在）
  - [x] SubTask 6.5: 启动应用验证无崩溃（PID 5900，内存 44MB，日志正常）
  - [ ] SubTask 6.6: 点击"下一步"进入横校，验证无 UI 回退、无无限弹窗、内存稳定（需用户真实数据验证）
  - [x] SubTask 6.7: 运行 sequentialthinking 总结验证结果

# Task Dependencies

- Task 2 依赖 Task 1（移除 image 深拷贝后，同步构建才不会内存爆炸）
- Task 3、4、5 相互独立，可并行（均位于 verticalcheckwindow.cpp 但修改不同函数）
- Task 6 依赖 Task 1-5 全部完成
