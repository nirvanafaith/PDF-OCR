# 横校工具2 C++ 版构建打包技术报告与执行计划

## 1. 任务摘要

将 `d:\hx\software2_cpp` 工程编译、打包为可在 Windows 下独立运行的 exe，并确保：
1. 所有依赖已就绪（Qt5、MuPDF、PoDoFo、nlohmann/json、MinGW 工具链）。
2. 编译成功，无报错。
3. 部署后的 `dist\hengxiao_tool2.exe` 能正常启动，无 DLL 缺失弹窗。
4. 如发现代码中与本地依赖版本不兼容或运行时隐患，一并修正。

## 2. 项目技术栈与架构

| 项目 | 说明 |
|------|------|
| 语言/标准 | C++17 |
| 构建系统 | CMake ≥ 3.16 + Ninja |
| 工具链 | MSYS2 MinGW64 (gcc/g++) |
| GUI | Qt5.15 (Widgets / Gui / Core / Concurrent) |
| JSON | nlohmann/json 3.x |
| PDF 渲染 | MuPDF 1.27.1 |
| PDF 生成 | PoDoFo 0.10.4 |

### 2.1 目录结构

```
software2_cpp/
├── CMakeLists.txt              # 主构建配置
├── build.bat                   # MSYS2 MinGW64 编译脚本
├── deploy.bat                  # DLL 与资源复制脚本
├── src/
│   ├── main.cpp                # 入口：QApplication + MainWindow
│   ├── models/datamodels.h     # 数据模型与 JSON 序列化
│   ├── processors/             # PDF 处理、OCR 数据、懒加载
│   ├── utils/                  # JSON、样式、缩放工具
│   └── windows/                # 导入/纵校/横校/步骤指示器窗口
└── resources/styles.qss        # 全局 QSS
```

### 2.2 关键窗口流程

`MainWindow` 通过 `QStackedWidget` 管理四个阶段：
1. **导入** (`ImportWindow`)：选择 PDF，自动检测同目录 `lines.json` + `newchar.json`/`chars.json`，后台线程加载页面图像与 OCR 结果。
2. **纵校** (`VerticalCheckWindow`)：按字符分组校对切片，支持修改/删除/框选。
3. **横校** (`HorizontalCheckWindow`)：左右双视图（文字叠加 + 原图），支持缩放、翻页、修改、忽略行。
4. **精修** (`setup_refine_stage` 占位，后续任务实现）。

## 3. 依赖检测结果

已在本地 `C:\msys64\mingw64` 检测到全部依赖：

| 依赖 | 状态 | 路径/版本 |
|------|------|-----------|
| MSYS2 MinGW64 | 已安装 | `C:\msys64` |
| gcc / g++ | 已安装 | `C:\msys64\mingw64\bin\gcc.exe` |
| cmake | 已安装 | `C:\msys64\mingw64\bin\cmake.exe` |
| ninja | 已安装 | `C:\msys64\mingw64\bin\ninja.exe` |
| Qt5Core/Gui/Widgets/Concurrent | 已安装 | `C:\msys64\mingw64\bin\Qt5*.dll` |
| nlohmann/json | 已安装 | `C:\msys64\mingw64\include\nlohmann\json.hpp` |
| MuPDF | 已安装 | 1.27.1 (`libmupdf.dll`) |
| PoDoFo | 已安装 | 0.10.4 (`libpodofo.dll`) |

CMake 已在前次配置中成功找到所有依赖（`MUPDF_FOUND=1`、`PODOFO_FOUND=1`、Qt5 各组件目录已写入 `CMakeCache.txt`）。

## 4. 代码质量与兼容性评估

### 4.1 已确认兼容的部分

- **MuPDF 1.27.1**：`pdf_processor.cpp` / `lazy_page_loader.cpp` 使用的 `fz_context`、`fz_open_document`、`fz_new_pixmap_from_page_number`、`fz_scale` 等 API 与本地 1.27.1 一致。
- **PoDoFo 0.10.4 API**：通过核对本地头文件，确认以下 API 存在且签名匹配：
  - `PdfStreamedDocument(const std::string_view& filename)`
  - `PdfDocument::CreateImage()`
  - `PdfFontManager::GetOrCreateFont(const std::string_view&)` / `GetStandard14Font(PdfStandard14FontType::Helvetica)`
  - `PdfFont::GetStringLength(const std::string_view&, const PdfTextState&)`
  - `PdfPageCollection::CreatePage(const Rect&)`
  - `PdfPainter::SetCanvas(PdfPage&)` / `DrawImage` / `DrawText` / `FinishDrawing`
  - `PdfGraphicsStateWrapper::SetFillColor(const PdfColor&)`
  - `PdfTextStateWrapper::SetFont(const PdfFont&, double)`
  - `PdfExtGState(PdfDocument&)` / `SetFillOpacity(double)`（本地 0.10.4 仍保留此 API；后续开发分支已改为 `CreateExtGState(definition)`，但本地无需修改）
  - `bufferview` 别名定义在 `podofo/auxiliary/basetypes.h`

- **Qt5 部署策略**：`deploy.bat` 已覆盖 Qt5 核心 DLL、MinGW 运行时、ICU、harfbuzz/freetype/glib、MuPDF、PoDoFo 传递依赖、Qt 平台插件 `qwindows.dll`、OpenSSL legacy provider。与 Qt 5.15 官方部署文档方向一致。

### 4.2 潜在风险点

| 位置 | 风险 | 处理策略 |
|------|------|----------|
| `src/processors/pdf_output_generator.cpp:86` | `PdfStreamedDocument document(output_path.toStdString())` 传入 `std::string`，而构造函数期望 `std::string_view`；隐式转换应可工作，但若 `output_path` 含空字符会有问题。 | 编译时确认，必要时显式构造 `std::string_view`。 |
| `src/windows/horizontalcheckwindow.cpp:208,270` | 将 `LineSlice*` 指针存入 `QGraphicsItem::setData(0, QVariant::fromValue(reinterpret_cast<quintptr>(ls_ptr)))`，之后转回。只要同进程、同架构安全，但依赖 `page_lines_` 不被重新分配。 | 当前实现可工作；若后续改为 `std::map` 导致重新分配可能失效，但当前 `page_lines_` 为 `std::map<int, std::vector<LineSlice>>`，元素地址稳定。 |
| `deploy.bat:150` | `libicudt*.dll` 使用通配复制；若 bin 目录有多个版本可能复制重复文件。 | 不影响功能，但可优化为复制确切版本。 |
| `deploy.bat` 整体 | DLL 列表基于当前 MSYS2 环境整理，若某些传递依赖版本变化（ICU 78→80、libxml2-16→libxml2-17 等），可能出现缺失。 | 打包后使用 Dependencies 工具或实际运行验证，按需补充。 |
| `src/main.cpp:35` | `snprintf(modules_path, MAX_PATH, ...)` 可能截断超长路径。 | 当前路径为 `exe_dir\lib\ossl-modules`，正常不会超长；如报警告可改为 `snprintf` 返回值检查。 |

### 4.3 不需要修改的部分

- `datamodels.h` 中 `std::optional<QImage>`：QImage 支持拷贝与移动，语义正确。
- `json_utils.cpp` 使用 `json::parse` 范围重载，兼容 nlohmann/json 3.x。
- `zoom_utils.cpp` 使用 `std::optional` 与 Qt 的 `qMax/qMin`，无问题。

## 5. 执行计划

### 5.1 编译

1. **清理旧构建产物**（保留 `CMakeCache.txt` 以复用配置）：
   ```powershell
   cd d:\hx\software2_cpp
   Remove-Item -Path build\hengxiao_tool2.exe -ErrorAction SilentlyContinue
   ```

2. **运行 `build.bat`**：
   - 设置 MSYS2/MinGW64 PATH、PKG_CONFIG_PATH。
   - 调用 `cmake --build . --config Release`。
   - 若编译失败，根据错误信息修改对应源文件后重试。

3. **常见编译问题预案**：
   - 若 PoDoFo API 不匹配：核对本地头文件后调整 `pdf_output_generator.cpp`。
   - 若 Qt MOC/UIC 报错：检查头文件中的 `Q_OBJECT` 宏及 CMake 的 `CMAKE_AUTOMOC/UIC/RCC` 设置。
   - 若链接错误：确认 `target_link_libraries` 中包含 `Qt5::Widgets Gui Core Concurrent` 和 `nlohmann_json::nlohmann_json`。

### 5.2 部署

1. **运行 `deploy.bat`**：
   - 创建 `dist/` 目录。
   - 复制 `hengxiao_tool2.exe`、`resources/`、Qt5 DLL、MinGW 运行时、MuPDF/PoDoFo 及其依赖、`platforms/qwindows.dll`、`lib/ossl-modules/legacy.dll`。
   - 生成 `qt.conf`。

2. **验证 dist 目录完整性**：
   - 检查 `dist\hengxiao_tool2.exe` 存在。
   - 检查关键 DLL 是否全部复制：
     ```powershell
     Get-ChildItem d:\hx\software2_cpp\dist\*.dll | Select-Object Name
     ```

### 5.3 运行验证

1. **启动验证**：
   ```powershell
   cd d:\hx\software2_cpp\dist
   .\hengxiao_tool2.exe
   ```
   - 观察是否出现 DLL 缺失弹窗。
   - 在无显示器环境中，可借助 `start` 或检查进程是否正常启动数秒后退出。

2. **DLL 依赖扫描（如启动失败）**：
   - 使用 `Dependencies` 或 `ldd`（MSYS2）检查 `hengxiao_tool2.exe` 缺失的 DLL。
   - 将缺失项补充到 `deploy.bat` 对应分组后重新部署。

3. **功能验证（可选但建议）**：
   - 准备一份测试 PDF + `lines.json` + `chars.json`。
   - 启动程序后完成导入 → 纵校 → 横校流程，确认无崩溃。

## 6. 验证清单

- [ ] `build\hengxiao_tool2.exe` 生成成功。
- [ ] 编译日志无 error。
- [ ] `dist\hengxiao_tool2.exe` 存在。
- [ ] `dist\` 包含 Qt5 平台插件 `platforms/qwindows.dll`。
- [ ] `dist\` 包含 `resources/styles.qss`。
- [ ] `dist\` 包含 `lib/ossl-modules/legacy.dll`。
- [ ] 双击 `dist\hengxiao_tool2.exe` 可正常启动，无 DLL 缺失弹窗。
- [ ] 程序主窗口标题显示“横校工具”，步骤指示器可见。

## 7. 假设与决策

1. **继续使用 MSYS2 MinGW64**：项目现有 `build.bat`/`deploy.bat` 均围绕该环境编写，且所有依赖已在此环境中安装完毕，无需切换 MSVC/vcpkg。
2. **PoDoFo 0.10.4 保持当前 API**：已核对本地头文件，`pdf_output_generator.cpp` 中的 API 调用在当前 0.10.4 下可用。若编译时报错，将按实际头文件调整。
3. **不修改业务逻辑**：本次任务重点是构建打包；仅在编译/运行受阻时做最小化修正。
4. **技术报告即本计划文件**：用户要求“先写出技术报告再进行修正”，本文件同时承担技术报告与执行计划职责。

## 8. 回滚策略

- 所有源文件修改前会读取原内容。
- 编译/部署仅修改 `build/` 和 `dist/` 目录，不影响源代码。
- 若修改源码后需要回退，可通过 Git（如已初始化）或原文件备份恢复。
