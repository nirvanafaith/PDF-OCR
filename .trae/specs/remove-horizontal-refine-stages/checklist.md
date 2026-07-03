# Verification Checklist

## 代码删除验证
- [x] `src/windows/horizontalcheckwindow.h` 与 `src/windows/horizontalcheckwindow.cpp` 已删除
- [x] `src/windows/refinewindow.h` 与 `src/windows/refinewindow.cpp` 已删除
- [x] `src/windows/movabletextitem.h` 与 `src/windows/movabletextitem.cpp` 已删除
- [x] `src/processors/pdf_output_generator.h` 与 `src/processors/pdf_output_generator.cpp` 已删除
- [x] `src/processors/pdf_output_worker.h` 与 `src/processors/pdf_output_worker.cpp` 已删除
- [x] `OCREngine::build_line_data` 方法已从 `ocr_engine.h` 与 `ocr_engine.cpp` 中删除
- [x] `datamodels.h` 中 `LineSlice`、`CorrectedChar`、`CorrectedLine`、`RefineTextItem`、`HorizontalCheckData`、`FinalCharList` 及其序列化代码已删除
- [x] `CMakeLists.txt` 的 `SOURCES` 与 `HEADERS` 列表已更新（删除 5 组文件，添加 placeholderwindow）

## 保留功能验证
- [x] `StepIndicator` 四阶段指示器在 `mainwindow.cpp` 中仍以「导入/纵校/横校/精修」四项构造
- [x] `OCREngine::load_results_from_file` 与 `parse_and_group` 方法仍存在且未被修改
- [x] `ImportWindow`、`VerticalCheckWindow`、`PDFProcessor`、`lazy_page_loader`、`utils/*` 文件未被修改
- [x] `main.cpp` 中 `OPENSSL_MODULES` 环境变量设置代码仍保留
- [x] `build.bat`、`deploy.bat` 未被修改

## 新增代码验证
- [x] `src/windows/placeholderwindow.h` 已创建，声明 `PlaceholderWindow` 类继承 QWidget，含 Q_OBJECT 宏
- [x] `src/windows/placeholderwindow.cpp` 已创建，实现构造函数、按钮信号连接、`set_next_button_text` 方法
- [x] `PlaceholderWindow` 发射 `next_signal()` 与 `back_signal()` 两个信号
- [x] 占位窗口 UI 居中显示标题（大字号）与描述（普通字号），底部「上一步」「下一步」按钮

## mainwindow 重构验证
- [x] `mainwindow.h` 不再包含 `HorizontalCheckWindow`、`RefineWindow`、`OCREngine` 的前向声明
- [x] `mainwindow.h` 不再包含 `horiz_widget_`、`refine_widget_`、`ocr_engine_`、`corrected_lines_` 成员
- [x] `mainwindow.h` 新增 `horiz_placeholder_` 与 `refine_placeholder_` 成员
- [x] `mainwindow.cpp` 不再 include `horizontalcheckwindow.h`、`refinewindow.h`、`ocr_engine.h`
- [x] `mainwindow.cpp` 不再调用 `ocr_engine_->build_line_data`
- [x] `on_vertical_finished` 调用 `setup_horizontal_placeholder()` 而非 `setup_horizontal_stage()`
- [x] `setup_horizontal_placeholder` 构造的占位页标题为「横校」、描述含「横校功能正在开发中」
- [x] `setup_refine_placeholder` 构造的占位页标题为「精修」、「下一步」按钮文字改为「完成」
- [x] 横校占位「上一步」能重建纵校窗口（使用保存的 char_slices_/page_images_/ocr_results_）
- [x] 精修占位「完成」能清理所有窗口并回到导入阶段

## 编译验证
- [x] `cmake -G Ninja -B build -S .` 配置成功，无错误
- [x] `cmake --build build --config Release` 编译成功（17/17 目标），无错误无警告
- [x] 构建产物 `build/hengxiao_tool2.exe` 已生成（17.5MB）

## 部署与运行验证
- [x] `deploy/` 目录已更新（新 exe 已复制覆盖旧 exe）
- [x] `deploy/hengxiao_tool2.exe` 存在且为新编译版本（17.5MB，时间戳 2026-07-03 08:28:47）
- [x] `deploy/run.bat` 存在（启动器预设 OPENSSL_MODULES）
- [x] `deploy/lib/ossl-modules/legacy.dll` 存在（144KB）
- [x] `deploy/platforms/qwindows.dll` 存在（1.2MB）
- [x] `deploy/resources/styles.qss` 存在（5.7KB）
- [x] 双击 `deploy/run.bat` 启动应用，窗口标题为「横校工具」
- [x] 顶部 StepIndicator 显示「导入 → 纵校 → 横校 → 精修」四个阶段（代码层面验证）
- [x] 应用启动后内存 83.5MB（正常水平），UI 响应正常（Responding: True）
- [x] 导入阶段功能不受影响（纵校阶段前置功能，代码未被修改）

## 启动方法说明
- [x] 已向用户提供启动方法（`deploy/run.bat` 双击或命令行运行）
