# 修复计划：surya_ocr 输出路径问题

## 问题分析

### 现象
- surya_ocr 生成的 results.json 保存在：`C:\Users\E-VR\AppData\Local\Temp\surya_ocr_5ffkffse\图片PDF文字识别与人工校正系统详细设计文档\results.json`
- 代码查找的路径：`C:\Users\E-VR\AppData\Local\Temp\surya_ocr_5ffkffse\results.json`
- 报错：`OCR结果文件不存在`

### 根因
surya_ocr CLI 的行为：当执行 `surya_ocr "file.pdf" --output_dir "output_dir"` 时，surya_ocr 会在 `output_dir` 下创建一个以 **PDF文件名（去掉扩展名）** 命名的子目录，然后在该子目录下保存 `results.json`。

例如：
```
surya_ocr "C:\path\文档.pdf" --output_dir "C:\temp\surya_ocr_xxx"
→ 实际输出: C:\temp\surya_ocr_xxx\文档\results.json
```

### 用户需求
生成的 JSON 直接放在 PDF 文件旁边同一级目录，而非临时目录。

## 修复方案

### 修复1: ui/ocr_prepare_window.py

修改 `_on_run_ocr` 方法：
- 将 output_dir 设置为 PDF 所在目录
- 修正 JSON 路径计算

```python
# 修改前
import tempfile
output_dir = tempfile.mkdtemp(prefix="surya_ocr_")

# 修改后
import os
pdf_dir = os.path.dirname(self.pdf_path)
output_dir = pdf_dir if pdf_dir else "."
```

修改 `_on_ocr_finished` 方法：
- 正确计算 JSON 路径：`output_dir/{pdf_filename_without_ext}/results.json`

```python
# 修改前
json_path = output_dir.replace("\\", "/") + "/results.json"

# 修改后
pdf_basename = os.path.splitext(os.path.basename(self.pdf_path))[0]
json_path = os.path.join(output_dir, pdf_basename, "results.json")
```

### 修复2: ocr_engine/surya_engine.py

修改 `run_ocr` 方法中 results.json 的查找路径：

```python
# 修改前
results_path = os.path.join(output_dir, "results.json")

# 修改后
pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
results_path = os.path.join(output_dir, pdf_basename, "results.json")
```

## 修改文件清单

1. `ui/ocr_prepare_window.py`
   - 修改 `_on_run_ocr`: output_dir 设为 PDF 所在目录
   - 修改 `_on_ocr_finished`: 正确计算 JSON 路径

2. `ocr_engine/surya_engine.py`
   - 修改 `run_ocr`: 正确计算 results.json 路径
