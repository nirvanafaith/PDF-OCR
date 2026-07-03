# 性能优化 Spec

## Why
当前软件在处理大型 PDF 时存在明显的性能瓶颈：PDF 输出 O(n*m) 复杂度、所有页面一次性加载到内存、数据加载阻塞 UI 线程、重复的图像转换操作等。

## What Changes
- PDF 输出按页预分组字符，O(n*m) → O(n+m)
- 页面图像懒加载 + LRU 缓存，内存占用从 O(全部页面) → O(5页)
- OCR 准备阶段数据加载移至工作线程，UI 不再冻结
- 精修/纵校窗口添加 QPixmap 缓存，避免重复 PIL→QPixmap 转换
- 纵校切片悬停添加缓存，避免鼠标移动时重复生成
- bbox 坐标转换提取为工具函数，消除代码重复
- JSON 保存优化，chars.json 使用紧凑格式

## Impact
- Affected code: `pdf_processor/pdf_output.py`, `pdf_processor/pdf_loader.py`, `ocr_engine/rapidocr_engine.py`, `ui/ocr_prepare_window.py`, `ui/vertical_check_window.py`, `ui/refine_window.py`

## ADDED Requirements

### Requirement: PDF 输出按页预分组
PDFOutputGenerator.generate SHALL 在页面循环前将 corrected_chars 按 page_num 预分组为字典，页面循环中只遍历当前页的字符。

#### Scenario: 大文档输出
- **WHEN** 生成包含 100 页 10000 字符的 PDF
- **THEN** 字符遍历次数从 1,000,000 降至约 10,000（每页平均 100 字符）

### Requirement: 页面图像懒加载
PDFProcessor SHALL 支持按需加载单页图像，使用 LRU 缓存（maxsize=5）管理最近访问的页面，不再一次性加载所有页面到内存。

#### Scenario: 大文档内存
- **WHEN** 打开 100 页 PDF
- **THEN** 内存中最多同时持有 5 页图像，而非 100 页

### Requirement: 数据加载不阻塞 UI
OCRPrepareWindow 的"下一步"操作 SHALL 在工作线程中执行 PDF 加载和字符分组，UI 保持响应。

#### Scenario: 加载过程
- **WHEN** 用户点击"下一步"
- **THEN** UI 保持响应，输出区域显示进度，按钮禁用直到完成

### Requirement: QPixmap 渲染缓存
纵校和精修窗口 SHALL 缓存当前页的 QPixmap，仅在页面或缩放比例变化时重新生成。

#### Scenario: 翻页后返回
- **WHEN** 用户从第 2 页翻回第 1 页（缩放不变）
- **THEN** 使用缓存的 QPixmap，不重新从 PIL 转换

### Requirement: 纵校切片悬停缓存
纵校窗口 eventFilter 中 SHALL 缓存当前悬停行的切片 QPixmap，同一行不重复生成。

#### Scenario: 鼠标在同一行移动
- **WHEN** 鼠标在同一行文本上移动
- **THEN** 不重新生成切片 QPixmap，复用缓存

### Requirement: bbox 坐标转换工具函数
系统 SHALL 提供 `flatten_bbox(bbox)` 工具函数，将 4 点坐标转换为 [x1, y1, x2, y2] 格式，消除代码重复。

### Requirement: JSON 紧凑保存
chars.json SHALL 使用紧凑格式（indent=None）保存，lines.json 保持 indent=2 可读格式。

## MODIFIED Requirements
无

## REMOVED Requirements
无
