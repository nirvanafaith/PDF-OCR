# 横校工具2 移除横校阶段并重新打包计划

 ## 1. 任务摘要

 将 `d:\hx\software2_cpp` 中的**横校阶段**（HorizontalCheckWindow）功能移除，替换为一个占位页面，然后重新编译并打包为可运行的 exe。

 具体要求：
1. 去掉横校功能实现。
2. 在原来横校的位置留下一个占位符页面（带“下一步/上一步”导航）。
3. 保持步骤指示器中的“横校”标签，仅功能降级为占位。
4. 重新编译并打包，确保 `dist\hengxiao_tool2.exe` 双击可正常启动。

## 2. 当前状态分析

### 2.1 现有流程

`MainWindow` 当前管理 4 个阶段：
1. **导入** (`ImportWindow`)
2. **纵校** (`VerticalCheckWindow`)
3. **横校** (`HorizontalCheckWindow`) —— 使用 `OCREngine::build_line_data` 异步构建行数据，然后显示左右双视图校对窗口
4. **精修** (`QWidget` 占位)

### 2.2 横校相关代码分布

| 文件 | 横校相关内容 |
|------|-------------|
| `src/windows/mainwindow.h` | `HorizontalCheckWindow` 前向声明与成员指针、`OCREngine*`、`QFutureWatcher*`、`QProgressDialog*`、`corrected_lines_`、横校相关 slots |
| `src/windows/mainwindow.cpp` | `#include "windows/horizontalcheckwindow.h"`、`#include "processors/ocr_engine.h"`、`setup_horizontal_stage()`、`on_line_data_ready()`、`on_horizontal_finished()`、`on_horizontal_back()` |
| `src/windows/horizontalcheckwindow.h/cpp` | 横校对窗口完整实现（本次不再编译，但保留源文件） |
| `src/processors/ocr_engine.h/cpp` | 仅 `build_line_data` 用于横校阶段 |
| `CMakeLists.txt` | `horizontalcheckwindow.cpp/h` 在 `SOURCES`/`HEADERS` 列表中 |

### 2.3 打包现状

上一任务已为打包问题修复：
- 主程序输出为 `hengxiao_tool2_app.exe`
- `hengxiao_tool2.exe` 是一个启动器，在启动真实程序前设置 `OPENSSL_MODULES` 环境变量
- `deploy.bat` 已同步复制两个 exe

本次无需改动打包方案，只需重新编译部署。

## 3. 修改计划

### 3.1 `src/windows/mainwindow.h`

- 删除 `HorizontalCheckWindow` 前向声明。
- 删除成员：
  - `HorizontalCheckWindow* horiz_widget_ = nullptr;`
  - `OCREngine* ocr_engine_ = nullptr;`
  - `QFutureWatcher<std::map<int, std::vector<LineSlice>>>* horiz_watcher_ = nullptr;`
  - `QProgressDialog* horizontal_progress_ = nullptr;`
  - `std::vector<CorrectedLine> corrected_lines_;`
- 删除 slots：
  - `void on_horizontal_finished(...)`
  - `void on_horizontal_back()`
  - `void on_line_data_ready()`
- 将 `setup_horizontal_stage()` 改为 `setup_horizontal_placeholder_stage()`。
- 新增占位页面成员：
  - `QWidget* horizontal_placeholder_widget_ = nullptr;`
- 保留步骤指示器中的“横校”文字标签。

### 3.2 `src/windows/mainwindow.cpp`

- 删除 `#include "windows/horizontalcheckwindow.h"`。
- 删除 `#include "processors/ocr_engine.h"`。
- 删除构造函数中的 `ocr_engine_ = new OCREngine();`。
- 删除析构函数中的 `delete ocr_engine_;`。
- 删除 `setup_horizontal_stage()` 全部异步横校逻辑。
- 新增 `setup_horizontal_placeholder_stage()`：
  - 使用 `create_placeholder_widget` 创建居中文本占位页，文本为“横校阶段（占位，后续任务实现）”。
  - 添加水平布局的“上一步”和“下一步”按钮。
  - “上一步”回到纵校阶段。
  - “下一步”进入精修阶段。
- 修改 `on_vertical_finished()`：
  - 纵校窗口释放后，直接调用 `setup_horizontal_placeholder_stage()`。
- 修改 `on_refine_back()`：
  - 从精修返回时，回到横校占位页（或直接回到纵校，视占位页导航而定）。
- 修改 `on_refine_finished()`：
  - 清理阶段窗口时一并清理 `horizontal_placeholder_widget_`。

### 3.3 `src/windows/verticalcheckwindow.h/cpp`（可选，顺手修改）

- 将注释中“进入横校前”改为“进入下一阶段前”，避免歧义。
- 不改动功能逻辑。

### 3.4 `CMakeLists.txt`

- 从 `SOURCES` 中移除 `src/windows/horizontalcheckwindow.cpp`。
- 从 `HEADERS` 中移除 `src/windows/horizontalcheckwindow.h`。
- `src/processors/ocr_engine.cpp/h` 保留在工程中（`PDFOutputGenerator` 可能仍依赖 `OCREngine` 中的其他功能；若编译无依赖可保留文件不编译）。

## 4. 重新编译与打包

1. 清理 `build/` 目录。
2. 重新运行 CMake 配置：
   ```powershell
   cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="C:/msys64/mingw64"
   ```
3. 编译：
   ```powershell
   cmake --build . --config Release
   ```
4. 运行 `deploy.bat` 部署到 `dist/`。
5. 验证 `dist\hengxiao_tool2.exe` 双击启动无报错。

## 5. 验证清单

- [ ] `src/windows/mainwindow.h` 中横校相关成员和 slots 已删除。
- [ ] `src/windows/mainwindow.cpp` 中横校逻辑已替换为占位页。
- [ ] `CMakeLists.txt` 中已移除 `horizontalcheckwindow.cpp/h`。
- [ ] 编译成功，生成 `build\hengxiao_tool2.exe` 和 `build\hengxiao_tool2_app.exe`。
- [ ] `deploy.bat` 成功，dist 目录包含两个 exe 及全部依赖。
- [ ] 双击 `dist\hengxiao_tool2.exe` 正常启动，无 0xc0000142 弹窗。
- [ ] 流程验证：导入 → 纵校 → 横校占位页 → 精修，导航按钮工作正常。

## 6. 假设与决策

1. **保留横校源文件**：不删除 `horizontalcheckwindow.h/cpp`，仅将其移出编译列表，方便后续任务恢复。
2. **保留 OCR 引擎文件**：`ocr_engine.cpp/h` 仍保留在工程中，虽然本次不再使用 `build_line_data`，但避免影响其他潜在依赖。
3. **占位页保持 4 步流程**：步骤指示器仍显示“导入/纵校/横校/精修”，其中“横校”仅显示占位内容。
4. **复用现有启动器**：沿用 `hengxiao_tool2.exe` 启动 `hengxiao_tool2_app.exe` 的方案解决 OpenSSL provider 路径问题。
