# 修复MinerU自动导入JSON路径检测

## 问题分析

当前 `_on_mineru_recognize` 方法在MinerU解析完成后，在整个 `output/` 目录中搜索最大的JSON文件。如果output目录下有多本书的解析结果，就会搜到别的书的JSON，导致导入错误。

MinerU的输出路径结构：
```
output/
  27424 智慧工地技术 正文1-1/
    hybrid_ocr/
      27424 智慧工地技术 正文1-1_middle.json   ← 应该导入这个
      27424 智慧工地技术 正文1-1_model.json
      27424 智慧工地技术 正文1-1_content_list_v2.json
      ...
  另一本书名/
    hybrid_ocr/
      另一本书名_middle.json   ← 不应该导入这个
```

## 修复方案

修改 `_on_mineru_recognize` 中的JSON搜索逻辑：

1. 根据当前PDF文件名（去掉扩展名），定位到对应的子目录：`output/<PDF名>/hybrid_ocr/`
2. 只在该子目录中搜索JSON文件
3. 优先选择 `_middle.json`（因为其格式最完整，坐标为PDF点坐标，转换最精确）
4. 如果没有middle.json，再选择该子目录中最大的JSON

### 修改文件

**文件**: `软件1/ui/draw_box_window.py`

**修改位置**: `_on_mineru_recognize` 方法中的JSON搜索逻辑（约252-262行）

**修改内容**:
```python
# 当前代码（有bug）：
largest_json = None
largest_size = 0
for root, dirs, files in os.walk(output_dir):
    for f in files:
        if f.endswith('.json'):
            fpath = os.path.join(root, f)
            fsize = os.path.getsize(fpath)
            if fsize > largest_size:
                largest_size = fsize
                largest_json = fpath

# 修改为：
pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
pdf_output_dir = os.path.join(output_dir, pdf_basename, "hybrid_ocr")
largest_json = None
if os.path.isdir(pdf_output_dir):
    # 优先选择 _middle.json
    middle_json = os.path.join(pdf_output_dir, f"{pdf_basename}_middle.json")
    if os.path.isfile(middle_json):
        largest_json = middle_json
    else:
        # 回退：在该子目录中选择最大的JSON
        largest_size = 0
        for f in os.listdir(pdf_output_dir):
            if f.endswith('.json'):
                fpath = os.path.join(pdf_output_dir, f)
                fsize = os.path.getsize(fpath)
                if fsize > largest_size:
                    largest_size = fsize
                    largest_json = fpath
```

## 验证步骤

1. 运行软件1，导入PDF
2. 点击"模型识别"按钮
3. MinerU解析完成后，确认导入的是当前PDF对应的JSON
4. 确认框位置正确
