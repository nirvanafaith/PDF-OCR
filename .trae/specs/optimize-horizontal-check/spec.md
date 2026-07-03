# 横校界面优化 Spec

## Why
当前横校界面存在多项体验问题：字符列表显示冗余信息、切片展示尺寸不统一、每行切片数过少、悬停高亮不明显、修改字符后JSON数据未同步更新。需要全面优化以提升校对效率。

## What Changes
- 左侧字符列表条目仅显示字符本身，移除"字'X'：共N处"格式
- 切片展示统一压缩至相同宽高（强制缩放至固定宽高，非KeepAspectRatio），每行8个
- 鼠标悬停切片时蓝色高亮（背景色变化）
- 右键修改字符后同步更新 ocr_results JSON 数据中对应字符的 text 字段
- 移除切片下方的页码坐标信息标签
- **修复 main.py 未传入 ocr_results 给 HorizontalCheckWindow 的 BUG**
- **修复 main.py 未接收更新后 ocr_results 的 BUG**

## Impact
- Affected code: ui/horizontal_check_window.py, main.py

## ADDED Requirements

### Requirement: 字符列表简洁显示
左侧字符列表每个条目仅显示字符本身，不附加数量等提示信息。

#### Scenario: 列表显示
- **WHEN** 横校界面加载字符列表
- **THEN** 每个条目仅显示该字符文本本身，如"画"、"十"、"高"

### Requirement: 切片统一尺寸展示
所有切片图片统一压缩至相同的宽度和高度进行展示，每行展示8个切片。图片强制缩放至固定宽高（使用KeepAspectRatioByExpanding或直接缩放），确保每个切片展示区域大小完全一致。

#### Scenario: 统一尺寸
- **WHEN** 切片图片展示在网格中
- **THEN** 每张图片被强制缩放至相同的固定宽高（如80x80），所有切片卡片视觉大小完全一致

#### Scenario: 每行8个
- **WHEN** 切片网格布局
- **THEN** 每行展示8个切片，切片间有合适间距

### Requirement: 悬停蓝色高亮
鼠标悬停在切片上时，切片卡片背景变为蓝色高亮。

#### Scenario: 悬停高亮
- **WHEN** 鼠标悬停在某个切片卡片上
- **THEN** 该卡片背景色变为浅蓝色高亮

### Requirement: 右键修改字符同步更新JSON
右键修改字符后，不仅移动切片到新字符集合，还要同步更新 ocr_results 中对应字符的 text 字段。

#### Scenario: 修改字符同步JSON
- **WHEN** 用户右键切片并修改字符为新文字
- **THEN** 系统将该切片从当前字符集合移至新字符集合，同时更新 ocr_results[doc_key][page_num]["text_lines"][line_idx]["chars"][char_idx]["text"] 为新文字

### Requirement: main.py 正确传递和接收 ocr_results
main.py 必须将 ocr_results 传入 HorizontalCheckWindow，并在横校完成后接收更新后的 ocr_results。

#### Scenario: 传入 ocr_results
- **WHEN** 创建 HorizontalCheckWindow 实例
- **THEN** 将 self.ocr_results 作为第三个参数传入

#### Scenario: 接收更新后的 ocr_results
- **WHEN** HorizontalCheckWindow 发出 finished_signal(char_slices, ocr_results)
- **THEN** main.py 的 _on_horizontal_check_finished 同时接收 updated_char_slices 和 updated_ocr_results，并更新 self.ocr_results

## MODIFIED Requirements

### Requirement: 切片卡片展示
切片卡片仅展示字符图片，移除下方的页码坐标信息标签。图片强制缩放至固定宽高，确保视觉统一。

## REMOVED Requirements
无
