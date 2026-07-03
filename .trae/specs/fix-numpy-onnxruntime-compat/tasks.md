# Tasks

- [x] Task 1: 修改 requirements.txt，添加 numpy<2 版本约束
  - [x] SubTask 1.1: 在 requirements.txt 中添加 `numpy<2` 行，确保位于其他依赖之前
- [x] Task 2: 降级当前运行环境的 NumPy 版本
  - [x] SubTask 2.1: 执行 `pip install "numpy==1.26.4" --force-reinstall --no-deps` 将 NumPy 2.3.5 降级为 1.26.4
  - [x] SubTask 2.2: 验证 NumPy 版本已降级（`python -c "import numpy; print(numpy.__version__)"`）
- [x] Task 3: 验证 onnxruntime 可正常导入
  - [x] SubTask 3.1: 执行 `python -c "import onnxruntime; print(onnxruntime.__version__)"` 确认无报错
- [x] Task 4: 升级 onnxruntime 到 ≥1.19.0 以支持 ONNX IR version 10
  - [x] SubTask 4.1: 在 requirements.txt 中添加 `onnxruntime>=1.19.0` 版本约束
  - [x] SubTask 4.2: 执行 `pip install "onnxruntime>=1.19.0" --upgrade` 升级 onnxruntime（升级到 1.26.0）
  - [x] SubTask 4.3: 验证 onnxruntime 版本已升级
- [x] Task 5: 验证 RapidOCR 引擎可正常初始化（含模型加载）
  - [x] SubTask 5.1: 执行 `python -c "from ocr_engine import OCREngine; engine = OCREngine(); print('OCREngine OK')"` 确认无报错
- [x] Task 6: 验证应用程序可正常启动
  - [x] SubTask 6.1: 运行 `python main.py`，确认窗口正常显示无崩溃

# Task Dependencies
- Task 4 depends on Task 2 (numpy must be downgraded first)
- Task 5 depends on Task 4
- Task 6 depends on Task 5
