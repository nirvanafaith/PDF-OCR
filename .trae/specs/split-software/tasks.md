# Tasks

- [x] Task 1: 创建软件1目录结构和复制共享模块
  - [x] SubTask 1.1: 创建 软件1/ 目录及子目录 (models/, ocr_engine/, pdf_processor/, ui/)
  - [x] SubTask 1.2: 复制 models/__init__.py, models/data_models.py 到 软件1/models/
  - [x] SubTask 1.3: 复制 ocr_engine/__init__.py, ocr_engine/rapidocr_engine.py 到 软件1/ocr_engine/
  - [x] SubTask 1.4: 复制 pdf_processor/__init__.py, pdf_processor/pdf_loader.py 到 软件1/pdf_processor/
  - [x] SubTask 1.5: 复制 ui/__init__.py, ui/styles.py, ui/zoom_utils.py, ui/draw_box_window.py, ui/ocr_prepare_window.py 到 软件1/ui/
  - [x] SubTask 1.6: 创建 软件1/requirements.txt

- [x] Task 2: 创建软件1的main.py
  - [x] SubTask 2.1: 编写2阶段MainWindow (画框 → OCR准备)
  - [x] SubTask 2.2: 包含StepIndicator组件
  - [x] SubTask 2.3: 包含NVIDIA DLL路径设置代码

- [x] Task 3: 创建软件2目录结构和复制共享模块
  - [x] SubTask 3.1: 创建 软件2/ 目录及子目录 (models/, ocr_engine/, pdf_processor/, ui/)
  - [x] SubTask 3.2: 复制 models/, ocr_engine/, pdf_processor/ (含pdf_output.py) 到 软件2/
  - [x] SubTask 3.3: 复制 ui/__init__.py, ui/styles.py, ui/zoom_utils.py, ui/vertical_check_window.py, ui/horizontal_check_window.py, ui/refine_window.py 到 软件2/ui/
  - [x] SubTask 3.4: 创建 软件2/requirements.txt

- [x] Task 4: 创建软件2的ImportWindow
  - [x] SubTask 4.1: 设计ImportWindow UI（PDF选择、JSON选择、加载按钮）
  - [x] SubTask 4.2: 实现PDF加载逻辑（使用PDFProcessor）
  - [x] SubTask 4.3: 实现JSON加载逻辑（使用OCREngine.load_results_from_file + parse_and_group）
  - [x] SubTask 4.4: 实现finished_signal发射(page_images, ocr_results, char_slices)

- [x] Task 5: 创建软件2的main.py
  - [x] SubTask 5.1: 编写4阶段MainWindow (导入 → 纵校 → 横校 → 精修)
  - [x] SubTask 5.2: 包含StepIndicator组件
  - [x] SubTask 5.3: 实现各阶段间的数据流转和信号连接

- [x] Task 6: 修改两个软件中UI模块的导入路径
  - [x] SubTask 6.1: 确保软件1中所有import使用相对路径正确
  - [x] SubTask 6.2: 确保软件2中所有import使用相对路径正确

- [x] Task 7: 测试验证
  - [x] SubTask 7.1: 运行软件1，确认无error和warning
  - [x] SubTask 7.2: 运行软件2，确认无error和warning

# Task Dependencies
- Task 2 depends on Task 1
- Task 4 depends on Task 3
- Task 5 depends on Task 3, Task 4
- Task 6 depends on Task 2, Task 5
- Task 7 depends on Task 6
