# 修复计划：PDF文件导入报错"文件不是有效的PDF"

## 根因分析

**问题现象**：用户导入 `图片PDF文字识别与人工校正系统详细设计文档.pdf` 时，程序报错"文件不是有效的PDF"。

**根因**：`pdf2image` 库依赖系统安装的 Poppler 工具（`pdfinfo`、`pdftoppm` 等命令行程序）来处理 PDF。当前系统上 Poppler 安装不完整或版本不兼容（`pdfinfo` 返回退出码 3221225781 = Windows DLL 加载失败），导致 `pdf2image.convert_from_path()` 抛出 `PDFPageCountError`，被代码捕获后显示"文件不是有效的PDF"。

**证据**：
1. `pdfinfo` 命令返回退出码 3221225781（Windows DLL 缺失/不兼容）
2. `pdf2image` 抛出 `PDFPageCountError: Unable to get page count`
3. 同一 PDF 文件用 PyMuPDF (fitz) 可以正常打开和渲染（30页，渲染成功）
4. Poppler 不是 Python 包，无法通过 pip 安装，需要手动下载配置，对用户不友好

**解决方案**：将 PDF 转图像的引擎从 `pdf2image`（依赖 Poppler）切换为 `PyMuPDF`（纯 Python 包，pip 直接安装），彻底消除 Poppler 依赖问题。

## 修改步骤

### 步骤 1：修改 `requirements.txt`
- 移除 `pdf2image`
- 添加 `PyMuPDF`（即 `fitz`）

### 步骤 2：修改 `pdf_processor/pdf_loader.py`
- 移除 `from pdf2image import convert_from_path` 和 `from pdf2image.exceptions import PDFPageCountError, PDFSyntaxError`
- 添加 `import fitz`
- 重写 `convert_to_images` 方法：
  - 使用 `fitz.open(pdf_path)` 打开 PDF
  - 遍历每页，使用 `page.get_pixmap(dpi=dpi)` 渲染为图像
  - 将 pixmap 转为 PIL Image：`Image.frombytes("RGB", [pix.width, pix.height], pix.samples)`
  - 错误处理：文件不存在、无效PDF、加密PDF等

### 步骤 3：修改 `pdf_processor/pdf_output.py`
- 当前代码使用 `reportlab` 生成双层 PDF，不依赖 `pdf2image`，无需修改
- 但需确认 `ImageReader` 接受 PIL Image 对象（当前已支持），无需改动

### 步骤 4：验证
- 运行 `python -c "from pdf_processor.pdf_loader import PDFProcessor; p = PDFProcessor(); imgs = p.convert_to_images(r'c:\Users\E-VR\Documents\trae_projects\横校\图片PDF文字识别与人工校正系统详细设计文档.pdf'); print(f'成功: {len(imgs)} 页')"` 确认可正常导入目标 PDF

## 影响范围
- `requirements.txt`：替换依赖
- `pdf_processor/pdf_loader.py`：重写 PDF 转图像逻辑
- 其他模块：不受影响（接口 `convert_to_images(pdf_path) -> list[PIL.Image]` 保持不变）
