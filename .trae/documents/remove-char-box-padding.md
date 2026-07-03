# 去掉软件2字符切片框的向外扩展像素

## 问题分析

当前软件2在读取chars.json并裁剪字符切片图像时，会对每个字符框向外扩展6像素，导致切片图像比chars.json中规范的框更大。用户要求去掉这个扩展逻辑，按照chars.json中规范的框大小精确裁剪。

## 当前状态

唯一需要修改的位置在 `软件2/ocr_engine/rapidocr_engine.py` 的 `parse_and_group` 方法中，第229-233行：

```python
padding = 6
crop_x1 = max(0, int(round(bbox_flat[0])) - padding)
crop_y1 = max(0, int(round(bbox_flat[1])) - padding)
crop_x2 = min(img_width, int(round(bbox_flat[2])) + padding)
crop_y2 = min(img_height, int(round(bbox_flat[3])) + padding)
```

该方法用于：
- 从chars.json读取字符数据
- 展平4角点box为 `[x1,y1,x2,y2]`
- 从页面图像中裁剪字符区域
- 生成 CharSlice 对象，用于纵校阶段展示
- 被 `DataLoadWorker.run` 调用

`parse_and_group` 读取的 chars 数据来自 `load_results_from_file`，默认读取 `chars.json`。软件2目前没有读取 `newchar.json` 的逻辑。

## 修改方案

### 修改文件：`软件2/ocr_engine/rapidocr_engine.py`

#### 1. `parse_and_group` 方法中去掉padding

将第229-233行：
```python
padding = 6
crop_x1 = max(0, int(round(bbox_flat[0])) - padding)
crop_y1 = max(0, int(round(bbox_flat[1])) - padding)
crop_x2 = min(img_width, int(round(bbox_flat[2])) + padding)
crop_y2 = min(img_height, int(round(bbox_flat[3])) + padding)
```

改为：
```python
crop_x1 = max(0, int(round(bbox_flat[0])))
crop_y1 = max(0, int(round(bbox_flat[1])))
crop_x2 = min(img_width, int(round(bbox_flat[2])))
crop_y2 = min(img_height, int(round(bbox_flat[3])))
```

#### 2. 更新方法文档字符串

将第189行的 docstring 中的 "带 6 像素边距" 改为 "不带额外边距" 或直接删除该描述。

## 验证步骤

1. 语法检查：编译 `rapidocr_engine.py` 通过
2. 运行软件2：启动无报错
3. 导入json/pdf数据后，检查纵校界面中的字符切片是否与框大小一致（不再向外扩展6像素）
4. 检查横校/精修界面是否正常
