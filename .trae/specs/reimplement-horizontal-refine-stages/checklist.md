# Checklist

> change-id: `reimplement-horizontal-refine-stages`
> 验证每个检查点后勾选 `[x]`。任一失败需在 `tasks.md` 追加修复任务。

## 阶段 A：清理与基础设施

- [x] `horizontalcheckwindow.h` / `.cpp` 原有实现已完全移除（无残留 `ignored_lines_` 集合、无 `QCache` 单缓存逻辑）
- [x] `mainwindow.cpp` 中 `create_placeholder_widget` 函数与精修占位调用已删除
- [ ] `utils/logger.h` / `.cpp` 已创建，`Logger` 单例可被全局访问
- [ ] 日志文件路径为 `%APPDATA%\hengxiao_tool2\logs\hengxiao_tool2.log`（Win7 可写）
- [ ] 日志条目包含：时间戳 `yyyy-MM-dd HH:mm:ss.zzz`、级别、错误类型、堆栈追踪、文件:行号:函数
- [ ] `backward-cpp` 已通过 `FetchContent` 集成，`dbghelp.lib` 已链接
- [ ] `utils/exception_handler.h` / `.cpp` 已创建，`install_global_handlers()` 注册了 `std::set_terminate` 与 `_set_se_translator`
- [ ] `main.cpp` 早期调用 `install_global_handlers()` 与 `Logger::instance().init()`
- [ ] 时间 API 使用 `GetSystemTimeAsFileTime`（非 Win8+ 的 `GetSystemTimePreciseAsFileTime`）

## 阶段 B：数据模型与横校

- [x] `LineSlice` 结构体新增 `bool ignored = false` 字段
- [x] `to_json` / `from_json` 序列化函数正确读写 `ignored` 字段
- [x] `HorizontalCheckWindow` 构造接收 `std::map<int, std::vector<LineSlice>>` 与 `std::vector<QImage>`
- [x] `modifications_` 列表追踪 `modify_text` 与 `ignore` 两类操作
- [x] `render_page()` 按字符级 bbox 渲染，字体大小自适应（超出目标宽度按比例缩小）
- [x] 左侧场景缓存 key 为 `(page, zoom)`，右侧 PDF 场景缓存 key 为 `(page, zoom, 'pdf')`
- [x] 忽略行通过 `LineSlice::ignored` 字段读取，渲染为灰色
- [x] `eventFilter` 实现 Ctrl+滚轮缩放、滚轮到顶/底自动翻页、MouseMove 悬停预览（含切片缓存）
- [x] `_make_slice_pixmap` 裁剪 `[0, bbox[1]-20, page_w, bbox[3]+20]` 区域
- [x] 悬停预览图元 `setZValue(100)`，右侧蓝色框 `setZValue(10)`、`QPen(blue, 2)`
- [x] `on_modify_text` 修改后调用 `sync_chars_with_text`（字符数相同逐个替换、不同则等间距分配 bbox）
- [x] `on_finish` 对话框同时显示「修改文字：N 处」与「忽略行：M 处」
- [x] `build_corrected_lines` 遍历所有页面读取 `ls.ignored` 构造 `CorrectedLine`
- [x] `page_lines()` 公开访问器返回 `std::map<int, std::vector<LineSlice>>`
- [x] 滚动条双向联动（左→右、右→左）使用 `blockSignals` 防回环
- [x] `resizeEvent` 最大化时延迟 50ms 调用 `on_fit_height`

## 阶段 C：精修阶段

- [ ] `MovableTextItem` 继承 `QGraphicsRectItem`，`HANDLE_SIZE = 8`
- [ ] 8 个缩放手柄（`topLeft`/`top`/`topRight`/`left`/`right`/`bottomLeft`/`bottom`/`bottomRight`）正确创建与定位
- [ ] 手柄初始不可见，选中时显示蓝色实心矩形
- [ ] 内嵌 `QGraphicsTextItem` 红色文字，`pixelSize = max(int(h), 1)`，`document().setDocumentMargin(0)`
- [ ] `mousePressEvent` 命中手柄进入缩放模式，命中文字进入移动模式
- [ ] `mouseMoveEvent` 缩放算法按手柄方向调整 `new_w` / `new_h`，最小尺寸 5 限制
- [ ] 缩放时字体 `pixelSize` 同步更新，手柄重定位，文字居中
- [ ] `hoverMoveEvent` 按手柄设置对应光标（`SizeFDiagCursor` / `SizeBDiagCursor` / `SizeVerCursor` / `SizeHorCursor` / `SizeAllCursor`）
- [ ] `contextMenuEvent` 弹出「修改文字」/「删除」菜单
- [ ] `_edit_text` 弹对话框编辑文字内容
- [ ] `update_zoom(double)` 按比例缩放位置、尺寸、字体
- [ ] `activate()` / `deactivate()` 正确切换交互能力

- [ ] `RefineWindow` 构造接收 `page_lines` 与 `page_images`
- [ ] `_convert_chars` 遍历 `page_lines` 跳过忽略行，为每个字符创建 `RefineTextItem` 存入 `page_items`
- [ ] 工具栏包含：返回/翻页/缩放/手型/拖拽/新增文字/输出/确认完成
- [ ] 三种工具模式互斥切换（手型 / 拖拽 / 新增文字）
- [ ] 手型模式：`ScrollHandDrag` + `OpenHandCursor`，停用所有 `MovableTextItem`
- [ ] 拖拽模式：`NoDrag` + `ArrowCursor`，激活所有 `MovableTextItem`
- [ ] 新增文字模式：`NoDrag` + `CrossCursor`，停用所有 `MovableTextItem`
- [ ] `render_page` 渲染背景图与 `MovableTextItem`，首次延迟 100ms 调用 `on_fit_height`
- [ ] `eventFilter` 拖拽模式下空白点击取消所有选中
- [ ] `on_context_menu` 拖拽模式弹修改/删除菜单，新增文字模式弹添加文字菜单
- [ ] `_add_text_at` 弹对话框，按 `_get_avg_font_size` 水平排列字符
- [ ] `_sync_current_page` 将场景位置反算回 `RefineTextItem.bbox`
- [ ] `keyPressEvent` 拖拽模式下 `Delete` 键删除选中项
- [ ] `on_output` / `on_finish_confirm` 调用 `_sync_current_page` 后启动 `PDFOutputWorker`
- [ ] `QProgressDialog` 显示进度，连接三个信号
- [ ] 信号 `finished_signal()` / `output_complete_signal(QString, QString)` / `back_signal()` 正确声明与发射

- [ ] `PDFOutputWorker` 继承 `QThread`
- [ ] 信号 `progress_signal(int, QString)` / `finished_signal()` / `error_signal(QString)` 声明
- [ ] `run()` 先红色后透明两阶段生成
- [ ] 进度计算 `total_steps = total_pages * 2`，百分比正确
- [ ] 异常通过 `error_signal` 发射

## 阶段 D：集成与编译

- [ ] `mainwindow.h` 中 `refine_widget_` 类型为 `RefineWindow*`
- [ ] `setup_refine_stage` 构造 `RefineWindow(horiz_widget_->page_lines(), page_images_)`
- [ ] 三个信号正确连接
- [ ] `on_output_complete` 显示成功消息框
- [ ] `on_refine_finished` 清理所有窗口并重置到导入阶段
- [ ] 所有阶段切换函数有 `try/catch` 与 `Logger` 调用
- [ ] `CMakeLists.txt` 新增所有源文件与头文件
- [ ] `backward-cpp` 通过 `FetchContent` 集成
- [ ] `/Zi` 与 `/DEBUG` 选项启用，生成 PDB
- [ ] `_WIN32_WINNT=0x0601` 与 `WINVER=0x0601` 仍生效

## 阶段 E：环境与运行验证

- [ ] Visual Studio 2019 Build Tools（v142）或 VS 2022 已安装
- [ ] Qt 5.15.x（MSVC 2019 64-bit）已安装，`Qt5_DIR` 环境变量配置
- [ ] CMake >= 3.16 已安装
- [ ] MuPDF 已安装（vcpkg 或源码编译，Win7 兼容）
- [ ] PoDoFo 已安装（vcpkg 或源码编译，Win7 兼容）
- [ ] `build.bat` 正确执行 `cmake` 配置与构建
- [ ] `deploy.bat` 通过 `windeployqt` 收集 Qt 依赖
- [ ] `README.md` 反映新依赖与构建步骤
- [ ] `hengxiao_tool2.exe` 与 `.pdb` 生成成功
- [ ] 编译无错误（警告可接受但应尽量消除）

## 阶段 F：Windows 7 功能验证

- [ ] 在 Windows 7 SP1 64-bit 上 `hengxiao_tool2.exe` 可启动
- [ ] 导入阶段：PDF 与 OCR JSON 正确加载
- [ ] 纵校阶段：字符分组与修改正常
- [ ] 横校阶段：文字修改、忽略、缩放、翻页、悬停预览、完成确认均正常
- [ ] 精修阶段：拖拽、8 角缩放、新增文字、删除、编辑均正常
- [ ] 输出 PDF：红色版与透明版均生成，文字位置正确
- [ ] 异常处理：故意触发异常时日志文件正确写入，含完整堆栈
- [ ] 日志文件位置与格式符合规范
- [ ] 所有功能与 Python 版本（`d:\hx\software2`）行为一致

## 异常处理与日志专项验证

- [ ] `OCREngine::load_results_from_file` 文件不存在时抛 `std::runtime_error` 并记录日志
- [ ] `PDFOutputGenerator::generate` 图像为空时抛异常并记录日志
- [ ] `PDFOutputWorker::run` 异常通过 `error_signal` 发射并记录日志
- [ ] `HorizontalCheckWindow::render_page` 字符 bbox 无效时跳过并记录警告
- [ ] `RefineWindow::render_page` 图像加载失败时记录错误
- [ ] 全局 `terminate` 处理器捕获未捕获 C++ 异常并记录 FATAL
- [ ] 全局 SEH 转换器捕获访问违例并记录 FATAL
- [ ] 日志文件按日轮转或追加写入（不覆盖）
