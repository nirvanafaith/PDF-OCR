# Tasks

- [x] Task 1: 移除 `OcrEngine::parse_and_group` 中的 CharSlice 图像深拷贝
  - [x] SubTask 1.1: 定位 `d:\hx\2_cpp\src\processors\ocr_engine.cpp` 中 `parse_and_group` 方法（约 56-118 行）
  - [x] SubTask 1.2: 删除 `slice.image = page_images[page_num].copy(crop_x1, crop_y1, ...)` 赋值块（约 107-112 行）
  - [x] SubTask 1.3: 保留 `CharSlice` 其他字段（page_num、bbox、text、line_id、char_id、score）的赋值
  - [x] SubTask 1.4: 若 `img_width`/`img_height` 局部变量在删除后变为未使用，仅移除服务于拷贝的变量或保留必要边界校验逻辑
  - [x] SubTask 1.5: 运行 sequentialthinking 验证此改动与 Python `parse_and_group` 在内存语义上的差异（Qt 深拷贝 vs PIL 延迟裁剪）
  - [x] SubTask 1.6: 运行 context7 查询 Qt5 QImage::copy 内存行为，确认按需裁剪是正确优化方向

- [x] Task 2: 修改 `VerticalCheckWindow::char_slice_to_pixmap` 为按需裁剪
  - [x] SubTask 2.1: 定位 `d:\hx\2_cpp\src\windows\verticalcheckwindow.cpp` 中 `char_slice_to_pixmap`（约 785-791 行）
  - [x] SubTask 2.2: 将实现改为从 `page_images_[slice.page_num]` 按 `slice.bbox` 裁剪
  - [x] SubTask 2.3: 运行 sequentialthinking 验证此改动不会破坏 `render_current_page` 和 `pixmap_cache_` 缓存逻辑
  - [x] SubTask 2.4: 运行 context7 查询 Qt5 QPixmap::fromImage 与 QImage::copy 最佳实践

- [x] Task 3: 为纵校窗口关键路径添加异常捕获
  - [x] SubTask 3.1: 在 `VerticalCheckWindow` 构造函数中的 `QTimer::singleShot(0, ...)` lambda 外层添加 `try/catch (const std::exception&)`
  - [x] SubTask 3.2: 在 `on_label_selected` 函数体最外层添加 `try/catch`
  - [x] SubTask 3.3: 在 `render_current_page` 函数体最外层添加 `try/catch`
  - [x] SubTask 3.4: 确认 `d:\hx\2_cpp\src\utils\logger.h` 中 `LOG_EX_ERROR` 宏可用，且 `QMessageBox` 已在 verticalcheckwindow.cpp 中 include
  - [x] SubTask 3.5: 运行 sequentialthinking 验证异常捕获位置覆盖所有可能导致闪退的入口（初始化、标签切换、翻页）

- [x] Task 4: 构建与端到端验证
  - [x] SubTask 4.1: 设置 PATH 环境变量 `C:\msys64\mingw64\bin` 优先
  - [x] SubTask 4.2: 在 `d:\hx\2_cpp\build` 执行 CMake 配置与 Ninja 构建
  - [x] SubTask 4.3: 修复编译错误（无编译错误）
  - [x] SubTask 4.4: 将新生成的 `hengxiao_tool2.exe` 复制到 `deploy` 目录
  - [x] SubTask 4.5: 通过 `run.bat` 启动应用，验证能正常启动到导入界面
  - [ ] SubTask 4.6: 导入真实 PDF + JSON，验证进入纵校阶段不闪退（需用户真实数据验证）
  - [ ] SubTask 4.7: 监控内存使用情况，确认导入阶段内存增量显著降低（需用户真实数据验证）
  - [x] SubTask 4.8: 运行 sequentialthinking 总结验证结果

# Task Dependencies

- Task 2 依赖 Task 1（移除 image 深拷贝后，按需裁剪才成为唯一图像来源）
- Task 3 与 Task 1/2 基本独立，但应基于 Task 2 完成后的代码添加异常捕获
- Task 4 依赖 Task 1-3 全部完成
