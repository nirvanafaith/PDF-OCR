# Tasks

- [x] Task 1: 创建 `PlaceholderWindow` 占位窗口组件
  - [x] SubTask 1.1: 新建 `src/windows/placeholderwindow.h`，声明 `PlaceholderWindow` 类（继承 QWidget），构造函数签名 `PlaceholderWindow(const QString& title, const QString& description, QWidget* parent = nullptr)`，声明信号 `next_signal()` 与 `back_signal()`，声明成员 `QLabel* title_label_`、`QLabel* desc_label_`、`QPushButton* next_btn_`、`QPushButton* back_btn_`
  - [x] SubTask 1.2: 新建 `src/windows/placeholderwindow.cpp`，实现构造函数：使用 QVBoxLayout 居中显示标题（字号 24pt 加粗）与描述（字号 12pt），底部 QHBoxLayout 放置「上一步」「下一步」按钮，连接 clicked 信号到 next_signal/back_signal 发射
  - [x] SubTask 1.3: 提供 `set_next_button_text(const QString&)` 方法，便于精修占位页将按钮文字改为「完成」

- [x] Task 2: 重构 `mainwindow.h` 头文件
  - [x] SubTask 2.1: 删除前向声明 `HorizontalCheckWindow`、`RefineWindow`、`OCREngine`
  - [x] SubTask 2.2: 添加前向声明 `PlaceholderWindow`
  - [x] SubTask 2.3: 删除成员 `horiz_widget_`、`refine_widget_`、`ocr_engine_`、`corrected_lines_`
  - [x] SubTask 2.4: 添加成员 `PlaceholderWindow* horiz_placeholder_ = nullptr;` 与 `PlaceholderWindow* refine_placeholder_ = nullptr;`
  - [x] SubTask 2.5: 删除槽函数声明 `on_horizontal_finished`、`on_horizontal_back`、`on_output_complete`、`on_refine_back`、`on_refine_finished`
  - [x] SubTask 2.6: 添加槽函数声明 `on_horizontal_placeholder_next`、`on_horizontal_placeholder_back`、`on_refine_placeholder_next`、`on_refine_placeholder_back`
  - [x] SubTask 2.7: 删除私有方法声明 `setup_horizontal_stage`、`setup_refine_stage`，添加 `setup_horizontal_placeholder`、`setup_refine_placeholder`

- [x] Task 3: 重构 `mainwindow.cpp` 实现文件
  - [x] SubTask 3.1: 删除 include `windows/horizontalcheckwindow.h`、`windows/refinewindow.h`、`processors/ocr_engine.h`，添加 include `windows/placeholderwindow.h`
  - [x] SubTask 3.2: 构造函数删除 `ocr_engine_ = new OCREngine()`，析构函数删除 `delete ocr_engine_`
  - [x] SubTask 3.3: `on_vertical_finished` 中将 `setup_horizontal_stage()` 调用改为 `setup_horizontal_placeholder()`，删除 `corrected_lines_` 相关逻辑
  - [x] SubTask 3.4: 删除 `setup_horizontal_stage`、`setup_refine_stage`、`on_horizontal_finished`、`on_horizontal_back`、`on_output_complete`、`on_refine_back`、`on_refine_finished` 全部实现
  - [x] SubTask 3.5: 实现 `setup_horizontal_placeholder`：构造 `PlaceholderWindow`（标题「横校」、描述「横校功能正在开发中，敬请期待」），连接 `next_signal`→`on_horizontal_placeholder_next`、`back_signal`→`on_horizontal_placeholder_back`，加入 stack 并设为当前页，`step_indicator_->set_current(2)`
  - [x] SubTask 3.6: 实现 `setup_refine_placeholder`：构造 `PlaceholderWindow`（标题「精修」、描述「精修功能正在开发中，敬请期待」），调用 `set_next_button_text("完成")`，连接信号到对应槽，加入 stack 并设为当前页，`step_indicator_->set_current(3)`
  - [x] SubTask 3.7: 实现 `on_horizontal_placeholder_next`：`current_stage_=3`，`step_indicator_->set_current(3)`，调用 `setup_refine_placeholder`
  - [x] SubTask 3.8: 实现 `on_horizontal_placeholder_back`：销毁横校占位页，重建纵校窗口（用保存的 `char_slices_`、`page_images_`、`ocr_results_`），`step_indicator_->set_current(1)`
  - [x] SubTask 3.9: 实现 `on_refine_placeholder_next`：清理所有阶段窗口与数据，`current_stage_=0`，调用 `setup_import_stage()` 回到导入阶段
  - [x] SubTask 3.10: 实现 `on_refine_placeholder_back`：销毁精修占位页，切换回横校占位页（若已销毁则重建），`step_indicator_->set_current(2)`

- [x] Task 4: 删除横校与精修相关源文件
  - [x] SubTask 4.1: 删除 `src/windows/horizontalcheckwindow.h` 与 `src/windows/horizontalcheckwindow.cpp`
  - [x] SubTask 4.2: 删除 `src/windows/refinewindow.h` 与 `src/windows/refinewindow.cpp`
  - [x] SubTask 4.3: 删除 `src/windows/movabletextitem.h` 与 `src/windows/movabletextitem.cpp`
  - [x] SubTask 4.4: 删除 `src/processors/pdf_output_generator.h` 与 `src/processors/pdf_output_generator.cpp`
  - [x] SubTask 4.5: 删除 `src/processors/pdf_output_worker.h` 与 `src/processors/pdf_output_worker.cpp`

- [x] Task 5: 清理 `OCREngine::build_line_data`
  - [x] SubTask 5.1: 在 `src/processors/ocr_engine.h` 中删除 `build_line_data` 方法声明及其文档注释
  - [x] SubTask 5.2: 在 `src/processors/ocr_engine.cpp` 中删除 `build_line_data` 方法实现

- [x] Task 6: 清理 `datamodels.h` 中仅横校/精修使用的数据类型
  - [x] SubTask 6.1: 删除 `struct LineSlice` 及其 `to_json`/`from_json` 重载
  - [x] SubTask 6.2: 删除 `struct CorrectedChar` 及其 `NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE` 宏
  - [x] SubTask 6.3: 删除 `struct CorrectedLine` 及其宏
  - [x] SubTask 6.4: 删除 `struct RefineTextItem` 及其宏
  - [x] SubTask 6.5: 删除 `struct HorizontalCheckData` 及其 `to_json`/`from_json` 重载
  - [x] SubTask 6.6: 删除 `struct FinalCharList` 及其 `to_json`/`from_json` 重载
  - [x] SubTask 6.7: 保留 `TextLine`、`OCRPageResult`、`OCRResult`、`CharSlice`、`VerticalCheckData` 及 `OcrResults`/`CharSliceMap` 别名（导入/纵校仍需使用）

- [x] Task 7: 更新 `CMakeLists.txt` 源文件列表
  - [x] SubTask 7.1: 从 `SOURCES` 列表删除 `src/windows/horizontalcheckwindow.cpp`、`src/windows/refinewindow.cpp`、`src/windows/movabletextitem.cpp`、`src/processors/pdf_output_generator.cpp`、`src/processors/pdf_output_worker.cpp`
  - [x] SubTask 7.2: 从 `HEADERS` 列表删除对应的 5 个 `.h` 文件
  - [x] SubTask 7.3: 在 `SOURCES` 添加 `src/windows/placeholderwindow.cpp`，在 `HEADERS` 添加 `src/windows/placeholderwindow.h`

- [x] Task 8: 重新构建项目
  - [x] SubTask 8.1: 设置 MSYS2 MinGW PATH（`$env:PATH = "C:\msys64\mingw64\bin;" + $env:PATH`）
  - [x] SubTask 8.2: 删除 `build/CMakeCache.txt` 强制重新 configure（CMakeLists.txt 已修改）
  - [x] SubTask 8.3: 运行 `cmake -G Ninja -B build -S . -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5` 重新配置
  - [x] SubTask 8.4: 运行 `cmake --build build --config Release` 编译，确认无错误无警告（17/17 目标全部成功）
  - [x] SubTask 8.5: 无编译错误，无需修复

- [x] Task 9: 重新打包部署
  - [x] SubTask 9.1: deploy.bat 因编码问题无法从 PowerShell 调用，改为直接复制 build\hengxiao_tool2.exe 到 deploy\ 目录（依赖项未变）
  - [x] SubTask 9.2: 验证 `deploy/` 目录下 `hengxiao_tool2.exe`（17.5MB）、`run.bat`、`resources/styles.qss`、`platforms/qwindows.dll`、`lib/ossl-modules/legacy.dll` 均存在
  - [x] SubTask 9.3: 双击 `deploy/run.bat` 启动应用，确认窗口标题为「横校工具」，内存 83.5MB，UI 响应正常
  - [x] SubTask 9.4: 提供启动方法说明给用户

# Task Dependencies

- Task 1（PlaceholderWindow）独立，可与 Task 4、Task 5、Task 6、Task 7 并行
- Task 2、Task 3（mainwindow 重构）依赖 Task 1 完成
- Task 4、Task 5、Task 6、Task 7 互相独立，可并行
- Task 8（构建）依赖 Task 1-7 全部完成
- Task 9（部署）依赖 Task 8 成功
