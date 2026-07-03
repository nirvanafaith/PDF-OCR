# Tasks

- [x] Task 1: 新增 TextBox 数据模型
  - [x] 在 `models/data_models.py` 中添加 `TextBox` dataclass，包含 `page_num: int` 和 `bbox: List[float]` 字段

- [x] Task 2: 创建画框步骤窗口 `ui/draw_box_window.py`
  - [x] 实现 `DrawBoxWindow` 类，继承 QWidget
  - [x] 实现 PDF 加载和页面浏览（选择PDF按钮、上一页/下一页、页码显示）
  - [x] 使用 QGraphicsView/QGraphicsScene 显示 PDF 页面图像
  - [x] 实现鼠标拖拽绘制蓝色边框透明填充矩形框
  - [x] 实现右键菜单删除已有框
  - [x] 实现"完成"按钮，发射 `finished_signal(str, dict)` 信号（pdf_path, regions）
  - [x] 实现 `_pil_to_pixmap` 辅助方法

- [x] Task 3: 修改 `OCREngine.run_ocr` 支持区域限制
  - [x] 添加 `regions` 可选参数，类型 `dict[int, list[list[float]]]`
  - [x] 当 regions 不为空时，对每页裁剪框区域图像进行OCR，再将坐标映射回整页绝对坐标
  - [x] 当 regions 为空时保持原有整页识别行为

- [x] Task 4: 修改 `OCRPrepareWindow` 接收区域信息
  - [x] 修改 `__init__` 接收 `regions` 参数并保存
  - [x] 修改 `_on_run_ocr` 将 `regions` 传递给 `OCRWorker`
  - [x] 修改 `OCRWorker` 将 `regions` 传递给 `ocr_engine.run_ocr`
  - [x] 修改 `DataLoadWorker` 在 `parse_and_group` 中过滤框外字符

- [x] Task 5: 修改 `MainWindow` 集成画框步骤
  - [x] 修改 `STAGES` 为 `["画框", "OCR准备", "横校", "纵校", "精修"]`
  - [x] 新增 `_setup_draw_box_stage` 方法创建 DrawBoxWindow
  - [x] 新增 `_on_draw_box_finished` 回调，传递 pdf_path 和 regions 给 OCRPrepareWindow
  - [x] 修改 `_setup_prepare_stage` 接收 pdf_path 和 regions 参数
  - [x] 调整所有步骤索引（+1）和返回逻辑

- [x] Task 6: 编译验证所有修改文件
  - [x] 对所有修改过的 .py 文件执行 `python -m py_compile` 验证无语法错误

# Task Dependencies
- Task 1 → Task 2（DrawBoxWindow 使用 TextBox 数据模型）
- Task 1 → Task 3（OCREngine 使用 TextBox 的 bbox 格式）
- Task 2 → Task 5（MainWindow 需要导入 DrawBoxWindow）
- Task 3 → Task 4（OCRPrepareWindow 需要新的 run_ocr 接口）
- Task 4 → Task 5（MainWindow 需要传递 regions 给 OCRPrepareWindow）
- Task 5 → Task 6（最后统一验证）
