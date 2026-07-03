# 软件2 C++ 重构任务列表

## 阶段 1：工程骨架与基础设施

- [x] Task 1.1：创建 C++ 工程目录结构与 CMake 构建配置
  - [x] 在 `软件2_cpp/` 下创建 `src/`、`include/`、`resources/`、`third_party/` 目录
  - [x] 编写根目录 `CMakeLists.txt`，配置 C++17、Qt5 Widgets/Gui/Core、Windows 7 兼容选项（`_WIN32_WINNT=0x0601`）
  - [x] 添加 nlohmann/json 获取/引用配置
  - [x] 添加 PDF 库（MuPDF 或 PDFium）和 PDF 生成库（PoDoFo 或 PDFium）的获取/引用配置
  - [x] 配置 MSVC 2017/2019 或 MinGW-w64 工具链，确保不依赖 Win10 专属 API
  - [ ] 验证 CMake configure 和 build 在本地可通过并生成可执行文件（待依赖安装后验证）

- [x] Task 1.2：移植全局样式与工具函数
  - [x] 将 `ui/styles.py` 中的 QSS 移植为 `resources/styles.qss`
  - [x] 实现 `StyleManager` 类统一加载和应用样式表
  - [x] 将 `ui/zoom_utils.py` 移植为 `src/utils/zoom_utils.h/.cpp`，保持 Ctrl+滚轮缩放逻辑
  - [x] 实现 `JsonUtils` 辅助读写 `lines.json`/`chars.json`

## 阶段 2：数据模型与核心处理逻辑

- [x] Task 2.1：移植数据模型
  - [x] 创建 `include/models/datamodels.h`，定义所有 C++ 数据结构
  - [x] 实现 `CharSlice`、`LineSlice`、`CorrectedChar`、`CorrectedLine`、`RefineTextItem` 等
  - [x] 实现 `flatten_bbox` 工具函数
  - [x] 为所有模型添加 JSON 序列化/反序列化方法

- [x] Task 2.2：移植 PDF 处理模块
  - [x] 实现 `src/processors/pdf_processor.h/.cpp`，封装 PDF 转 `QImage` 逻辑（200 DPI）
  - [x] 实现 `src/processors/lazy_page_loader.h/.cpp`（可选，按需加载）
  - [x] 实现 `src/processors/pdf_output_generator.h/.cpp`，生成红色/透明文字版 PDF
  - [x] 保持与 Python 版本一致的输出效果（字体大小自适应 bbox、中文渲染）

- [x] Task 2.3：移植 OCR 数据处理引擎
  - [x] 实现 `src/processors/ocr_engine.h/.cpp`
  - [x] 实现 `load_results_from_file` 加载 lines.json 和 chars.json
  - [x] 实现 `parse_and_group` 按字符文本分组构建 `CharSlice`
  - [x] 实现 `build_line_data` 构建 `LineSlice` 数据结构

## 阶段 3：UI 窗口移植

- [x] Task 3.1：移植主窗口与步骤指示器
  - [x] 实现 `StepIndicator` 自定义控件
  - [x] 实现 `MainWindow`，包含 `QStackedWidget` 与阶段切换逻辑
  - [x] 连接四个阶段窗口的信号与槽

- [x] Task 3.2：移植导入窗口
  - [x] 实现 `ImportWindow` UI 布局与文件选择对话框
  - [x] 实现自动检测 lines.json / newchar.json / chars.json
  - [x] 使用 `QThread` + worker 在后台加载 PDF 与 JSON
  - [x] 实现进度日志文本区域与加载完成信号

- [x] Task 3.3：移植纵校窗口
  - [x] 实现 `PreviewGraphicsView`（无边界拖拽、Ctrl+滚轮缩放、宽度适配、红框居中）
  - [x] 实现 `SliceItemWidget`（90×90 缩略图、右键菜单、低分样式）
  - [x] 实现 `VerticalCheckWindow` 布局（左侧字符列表、顶部预览、右侧切片网格、底部导航）
  - [x] 实现切片修改/删除逻辑，保持当前字符组状态
  - [x] 实现"下一步"与"返回"信号

- [ ] Task 3.4：移植横校窗口
  - [ ] 实现 `HorizontalCheckWindow` 双视图布局与工具栏
  - [ ] 实现页面图像渲染与字符叠加绘制（Microsoft YaHei、自适应字号）
  - [ ] 实现忽略行灰显、右键菜单修改/忽略、悬停提示
  - [ ] 实现左右视图滚动条联动
  - [ ] 实现缩放、适合宽度、适合高度
  - [ ] 实现"完成横校"信号

- [ ] Task 3.5：移植精修窗口
  - [ ] 实现 `MovableTextItem` 自定义图形项（移动、缩放手柄、选中、编辑、删除）
  - [ ] 实现 `RefineWindow` 布局与工具栏
  - [ ] 实现文本项渲染、添加、编辑、删除逻辑
  - [ ] 使用 `QThread` + worker 在后台生成两份 PDF
  - [ ] 实现进度对话框与完成提示

## 阶段 4：集成、测试与优化

- [ ] Task 4.1：端到端流程验证
  - [ ] 使用一组真实 PDF + lines.json + chars.json 跑通导入→纵校→横校→精修→导出 PDF
  - [ ] 对比 C++ 输出与 Python 版本输出（PDF 内容、布局、样式）
  - [ ] 记录并修复差异

- [ ] Task 4.2：性能与稳定性优化
  - [ ] 对 PDF 渲染、图像缩放、切片网格进行性能测试
  - [ ] 优化大文档内存占用与响应速度
  - [ ] 添加异常处理和用户友好的错误提示

- [ ] Task 4.3：文档与构建脚本
  - [ ] 编写 `README.md` 说明构建步骤、依赖获取、运行方式
  - [ ] 提供 Windows 依赖准备脚本（vcpkg/conan/手动）
  - [ ] 保留 Python 版本不变，不破坏原有入口

# Task Dependencies

- Task 1.1 → Task 1.2 → Task 2.1 → Task 2.2 / Task 2.3
- Task 2.1 → Task 3.1 / Task 3.2 / Task 3.3 / Task 3.4 / Task 3.5
- Task 2.2 / Task 2.3 → Task 3.2 / Task 3.3 / Task 3.4 / Task 3.5
- Task 3.1 / Task 3.2 / Task 3.3 / Task 3.4 / Task 3.5 → Task 4.1 → Task 4.2 → Task 4.3
