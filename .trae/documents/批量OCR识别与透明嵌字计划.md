# 批量OCR识别与透明嵌字计划

## 任务概述
将 `C:\Users\E-VR\Desktop\U盘书\新书` 目录下的 1.pdf、2.pdf、3.pdf 按顺序拼接成一本名为"铁路客货运输2025-6"的书，然后使用当前项目的 RapidOCR 引擎进行识别，并将识别结果以透明文字嵌回 PDF。

## 实现方案

创建一个独立脚本 `batch_ocr.py`，放在项目根目录下，复用项目现有模块完成全部操作。

### 步骤 1：合并 PDF

- 使用 PyMuPDF（fitz，已是项目依赖）合并三个 PDF
- 输入：`C:\Users\E-VR\Desktop\U盘书\新书\1.pdf`、`2.pdf`、`3.pdf`
- 输出：`C:\Users\E-VR\Desktop\U盘书\新书\铁路客货运输2025-6.pdf`
- 实现方式：`fitz.open()` 逐个打开，用 `insert_pdf()` 按顺序插入，最后 `save()`

### 步骤 2：OCR 识别

- 复用 `pdf_processor.PDFProcessor.convert_to_images()` 将合并后的 PDF 转为页面图像
- 复用 `ocr_engine.OCREngine.run_ocr()` 对所有页面执行 OCR 识别
- 得到 `(lines, chars)` 结果，chars 中包含每个字符的 text、bbox、page_num 等信息

### 步骤 3：构建 CorrectedChar 列表

- 遍历 OCR 结果中的 chars 列表
- 对每个 char 的 bbox 使用 `flatten_bbox()` 将多边形格式转为 `[x1, y1, x2, y2]` 矩形格式
- 构建 `CorrectedChar(text=char["char"], bbox=flatten_bbox(char["box"]), page_num=char["page_num"], ignored=False)` 列表
- 跳过手动校正阶段（横校、纵校、精修），直接使用原始 OCR 结果

### 步骤 4：生成透明嵌字 PDF

- 复用 `pdf_processor.pdf_output.PDFOutputGenerator.generate()` 方法
- 传入 `text_color="transparent"` 参数
- 现有代码使用 `Color(0, 0, 0, alpha=0)` 实现透明文字，文字不可见但可被 PDF 阅读器选中/搜索
- 输出：`C:\Users\E-VR\Desktop\U盘书\新书\铁路客货运输2025-6_透明.pdf`

### 步骤 5：验证透明文字的可选中性

- 检查 reportlab 的 `Color(0, 0, 0, alpha=0)` 是否能产生可选中/可搜索的文字
- 若不可选中，需改用 `canvas.setTextRenderMode(3)`（PDF 规范中的渲染模式 3 = 不可见但可选中）
- 此步骤在脚本运行后通过打开生成的 PDF 验证

## 涉及文件

| 操作 | 文件路径 |
|------|---------|
| 新建 | `c:\Users\E-VR\Documents\trae_projects\横校\batch_ocr.py` |
| 可能修改 | `c:\Users\E-VR\Documents\trae_projects\横校\pdf_processor\pdf_output.py`（若需改用 setTextRenderMode） |

## 依赖

全部使用项目已有依赖，无需安装新包：
- PyMuPDF (fitz)：PDF 合并与页面渲染
- rapidocr：OCR 识别引擎
- reportlab：PDF 生成
- Pillow：图像处理

## 脚本使用方式

```bash
cd c:\Users\E-VR\Documents\trae_projects\横校
python batch_ocr.py
```

脚本将自动完成：合并 → OCR → 透明嵌字，并在控制台输出进度信息。
