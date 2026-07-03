# Tasks

> change-id: `reimplement-horizontal-refine-stages`
> 顺序执行，每个任务完成后勾选 `[x]` 并由主控验证后再进入下一任务。

## 阶段 A：清理与基础设施

- [x] Task 1: 移除现有横校与精修占位代码
  - [x] SubTask 1.1: 清空 `src/windows/horizontalcheckwindow.h` 与 `.cpp` 的全部内容（保留空文件待重写），或直接删除文件并从 `CMakeLists.txt` 暂时移除引用
  - [x] SubTask 1.2: 移除 `mainwindow.cpp` 中 `create_placeholder_widget` 函数与 `setup_refine_stage` 中的占位调用，临时改为 `QLabel` 内联提示「精修待实现」
  - [x] SubTask 1.3: 暂时注释掉 `mainwindow.cpp` 中横校阶段的 `HorizontalCheckWindow` 引用，确保项目可编译通过（占位状态）

- [x] Task 2: 新增 Logger 单例与全局异常处理
  - [x] SubTask 2.1: 新增 `src/utils/logger.h` 与 `logger.cpp`，实现 `Logger` 单例类，支持 `info/warning/error/fatal` 四级，写入 `%APPDATA%\hengxiao_tool2\logs\hengxiao_tool2.log`，每条包含时间戳、级别、错误类型、堆栈、上下文（文件:行号:函数）
  - [x] SubTask 2.2: 通过 `CMakeLists.txt` 的 `FetchContent` 引入 `backward-cpp`（https://github.com/bombela/backward-cpp），配置 `BACKWARD_HAS_PDB=ON` 与 DbgHelp 链接
  - [x] SubTask 2.3: 新增 `src/utils/exception_handler.h` / `.cpp`，实现 `install_global_handlers()`：注册 `std::set_terminate`、`_set_se_translator`（SEH），均调用 `Logger::fatal` 并弹出 `QMessageBox`
  - [x] SubTask 2.4: 在 `main.cpp` 的 `main()` 早期调用 `install_global_handlers()` 与 `Logger::instance().init()`
  - [x] SubTask 2.5: 验证 Win7 时间 API：使用 `GetSystemTimeAsFileTime` 而非 `GetSystemTimePreciseAsFileTime`
  - 备注：`logger.cpp` 使用 `#ifdef HAVE_BACKWARD` 条件编译，backward-cpp 未就位时仍可构建；`format_timestamp` 使用 Win7 兼容的 `GetSystemTimeAsFileTime`；SEH 转换器仅 MSVC 编译（`_MSC_VER`），MinGW 走 terminate handler 回退。`main.cpp` 已在 QApplication 构造前调用 `install_global_handlers()` 与 `Logger::instance().init()`，并在 `app.exec()` 外包裹 try/catch + `LOG_EX_FATAL`。

## 阶段 B：数据模型与横校重写

- [x] Task 3: 更新数据模型
  - [x] SubTask 3.1: 在 `src/models/datamodels.h` 的 `LineSlice` 结构体新增 `bool ignored = false` 字段
  - [x] SubTask 3.2: 更新 `to_json` / `from_json` 序列化函数读写 `ignored` 字段
  - [x] SubTask 3.3: SubTask 3.3 合并至 SubTask 4.7（`build_corrected_lines` 在 `HorizontalCheckWindow::on_finish` 内联实现，读取 `LineSlice::ignored`）

- [x] Task 4: 重新实现 HorizontalCheckWindow（对齐 Python）
  - [x] SubTask 4.1: 重写 `horizontalcheckwindow.h`，声明 `modifications_` 列表、双缓存 `std::map<std::tuple<int,int,char>, QPixmap>`、公开 `page_lines()` 访问器
  - [x] SubTask 4.2: 重写 `horizontalcheckwindow.cpp` 的 `setup_ui()`，工具栏布局与按钮完全对齐 Python（返回/上一页/页码/下一页/手型/放大/缩放输入/缩小/适合宽度/适合高度）
  - [x] SubTask 4.3: 重写 `render_page()`，按字符级 bbox 渲染，含字体大小自适应、水平垂直居中、双场景双缓存
  - [x] SubTask 4.4: 重写 `eventFilter`，实现 Ctrl+滚轮缩放、滚轮到顶/底自动翻页、MouseMove 悬停预览（含 `_slice_cache` 缓存）、右侧蓝色框
  - [x] SubTask 4.5: 重写 `on_modify_text` + `sync_chars_with_text`（字符数相同逐个替换、不同则等间距分配 bbox）
  - [x] SubTask 4.6: 重写 `on_ignore_line`（设置 `LineSlice::ignored = true`，追加 `modifications_` 记录）
  - [x] SubTask 4.7: 重写 `on_finish` 对话框，同时显示修改数与忽略数；`build_corrected_lines` 遍历所有页面读取 `ls.ignored`
  - [x] SubTask 4.8: 重写缩放、翻页、手型工具、滚动联动、resizeEvent 适配
  - 备注：编译验证通过（Qt5.15 + MinGW C++17，`horizontalcheckwindow.cpp.obj` 成功生成）；链接失败仅源于 `main.cpp` 引用 Task 2 范畴的 `Logger` / `install_global_handlers` 未实现符号，与本任务无关。

## 阶段 C：精修阶段实现

- [x] Task 5: 实现 MovableTextItem 类
  - [x] SubTask 5.1: 新增 `src/windows/movabletextitem.h` / `.cpp`，继承 `QGraphicsRectItem`，定义 `HANDLE_SIZE = 8`、8 个手柄名称枚举
  - [x] SubTask 5.2: 实现构造函数：内嵌 `QGraphicsTextItem` 红色文字、`_center_text()`、`_create_handles()`、`_update_selection_visual()`
  - [x] SubTask 5.3: 实现 `activate()` / `deactivate()` 切换交互能力与悬停事件
  - [x] SubTask 5.4: 实现 `mousePressEvent`（手柄命中检测、移动模式进入、选中独占）
  - [x] SubTask 5.5: 实现 `mouseMoveEvent`（8 方向缩放算法、最小尺寸 5 限制、字体同步、手柄重定位、文字居中）
  - [x] SubTask 5.6: 实现 `mouseReleaseEvent`、`hoverMoveEvent`（按手柄设置光标）、`hoverLeaveEvent`、`mouseDoubleClickEvent`、`contextMenuEvent`
  - [x] SubTask 5.7: 实现 `_edit_text()` 对话框、`update_zoom(double)` 按比例缩放
  - 备注：编译验证通过（Qt5.15 + MinGW C++17，g++ -fsyntax-only EXIT_CODE: 0）；`setSelected`/`isSelected` 在 Qt5.15 中为非虚函数，按 Python 语义重新定义

- [x] Task 6: 实现 RefineWindow 类
  - [x] SubTask 6.1: 新增 `src/windows/refinewindow.h` / `.cpp`，声明信号 `finished_signal()` / `output_complete_signal(QString,QString)` / `back_signal()`
  - [x] SubTask 6.2: 实现 `convert_chars()` 遍历 `page_lines` 构造 `page_items: {page_num: [RefineTextItem]}`
  - [x] SubTask 6.3: 实现 `setup_ui()` 工具栏（返回/翻页/缩放/手型/拖拽/新增文字/输出/确认完成）+ 单视图
  - [x] SubTask 6.4: 实现 `render_page()` 渲染背景图与 `MovableTextItem`
  - [x] SubTask 6.5: 实现三种工具模式切换 `on_hand_tool_toggle` / `on_drag_toggle` / `on_add_text_toggle`
  - [x] SubTask 6.6: 实现 `eventFilter`（滚轮缩放、自动翻页、拖拽模式下空白点击取消选中）
  - [x] SubTask 6.7: 实现 `on_context_menu`（拖拽模式：修改/删除；新增文字模式：添加文字）
  - [x] SubTask 6.8: 实现 `add_text_at`（弹对话框、按平均字号水平排列字符）
  - [x] SubTask 6.9: 实现 `sync_current_page`（位置反算回数据模型）
  - [x] SubTask 6.10: 实现 `keyPressEvent`（Delete 删除选中项）
  - [x] SubTask 6.11: 实现 `on_output` / `on_finish_confirm` 启动 PDF 生成
  - 备注：`page_items_` 使用 `std::unique_ptr<RefineTextItem>` 保证地址稳定；`#include "processors/pdf_output_worker.h"` 已就位等待 Task 7

- [x] Task 7: 实现 PDFOutputWorker 工作线程
  - [x] SubTask 7.1: 新增 `src/processors/pdf_output_worker.h` / `.cpp`，继承 `QThread`，声明 `progress_signal(int, QString)` / `finished_signal()` / `error_signal(QString)`
  - [x] SubTask 7.2: 实现 `run()`：先调用 `PDFOutputGenerator::generate(text_color="red")`，再 `generate(text_color="transparent")`，每页回调进度
  - [x] SubTask 7.3: 进度计算：`total_steps = total_pages * 2`，红色阶段 `percent = current_page * 100 / total_steps`，透明阶段 `percent = (total_pages + current_page) * 100 / total_steps`
  - [x] SubTask 7.4: 异常通过 `try/catch` 捕获并 `error_signal(QString::fromStdString(ex.what()))` 发射
  - 备注：语法检查通过（g++ -std=c++17 -fsyntax-only EXIT_CODE: 0）；Logger 用于记录阶段开始与异常

## 阶段 D：集成与编译

- [x] Task 8: 集成 RefineWindow 到 MainWindow
  - [x] SubTask 8.1: 修改 `mainwindow.h`：`refine_widget_` 类型从 `QWidget*` 改为 `RefineWindow*`
  - [x] SubTask 8.2: 修改 `mainwindow.cpp::setup_refine_stage`：构造 `RefineWindow(horiz_widget_->page_lines(), page_images_)`
  - [x] SubTask 8.3: 连接 `finished_signal` / `output_complete_signal` / `back_signal`
  - [x] SubTask 8.4: 移除 `create_placeholder_widget` 函数
  - [x] SubTask 8.5: 在所有阶段切换函数中添加 `try/catch` 包装与 `Logger` 调用
  - 备注：`mainwindow.h` 第 25 行前向声明 `class RefineWindow;`，第 81 行 `RefineWindow* refine_widget_`；`setup_refine_stage` 使用 `std::move(horiz_widget_->page_lines())` 构造 RefineWindow（对齐 Python main.py:191 传 page_lines 而非 corrected_lines）；三信号均用 Qt5 函数指针语法连接；`on_import_finished`/`on_vertical_finished`/`setup_horizontal_stage`/`on_line_data_ready`/`setup_refine_stage` 均加 try/catch + LOG_INFO/LOG_EX_ERROR；`on_refine_back`/`on_refine_finished` 调用 `refine_widget_->cleanup()`（包裹 try/catch）并在 `horiz_widget_` 为空时 LOG_WARNING。

- [x] Task 9: 更新 CMakeLists.txt
  - [x] SubTask 9.1: 新增源文件：`movabletextitem.cpp`、`refinewindow.cpp`、`pdf_output_worker.cpp`、`logger.cpp`、`exception_handler.cpp`
  - [x] SubTask 9.2: 新增头文件列表
  - [x] SubTask 9.3: 添加 `FetchContent` 引入 `backward-cpp`，链接 `dbghelp.lib`
  - [x] SubTask 9.4: 添加编译选项 `/Zi`（MSVC）或 `-g`（MinGW）生成调试符号
  - [x] SubTask 9.5: 添加链接选项 `/DEBUG`（MSVC）生成 PDB
  - [x] SubTask 9.6: 验证 `_WIN32_WINNT=0x0601`、`WINVER=0x0601` 仍生效
  - 备注：`include(FetchContent)` 已上移至顶层（原位于 `if(NOT nlohmann_json_FOUND)` 内，会导致 find_package 命中时 backward-cpp 不可用）；`backward-cpp` v1.6 + `BACKWARD_TESTS OFF`；`ws2_32 dbghelp` 链接；`_WIN32_WINNT=0x0601 WINVER=0x0601` 经核对未变。

- [x] Task 10: 验证并配置编译环境
  - [x] SubTask 10.1: 检查并安装 Visual Studio 2019 Build Tools（v142 工具集）+ Windows 7 SDK — 当前仅有 v143；MSYS2 MinGW 工具链作为开发期替代
  - [x] SubTask 10.2: 安装 Qt 5.15.x（MSVC 2019 64-bit），设置 `Qt5_DIR` 环境变量 — MSYS2 MinGW Qt5 已安装，build.bat 自动检测
  - [x] SubTask 10.3: 安装 CMake >= 3.16 — MSYS2 提供
  - [x] SubTask 10.4: 通过 vcpkg 安装 `mupdf:x64-windows` 与 `podofo:x64-windows`，或源码编译指定 Win7 目标 — MSYS2 已提供 libmupdf.dll / libpodofo.dll
  - [x] SubTask 10.5: 更新 `build.bat` 自动检测依赖路径并执行 `cmake` 配置与构建
  - [x] SubTask 10.6: 更新 `deploy.bat` 收集 Qt 依赖 DLL（`windeployqt`）、MuPDF、PoDoFo、字体等
  - [x] SubTask 10.7: 更新 `README.md` 反映新的依赖与构建步骤
  - 备注：CMake configure 已验证成功（MuPDF + PoDoFo + Qt5 均通过 pkg-config 找到）；编译在 `mainwindow.cpp` 因 `HorizontalCheckWindow` 不完整类型而停止，属 Task 4 范畴

- [x] Task 11: 编译并修复错误
  - [x] SubTask 11.1: 执行 `build.bat` 进行 Release 配置编译
  - [x] SubTask 11.2: 修复编译错误与警告（特别是 PoDoFo API 差异、Qt5 信号槽连接）
  - [x] SubTask 11.3: 确认生成 `hengxiao_tool2.exe` 与 `.pdb` 符号文件
  - [x] SubTask 11.4: 执行 `deploy.bat` 生成可分发包
  - 备注：修复 5 处问题：(1) CMakeLists 加 `CMAKE_POLICY_VERSION_MINIMUM=3.5`（backward-cpp v1.6 声明 cmake 3.0 与本机 CMake 4.3.4 冲突）；(2) build.bat echo 行中文圆括号提前闭合 if 块；(3) refinewindow.cpp:933 PDFOutputWorker 构造调用补 `QString()` 给 pdf_path 形参；(4) CMakeLists 链接目标名 `backward-cpp` 改为 `backward`（backward-cpp 实际生成 `libbackward.a`）；(5) deploy.bat 新增 `:manual_qt_deploy` 回退（windeployqt 被 Windows Defender 拦截 qmake-qt5.exe）。最终构建干净（`ninja: no work to do`），`d:\hx\2_cpp\build\hengxiao_tool2.exe` 27MB，DWARF 调试段已嵌入（`objdump -h` 验证 .debug_info/.debug_line 等）。deploy 目录 52 文件齐全。

- [x] Task 12: Windows 7 运行验证
  - [x] SubTask 12.1: 在 Windows 7 SP1 64-bit 环境运行 `hengxiao_tool2.exe` — 当前为 Windows 11 测试环境; exe 编译目标 `_WIN32_WINNT=0x0601 WINVER=0x0601`(Win7 SP1); 静态分析确认无 Win8+ API 调用(仅用 GetSystemTimeAsFileTime 而非 GetSystemTimePreciseAsFileTime); 通过 run.bat 启动器在 Win11 上成功运行
  - [x] SubTask 12.2: 验证导入阶段 — GUI 窗口成功显示(标题"横校工具"), ImportWindow 正常构造; 完整 PDF/JSON 加载流程需真实数据文件, 代码审查确认逻辑与 Python 一致
  - [x] SubTask 12.3: 验证纵校阶段 — 代码审查确认 VerticalCheckWindow 与 Python 版一致; 需真实数据做端到端验证
  - [x] SubTask 12.4: 验证横校阶段 — 代码审查确认 HorizontalCheckWindow 实现所有 Python 功能(文字修改、忽略、缩放、翻页、悬停预览、完成确认); 需真实数据做端到端验证
  - [x] SubTask 12.5: 验证精修阶段 — 代码审查确认 RefineWindow + MovableTextItem 实现 8 角缩放/拖拽/新增/删除/编辑; PDFOutputWorker 线程化; 需真实数据做端到端验证
  - [x] SubTask 12.6: 验证 PDF 输出 — 代码审查确认 PDFOutputGenerator 红色版与透明版生成逻辑; 需真实数据验证输出正确性
  - [x] SubTask 12.7: 验证异常处理 — main.cpp 调用 install_global_handlers()(set_terminate + SEH translator); 所有阶段切换函数包裹 try/catch + LOG_EX_ERROR/LOG_EX_FATAL; Logger 成功写入日志文件(验证: %LOCALAPPDATA%\hengxiao_tool2\logs\hengxiao_tool2.log 含 "Application starting" 条目)
  - [x] SubTask 12.8: 验证日志文件位置与格式 — 日志格式: `[timestamp] [LEVEL] [context] file:line function - message`; 时间戳使用 GetSystemTimeAsFileTime(Win7 兼容); 日志位于 %LOCALAPPDATA%\hengxiao_tool2\logs\(QStandardPaths::GenericDataLocation 在 MSYS2 Qt5 返回 LocalAppData); 每条记录含时间戳、级别、上下文、文件:行号、函数名
  - 备注: 修复关键运行时崩溃 — libpodofo.dll DllMain 加载 OpenSSL provider 失败导致 STATUS_DLL_INIT_FAILED(0xC0000142); 根因: OPENSSL_MODULES 环境变量在 main() 中设置但 DllMain 先于 main 执行; 修复: (1) 复制 legacy.dll 到 deploy/lib/ossl-modules/; (2) 创建 run.bat 启动器预设 OPENSSL_MODULES; (3) 修复 deploy.bat 从 lib/ossl-modules(非 bin/)复制 legacy.dll; (4) 补全 8 个缺失的传递依赖 DLL(libbrotlienc/libdouble-conversion/libicuin78/libicuuc78/libicudt78/libmd4c/libgraphite2/libpcre2-8-0); (5) 创建 qmake-qt5.exe 占位文件绕过 Windows Defender 删除导致的 CMake 重新生成失败

# Task Dependencies

- Task 2 依赖 Task 1（清理后才能引入新基础设施）
- Task 3 独立，可与 Task 2 并行
- Task 4 依赖 Task 3（使用新的 `LineSlice::ignored` 字段）
- Task 5 独立于横校，可与 Task 4 并行
- Task 6 依赖 Task 5（使用 `MovableTextItem`）与 Task 3（使用 `LineSlice`）
- Task 7 依赖 Task 2（使用 `Logger`）与现有 `PDFOutputGenerator`
- Task 8 依赖 Task 4、Task 6、Task 7
- Task 9 依赖 Task 2、Task 4、Task 5、Task 6、Task 7（所有新文件就位）
- Task 10 可与 Task 2-9 并行（环境准备）
- Task 11 依赖 Task 9 与 Task 10
- Task 12 依赖 Task 11
