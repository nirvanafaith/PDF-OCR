# Tasks

- [x] Task 1: 在DrawBoxWindow工具栏添加"模型识别"按钮
  - [x] SubTask 1.1: 添加按钮到工具栏（在"导入JSON"按钮之后）
  - [x] SubTask 1.2: 添加 mineru_finished_signal 信号
  - [x] SubTask 1.3: 提取 _import_json_from_path(json_path) 方法（从_on_import_json中提取）
  - [x] SubTask 1.4: 实现 _on_mineru_recognize 方法（验证PDF、启动后台线程）
  - [x] SubTask 1.5: 实现 MinerU 后台运行逻辑（subprocess.Popen + CREATE_NEW_CONSOLE）
  - [x] SubTask 1.6: 实现查找最大JSON文件逻辑（递归搜索output目录）
  - [x] SubTask 1.7: 连接信号到导入逻辑

- [x] Task 2: 修改OCR准备阶段的JSON输出路径
  - [x] SubTask 2.1: 修改 _on_run_ocr 中的 output_dir 为软件1目录下的json/文件夹
  - [x] SubTask 2.2: 添加 import sys 到 ocr_prepare_window.py

- [x] Task 3: 测试验证
  - [x] SubTask 3.1: 运行软件1确认无error和warning
  - [x] SubTask 3.2: 验证"模型识别"按钮存在且可点击

# Task Dependencies
- Task 2 depends on nothing (independent)
- Task 3 depends on Task 1, Task 2
