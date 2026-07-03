# Tasks

- [x] Task 1: 软件1 OCR环节"下一步"按钮改名为"新书制作"
  - [x] SubTask 1.1: 修改 ocr_prepare_window.py 中 QPushButton("下一步") 为 QPushButton("新书制作")

- [x] Task 2: 软件1 OCR完成后复制原PDF到JSON文件夹
  - [x] SubTask 2.1: 在 rapidocr_engine.py 的 run_ocr 方法中添加 shutil.copy2 复制PDF

- [x] Task 3: 软件2移除OCR模型依赖
  - [x] SubTask 3.1: 修改 软件2/ocr_engine/rapidocr_engine.py，移除 RapidOCR 导入和引擎初始化，移除 run_ocr 方法
  - [x] SubTask 3.2: 修改 软件2/requirements.txt，移除 onnxruntime 和 rapidocr 行
  - [x] SubTask 3.3: 修改 软件2/main.py，移除 NVIDIA DLL 路径设置代码

- [x] Task 4: 测试验证
  - [x] SubTask 4.1: 运行软件1确认无error和warning
  - [x] SubTask 4.2: 运行软件2确认无error和warning

# Task Dependencies
- Task 1, 2, 3 are independent (can be parallelized)
- Task 4 depends on all previous tasks
