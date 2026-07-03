# Tasks

- [x] Task 1: 修复 main.py 中 ocr_results 的传递与接收
  - [x] SubTask 1.1: 修改 _on_prepare_finished 中 HorizontalCheckWindow 构造调用，传入 self.ocr_results 作为第三个参数
  - [x] SubTask 1.2: 修改 _on_horizontal_check_finished 方法签名，接收两个参数 (updated_char_slices, updated_ocr_results)，并更新 self.ocr_results

- [x] Task 2: 修改 SliceItemWidget 图片缩放方式为强制统一尺寸
  - [x] SubTask 2.1: 将 pixmap.scaled(80, 80, KeepAspectRatio) 改为 pixmap.scaled(80, 80, KeepAspectRatioByExpanding)，确保所有切片视觉大小完全一致

# Task Dependencies
- Task 2 独立于 Task 1，可并行执行
