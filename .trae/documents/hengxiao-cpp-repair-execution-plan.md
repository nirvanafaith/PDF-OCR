# 横校 C++ 修复、依赖安装与编译执行计划

## Summary

本计划依据 [`软件2_cpp/横校修复技术报告.md`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/横校修复技术报告.md)，对 `软件2_cpp` 完成最终修复验证、依赖安装、配置编译与运行验证。

目标：
1. 确认已落地修复正确；
2. 安装完整 MinGW64 + Qt5 工具链；
3. 配置并编译 `软件2_cpp`；
4. 使用示例数据运行完整流程（导入 → 纵校 → 横校 → 返回纵校），确保切换不再崩溃且修改正确生效。

## Current State Analysis

### 代码状态（Phase 1 已核实）

已审查关键文件并确认大部分修复已落地：

- [`src/windows/mainwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/mainwindow.cpp)
  - `on_horizontal_back()` 已重新创建 `VerticalCheckWindow`，避免空指针；
  - `on_line_data_ready()` 已对 `horiz_watcher_->result()` 包裹 `try-catch`；
  - 使用成员变量 `QProgressDialog* horizontal_progress_` 管理进度对话框。
- [`src/windows/horizontalcheckwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/horizontalcheckwindow.cpp)
  - 析构函数不再手动 `delete` hover 图元，避免双重释放；
  - `render_page`、`make_slice_pixmap`、`eventFilter` 均已加入 bbox 防御检查。
- [`src/windows/verticalcheckwindow.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/windows/verticalcheckwindow.cpp)
  - 新增 `flush_current_pending()`；
  - `on_next_step()` 在最后一组字符进入横校前调用 flush。
- [`src/processors/ocr_engine.cpp`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/processors/ocr_engine.cpp)
  - 对 `char`、`text` 字段增加 `is_string()` 前置检查。
- [`src/models/datamodels.h`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/src/models/datamodels.h)
  - `flatten_bbox` 对坐标元素增加 `is_number()` 检查。

剩余风险：代码是否完整同步到磁盘、是否存在新的编译错误、运行时是否有未覆盖路径，需在真实工具链下验证。

### 环境状态

- 当前仅有 `C:\Users\E-VR\mingw64` 的 gcc/g++，无 Qt5、CMake、ninja、MuPDF、PoDoFo；
- [`build.bat`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/build.bat) 硬编码使用 `C:\msys64\mingw64`；
- 项目路径包含中文，历史上 MOC/CMake 曾因编码问题失败，需重点关注。

## Proposed Changes

### Phase 1：状态确认与数据准备

1. 复核 [`横校修复技术报告.md`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/横校修复技术报告.md) 中列出的根因与当前代码是否一致；
2. 检查 `软件2/json` 目录下是否存在可用示例（PDF + `chars.json` + `lines.json`），确定验证用数据集；
3. 检查 `C:\msys64` 是否已存在，决定是否需要全新安装 MSYS2。

### Phase 2：依赖安装

1. **安装 MSYS2**
   - 若 `C:\msys64` 不存在，从官方源下载安装程序并安装到 `C:\msys64`；
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

3. **镜像回退**
   - 若官方镜像下载失败，更新 `/etc/pacman.d/mirrorlist.mingw` 与 `/etc/pacman.d/mirrorlist.msys`，换用 USTC / Tsinghua 镜像；
   - 重试安装命令。

4. **PATH 验证**
   - 确认 `C:\msys64\mingw64\bin` 与 `C:\msys64\usr\bin` 可用；
   - 验证 `cmake --version`、`ninja --version`、`g++ --version` 均返回有效版本。

### Phase 3：配置与编译

1. **首选方案：原目录构建**
   - 清理旧 `软件2_cpp/build`；
   - 执行 `build.bat`；
   - 若因中文路径导致 MOC/CMake 编码错误，切换到备选方案。

2. **备选方案：ASCII 路径构建**
   - 将源码复制到 `C:\temp\hengxiao_src`；
   - 在复制目录执行 CMake + Ninja 构建；
   - 将生成的可执行文件与部署产物复制回原目录或直接在备选目录运行验证。

3. **处理编译错误**
   - 若 Qt 头文件、MOC、链接错误，根据错误修正 include 或 CMake 配置；
   - 若 MuPDF/PoDoFo 包名或路径与 CMakeLists.txt 预期不一致，修正 `find_library`/`find_path` 或 pkg-config 调用；
   - 若出现新的代码错误，按技术报告原则进行最小化修复。

### Phase 4：运行验证

1. **启动程序**
   - 运行构建输出的 `hengxiao_tool2.exe`；
   - 若提示缺少 Qt 运行时，使用 `windeployqt` 部署。

2. **验证用例：纵校 → 横校 → 返回**
   - 导入示例 PDF 与 JSON；
   - 进入纵校，修改至少一个字符但不要切换字符分组（制造 pending modification）；
   - 点击“下一步”进入横校：
     - 不崩溃；
     - 横校窗口正常显示页面与文字叠加；
     - 已修改字符在横校中已生效；
   - 在横校点击“返回”：
     - 不崩溃；
     - 正确回到纵校；
   - 关闭主窗口，确认正常退出。

3. **边界验证**
   - 空 OCR 结果或单页数据；
   - 快速切换页面/缩放后返回；
   - 从横校完成进入精修占位阶段后再返回横校。

### Phase 5：报告更新

1. 将编译输出、运行日志、发现的新问题及修复记录更新到 [`横校修复技术报告.md`](file:///c:/Users/E-VR/Documents/trae_projects/横校/软件2_cpp/横校修复技术报告.md)；
2. 在报告中补充“运行验证结果”章节。

## Assumptions & Decisions

- **MSYS2 安装**：假设可以从官方源下载并安装到 `C:\msys64`，且该路径可写；
- **网络可用**：pacman 与 CMake FetchContent 都需要网络；若网络受限，需要用户手动提供离线包；
- **MuPDF/PoDoFo 包可用**：MSYS2 的 `mingw-w64-x86_64-mupdf` 与 `mingw-w64-x86_64-podofo` 包存在且版本兼容 Qt5/MinGW64；
- **测试数据可用**：优先使用 `软件2/json` 下已有的示例，不需要重新 OCR；
- **不改变 Python 版本**：本计划只修改 `软件2_cpp`，不触碰 `软件2`；
- **不引入新功能**：只修复横校切换与编译相关问题，不扩展 UI 或业务功能；
- **中文路径风险**：首选原目录构建，失败时切换到 ASCII 路径作为备选。

## Verification Steps

1. `cmake --version` 返回 ≥ 3.16；
2. `ninja --version` 返回有效版本；
3. `g++ --version` 返回 MinGW64 版本；
4. `build.bat` 执行成功，生成 `软件2_cpp/build/hengxiao_tool2.exe`（或 Release 子目录）；
5. 程序启动后窗口标题为“横校工具”，步骤指示器显示“导入/纵校/横校/精修”；
6. 导入示例数据后进入纵校，界面正常渲染字符切片；
7. 修改字符后不切换分组，点击“下一步”进入横校，无崩溃，文字叠加正确，修改已生效；
8. 横校点击“返回”后回到纵校，无崩溃；
9. 关闭程序后无异常退出码。
