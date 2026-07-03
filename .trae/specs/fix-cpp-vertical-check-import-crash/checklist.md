# Checklist

## 根因修复验证

- [ ] `OcrEngine::parse_and_group` 中不再出现 `slice.image = page_images[page_num].copy(...)` 赋值
- [ ] `CharSlice` 的 page_num、bbox、text、line_id、char_id、score 字段仍正确填充
- [ ] `CharSlice::image` 字段在 `datamodels.h` 中保留为 `std::optional<QImage>`
- [ ] `VerticalCheckWindow::char_slice_to_pixmap` 不再读取 `slice.image`
- [ ] `char_slice_to_pixmap` 根据 `slice.page_num` 和 `slice.bbox` 从 `page_images_` 按需裁剪
- [ ] `char_slice_to_pixmap` 对无效 page_num、无效 bbox、空页面图像返回空 `QPixmap`
- [ ] `render_current_page` 中 `pixmap_cache_` 缓存逻辑仍然有效
- [ ] 切片缩略图在纵校网格中正常显示

## 异常捕获验证

- [ ] `VerticalCheckWindow` 构造函数中的 `QTimer::singleShot(0, ...)` lambda 包含 `try/catch (const std::exception&)`
- [ ] `on_label_selected` 函数体包含 `try/catch (const std::exception&)`
- [ ] `render_current_page` 函数体包含 `try/catch (const std::exception&)`
- [ ] 捕获异常后调用 `LOG_EX_ERROR` 记录日志
- [ ] 捕获异常后调用 `QMessageBox::critical` 向用户显示"纵校界面初始化失败：{错误信息}"或类似提示
- [ ] `QMessageBox` 已在 `verticalcheckwindow.cpp` 中 include

## 构建与运行验证

- [ ] CMake 配置成功
- [ ] Ninja 构建成功，无编译错误
- [ ] 新 `hengxiao_tool2.exe` 已复制到 `deploy` 目录
- [ ] `run.bat` 能正常启动应用
- [ ] 导入 PDF + JSON 后进入纵校阶段不闪退
- [ ] 纵校界面首字符组切片正常显示
- [ ] 导入阶段内存增量显著降低（相比修复前）
- [ ] 日志路径 `%LOCALAPPDATA%\hengxiao_tool2\logs\hengxiao_tool2.log` 正常写入且无异常堆栈
