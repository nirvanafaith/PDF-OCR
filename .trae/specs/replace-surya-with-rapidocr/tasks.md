# Tasks

## Task 1: 创建 RapidOCR 引擎模块
- [x] SubTask 1.1: 新建 `ocr_engine/rapidocr_engine.py`，实现 `OCREngine` 类
  - 使用 RapidOCR + Paddle 后端初始化
  - 实现 `run_ocr(pdf_path, output_dir, output_callback)` 方法
  - 实现 `load_results_from_file(lines_json_path, chars_json_path)` 方法
  - 实现 `parse_and_group(results, page_images)` 方法
  - 实现 `build_line_data(results, page_images, char_slices)` 方法
- [x] SubTask 1.2: 修改 `ocr_engine/__init__.py`，从 rapidocr_engine 导入 OCREngine
- [x] SubTask 1.3: 删除 `ocr_engine/surya_engine.py`

## Task 2: 修改数据模型
- [x] SubTask 2.1: 修改 `models/data_models.py`
  - `CharSlice` 增加 `line_id` 字段，用于关联 RapidOCR 的行
  - 确保 `LineSlice` 和 `CharSlice` 兼容新引擎的输出字段

## Task 3: 修改 OCR 准备界面
- [x] SubTask 3.1: 修改 `ui/ocr_prepare_window.py`
  - 将 `OCRWorker` 改为调用 RapidOCR 引擎的 `run_ocr`
  - 修改 `_on_run_ocr`，移除 `surya_ocr` 命令行提示文本
  - 修改 `_on_ocr_finished`，自动填入 lines.json 和 chars.json 路径
  - 修改 `_on_next`，支持加载两个 JSON 文件并解析
  - 增加 chars.json 的文件选择输入框

## Task 4: 修改横校界面
- [x] SubTask 4.1: 修改 `ui/horizontal_check_window.py`
  - 修改 `_update_ocr_results_char`，适配 RapidOCR 的数据结构（`results` 现在是 `(lines, chars)` 元组）
  - 确保重定位操作同步更新 chars 数据

## Task 5: 修改纵校界面
- [x] SubTask 5.1: 修改 `ui/vertical_check_window.py`
  - 确保 `LineSlice` 的数据结构兼容（RapidOCR 的 box 格式为 4 点坐标）
  - 检查悬浮提示的裁剪逻辑是否正常工作

## Task 6: 修改主程序入口
- [x] SubTask 6.1: 修改 `main.py`
  - 确保 `ocr_results` 的数据结构从 dict 改为 `(lines, chars)` 元组后的传递逻辑正确

## Task 7: 验证与清理
- [x] SubTask 7.1: 全局搜索 `surya`，确保所有引用已移除
- [x] SubTask 7.2: 检查 `requirements.txt`，移除 surya 相关依赖（如有）

# Task Dependencies
- Task 2 依赖 Task 1（数据模型需要了解引擎输出格式）
- Task 3 依赖 Task 1 和 Task 2
- Task 4 依赖 Task 3
- Task 5 依赖 Task 4
- Task 6 依赖 Task 3
- Task 7 依赖 Task 1-6
