# 画框步骤添加 JSON 导入按钮 Spec

## Why
当前画框步骤仅支持用户手动绘制矩形框来标记OCR识别区域，对于已有MinerU layout.json文件的场景，用户需要手动逐页逐框绘制，效率极低。需要提供JSON导入功能，自动将layout.json中type为"text"的文本框批量录入软件，大幅提升工作效率。

## What Changes
- 在DrawBoxWindow工具栏中添加"导入JSON"按钮
- 新增JSON文件解析功能，读取MinerU layout.json格式
- 实现PDF点坐标到渲染图像像素坐标的转换
- 仅导入"type": "text"的para_blocks，忽略image/table/code等其他类型
- 导入的框适当扩展（2像素）确保框住文字（参考P2X项目的EXPAND_BBOX_PIXELS）
- 导入的框追加到已有框中，不覆盖用户已手动绘制的框

## Impact
- Affected specs: add-draw-box-step（画框步骤核心功能扩展）
- Affected code:
  - `ui/draw_box_window.py`：添加导入JSON按钮及解析逻辑
  - `pdf_processor/pdf_loader.py`：可能需要添加获取PDF页面原始尺寸的方法

## ADDED Requirements

### Requirement: JSON导入按钮
系统 SHALL 在画框步骤窗口的工具栏中提供"导入JSON"按钮，位于"选择PDF"按钮之后。

#### Scenario: 用户点击导入JSON按钮
- **WHEN** 用户点击"导入JSON"按钮
- **THEN** 系统弹出文件选择对话框，过滤器为"JSON文件 (*.json)"

#### Scenario: 未加载PDF时点击导入JSON
- **WHEN** 用户未加载PDF文件时点击"导入JSON"按钮
- **THEN** 系统弹出警告对话框提示"请先选择PDF文件"

### Requirement: MinerU layout.json解析
系统 SHALL 能够解析MinerU输出的layout.json格式，提取其中type为"text"的para_blocks。

#### Scenario: 成功解析JSON文件
- **WHEN** 用户选择一个有效的layout.json文件
- **THEN** 系统解析JSON，遍历pdf_info数组，对每一页提取type为"text"的para_blocks，获取其bbox坐标

#### Scenario: JSON文件格式无效
- **WHEN** 用户选择一个非layout.json格式的文件
- **THEN** 系统弹出错误提示，不崩溃

#### Scenario: JSON页数与PDF页数不匹配
- **WHEN** JSON中的页数少于PDF页数
- **THEN** 系统仅导入有对应数据的页面，多余页面无框

### Requirement: 坐标转换
系统 SHALL 将JSON中的PDF点坐标正确转换为渲染图像的像素坐标。

#### Scenario: 坐标转换正确
- **WHEN** JSON中某text block的bbox为[x0, y0, x1, y1]（PDF点坐标）
- **THEN** 转换后的图像像素坐标为[x0*scale_x, y0*scale_y, x1*scale_x, y1*scale_y]，其中scale_x = rendered_width / pdf_width，scale_y = rendered_height / pdf_height

#### Scenario: 框扩展确保框住文字
- **WHEN** 导入文本框的bbox转换完成后
- **THEN** 框的四边各向外扩展2像素（参考P2X项目的EXPAND_BBOX_PIXELS），确保框住文字

### Requirement: 框数据合并
系统 SHALL 将导入的框追加到已有框数据中，不覆盖用户已手动绘制的框。

#### Scenario: 导入框与已有框合并
- **WHEN** 用户已手动绘制了一些框，然后导入JSON
- **THEN** 导入的框追加到对应页面的框列表末尾，已有框保持不变

### Requirement: 导入后刷新显示
系统 SHALL 在JSON导入完成后自动刷新当前页面的显示。

#### Scenario: 导入完成后页面刷新
- **WHEN** JSON导入完成
- **THEN** 当前页面重新渲染，显示所有框（包括已有框和新导入的框），并弹出提示显示导入了多少个框

## MODIFIED Requirements

无修改的需求。

## REMOVED Requirements

无移除的需求。
