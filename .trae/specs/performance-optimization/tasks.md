# Tasks

- [x] Task 1: PDF 输出按页预分组 - O(n*m) → O(n+m)
  - [x] 在 generate 方法中，页面循环前将 corrected_chars 按 page_num 分组为 dict
  - [x] 页面循环中只遍历当前页的字符列表

- [x] Task 2: 页面图像懒加载 + LRU 缓存
  - [x] PDFProcessor 添加 LazyPageLoader 类，持有 fitz.Document 引用
  - [x] 实现 get_page(page_num) 方法，使用 LRU 缓存最近 5 页
  - [x] 保留 convert_to_images 方法兼容性
  - [x] 添加 get_page_count 和 get_lazy_loader 方法

- [x] Task 3: OCR 准备阶段数据加载移至工作线程
  - [x] 在 OCRPrepareWindow 中添加 DataLoadWorker
  - [x] _on_next 方法中启动工作线程执行 convert_to_images + parse_and_group
  - [x] 完成后通过信号传递结果

- [x] Task 4: 精修窗口 QPixmap 缓存
  - [x] 添加 _pixmap_cache 字典，key 为 (page_num, zoom_level)
  - [x] _render_page 中先查缓存，命中则直接使用

- [x] Task 5: 纵校窗口切片悬停缓存 + QPixmap 缓存
  - [x] 添加 _slice_cache_id/_slice_cache_pixmap 缓存当前悬停行的切片
  - [x] eventFilter 中同一行不重复生成切片
  - [x] 添加 _pixmap_cache 缓存当前页 QPixmap

- [x] Task 6: bbox 坐标转换工具函数
  - [x] 在 models/data_models.py 中添加 flatten_bbox 函数
  - [x] 替换 rapidocr_engine.py 中 3 处重复的 bbox 转换代码

- [x] Task 7: JSON 紧凑保存
  - [x] chars.json 使用 json.dump(data, f, ensure_ascii=False) 无 indent
  - [x] lines.json 保持 indent=2

# Task Dependencies
- Task 1, 6, 7 独立，可并行
- Task 3, 4, 5 独立，可并行
