# Tasks

- [x] Task 1: 修改 ocr_engine/surya_engine.py，支持实时流式输出
  - [x] SubTask 1.1: 修改 run_ocr 方法，将 subprocess.run 改为 subprocess.Popen，使用 PIPE 实时读取 stdout/stderr
  - [x] SubTask 1.2: 添加 output_callback 参数，每读取一行输出就调用回调函数
  - [x] SubTask 1.3: 保留原有的错误处理和结果文件读取逻辑

- [x] Task 2: 创建 ui/ocr_prepare_window.py，实现OCR准备界面
  - [x] SubTask 2.1: 创建 OCRPrepareWindow 类（QMainWindow），接收 pdf_path 参数
  - [x] SubTask 2.2: 实现界面布局：PDF路径显示、JSON路径输入框+浏览按钮、"使用本地模型识别"按钮、CMD输出文本区域（QTextEdit只读）、"下一步"按钮
  - [x] SubTask 2.3: 实现"使用本地模型识别"逻辑：在QThread中执行surya_ocr，实时输出到文本区域，完成后自动填入JSON路径
  - [x] SubTask 2.4: 实现"选择JSON文件"逻辑：文件对话框选择results.json，路径填入输入框
  - [x] SubTask 2.5: 实现"下一步"逻辑：加载PDF图像、解析JSON、构建char_slices，通过finished_signal发出
  - [x] SubTask 2.6: 实现按钮状态管理：JSON路径为空时"下一步"禁用，OCR执行中"识别"按钮禁用

- [x] Task 3: 修改 main.py，串联新流程
  - [x] SubTask 3.1: 修改 _on_select_pdf 方法，选择PDF后显示OCRPrepareWindow而非直接执行OCR
  - [x] SubTask 3.2: 移除 OCRWorker 类和 progress_dialog 相关代码
  - [x] SubTask 3.3: 连接 OCRPrepareWindow 的 finished_signal 到横校入口

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 2]
