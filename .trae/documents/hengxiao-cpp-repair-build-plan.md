# 横校 C++ 修复、依赖安装与编译验证计划

## Summary

按照用户要求，本计划将：
1. 依据 [`软件2_cpp/横校修复技术报告.md`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/横校修复技术报告.md) 完成横校切换相关代码修复；
2. 在 `C:\msys64` 全新安装 MSYS2 MinGW64 工具链，并安装 Qt5、CMake、ninja、nlohmann-json、MuPDF、PoDoFo；
3. 配置并编译 `软件2_cpp`；
4. 使用 `软件2` 目录下的示例 PDF/JSON 数据运行完整流程验证（导入 → 纵校 → 横校 → 返回纵校），确保不再崩溃且功能正常。

## Current State Analysis

### 已审查的关键文件

- [`软件2_cpp/CMakeLists.txt`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/CMakeLists.txt)：Qt5 5.15、nlohmann_json（FetchContent 回退）、可选 MuPDF/PoDoFo。
- [`软件2_cpp/build.bat`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/build.bat)：硬编码使用 `C:\msys64\mingw64`。
- [`软件2_cpp/src/windows/mainwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/mainwindow.cpp)：横校阶段生命周期、异步数据准备、异常回退逻辑所在。
- [`软件2_cpp/src/windows/mainwindow.h`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/mainwindow.h)：已声明 `horizontal_progress_`、`horiz_watcher_` 等成员。
- [`软件2_cpp/src/windows/horizontalcheckwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/horizontalcheckwindow.cpp)：横校渲染、悬停预览、右键修改/忽略、滚动联动。
- [`软件2_cpp/src/windows/verticalcheckwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/verticalcheckwindow.cpp)：纵校 pending modifications、进入横校前的 flush 接口。
- [`软件2_cpp/src/processors/ocr_engine.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/processors/ocr_engine.cpp)：行数据构建、JSON 字段访问。
- [`软件2_cpp/src/models/datamodels.h`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/models/datamodels.h)：数据结构与 `flatten_bbox`。

### 代码修复现状

根据技术报告与现场代码比对，大部分修复已落地：

| 根因 | 关键位置 | 状态 |
|------|----------|------|
| 析构双重释放 hover 图元 | `~HorizontalCheckWindow()` 已清空 | 已修复 |
| 返回纵校空指针 | `MainWindow::on_horizontal_back()` 已重新创建 `VerticalCheckWindow` | 已修复 |
| pending 未 flush | `VerticalCheckWindow::on_next_step()` 已调用 `flush_current_pending()` | 已修复 |
| 进度对话框指针不安全 | `MainWindow` 已使用 `QProgressDialog* horizontal_progress_` 成员 | 已修复 |
| bbox 无效值导致渲染问题 | `render_page`/`make_slice_pixmap`/`eventFilter` 已加防御 | 已修复 |
| 后台线程异常未捕获 | `MainWindow::on_line_data_ready()` 已加 `try-catch` | 已修复 |
| JSON 字段类型访问不健壮 | `OCREngine::build_line_data`、`flatten_bbox` 已加 `is_string`/`is_number` 检查 | 已修复 |

风险点：代码是否已完整同步到磁盘、是否存在编译期新错误、运行时是否仍有未覆盖的路径，都需在真实工具链下验证。

### 环境现状

- 当前仅有 `C:\Users\E-VR\mingw64` 的 gcc/g++，无 Qt5、CMake、ninja、MuPDF、PoDoFo。
- 直接运行 `build.bat` 因找不到 `cmake` 与 MSYS2 路径而失败。
- 计划采用用户确认的方案：全新安装 MSYS2 到 `C:\msys64`，并通过 pacman 安装全部依赖。

## Proposed Changes

### Phase A：环境安装（只读准备 → 执行安装命令）

1. **下载并安装 MSYS2**
   - 从官方源下载 MSYS2 安装程序。
   - 安装到 `C:\msys64`。
   - 首次启动后执行 `pacman -Syu` 更新包数据库。

2. **安装编译依赖**
   ```bash
   pacman -S --needed base-devel mingw-w64-x86_64-toolchain
   pacman -S --needed mingw-w64-x86_64-cmake
   pacman -S --needed mingw-w64-x86_64-ninja
   pacman -S --needed mingw-w64-x86_64-qt5
   pacman -S --needed mingw-w64-x86_64-nlohmann-json
   pacman -S --needed mingw-w64-x86_64-mupdf
   pacman -S --needed mingw-w64-x86_64-podofo
   ```

3. **验证 PATH**
   - 确保 `C:\msys64\mingw64\bin` 与 `C:\msys64\usr\bin` 在环境变量中，或 `build.bat` 中 `set PATH` 生效。

### Phase B：代码修复补全（按需）

如果编译或静态检查中发现遗漏，按技术报告补全以下位置：

- [`src/windows/mainwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/mainwindow.cpp)
  - 保持 `on_horizontal_back()` 重新创建纵校窗口；
  - 保持 `on_line_data_ready()` 对 `horiz_watcher_->result()` 的异常捕获与回退。
- [`src/windows/horizontalcheckwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/horizontalcheckwindow.cpp)
  - 保持 `~HorizontalCheckWindow()` 不手动 delete hover 图元；
  - 保持 `render_page`、`make_slice_pixmap`、`eventFilter` 中的 bbox 防御检查。
- [`src/windows/verticalcheckwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/verticalcheckwindow.cpp)
  - 保持 `on_next_step()` 在最后一组字符进入横校前调用 `flush_current_pending()`。
- [`src/processors/ocr_engine.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/processors/ocr_engine.cpp)
  - 保持对 `char`、`text` 字段的 `is_string()` 前置检查。
- [`src/models/datamodels.h`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/models/datamodels.h)
  - 保持 `flatten_bbox` 对坐标元素的 `is_number()` 检查。

### Phase C：配置与编译

1. **清理旧构建目录**
   - 删除 `软件2_cpp/build`（如果存在且配置指向错误路径）。

2. **运行 build.bat**
   - 在项目根目录执行 `build.bat`。
   - 预期流程：CMake configure → Ninja build → 调用 `deploy.bat`。

3. **处理编译错误**
   - 若出现 Qt 头文件、MOC、链接错误，根据错误信息修正 include 或 CMake 配置。
   - 若 MuPDF/PoDoFo 包名或路径与 CMakeLists.txt 预期不一致，修正 `find_library`/`find_path` 或 pkg-config 调用。

### Phase D：运行验证

1. **准备测试数据**
   - 使用 `软件2/json/命运跌宕：顺治97871133242540000（1-1）/` 或 `金融与生活97871133261660000（1-1）/` 下的 `chars.json`、`lines.json` 与 PDF。

2. **启动程序**
   - 运行构建输出的可执行文件（默认 `build/Release/hengxiao_tool2.exe` 或 `build/hengxiao_tool2.exe`，具体以 CMake 输出为准）。
   - 若缺少 Qt 运行时，使用 `windeployqt` 部署。

3. **执行验证用例**
   - 导入示例 PDF 与 JSON；
   - 进入纵校，修改至少一个字符但不切换分组（制造 pending modification）；
   - 点击“下一步”进入横校，确认：
     - 不崩溃；
     - 横校窗口正常显示页面与文字叠加；
     - 修改的字符在横校中已生效；
   - 在横校点击“返回”，确认回到纵校且不崩溃；
   - 关闭主窗口，确认正常退出。

4. **记录结果**
   - 将编译输出、运行截图/日志、发现的新问题更新到 [`横校修复技术报告.md`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/横校修复技术报告.md) 或单独验证报告中。

## Assumptions & Decisions

- **MSYS2 安装**：假设可以从官方源下载并安装到 `C:\msys64`，且该路径可写。
- **网络可用**：pacman 与 CMake FetchContent 都需要网络；若网络受限，需要用户手动提供离线包。
- **MuPDF/PoDoFo 包可用**：MSYS2 的 `mingw-w64-x86_64-mupdf` 与 `mingw-w64-x86_64-podofo` 包存在且版本兼容 Qt5/MinGW64。
- **测试数据可用**：使用 `软件2/json` 下已有的示例，不需要重新 OCR。
- **不改变 Python 版本**：本计划只修改 `软件2_cpp`，不触碰 `软件2`。
- **不引入新功能**：只修复横校切换与编译相关问题，不扩展 UI 或业务功能。

## Verification Steps

1. `cmake --version` 返回 ≥ 3.16。
2. `ninja --version` 返回有效版本。
3. `g++ --version` 返回 MinGW64 版本。
4. `build.bat` 执行成功，`build/hengxiao_tool2.exe`（或 Release 子目录）生成。
5. 程序启动后窗口标题为“横校工具”，步骤指示器显示“导入/纵校/横校/精修”。
6. 导入示例数据后进入纵校，界面正常渲染字符切片。
7. 修改字符后点击“下一步”进入横校，无崩溃，文字叠加正确。
8. 横校点击“返回”后回到纵校，无崩溃。
9. 关闭程序后无异常退出码。
