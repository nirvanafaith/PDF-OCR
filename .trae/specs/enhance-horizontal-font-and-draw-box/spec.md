# 横校环节字体算法与画框交互增强 Spec

## Why
当前横校界面左侧白纸上的文字按每个字符的独立 bbox 计算字体大小，导致同一行内字符大小不一、视觉不统一。此外，用户无法在横校阶段修正 OCR 行框位置或手动新增文本段，必须回到更早阶段重新处理，效率低下。

## What Changes
- 重写字体排版算法：根据行 bbox 的宽高比判断横排/竖排，按最短边计算最大可容纳字号，整行使用统一字号排版
- 扩展右键菜单：行文本上右键新增"重新定位行框"选项，进入画框模式在右侧 PDF 上绘制新框，确认后重新排版该行
- 扩展右键菜单：空白处右键新增"新增文段"选项，输入文本后在右侧 PDF 上画框，确认后创建新行并排版
- 画框完成后同步更新 LineSlice 数据（bbox、chars、image）
- 保持原有切片悬停预览和右侧蓝色框标记功能不变

## Impact
- Affected specs: optimize-horizontal-check（字体渲染从逐字计算改为整行统一计算）
- Affected code: `d:\hx\software2\ui\horizontal_check_window.py`
  - `_render_page`（字体算法重写）
  - `_on_context_menu`（扩展为支持文本项和空白处两种菜单）
  - `eventFilter`（新增画框模式的鼠标交互）
  - `__init__`（新增画框状态变量）
  - 新增 `_calculate_line_font_size`、`_distribute_chars_by_orientation`、`_enter_draw_box_mode`、`_exit_draw_box_mode`、`_apply_drawn_box`、`_add_new_text_segment` 方法

## ADDED Requirements

### Requirement: 基于行框的统一字体排版
系统 SHALL 根据行 bbox 的宽高比判断横排或竖排方向，按最短边计算整行最大可容纳字号，所有字符使用该统一字号在行框内排版。

#### Scenario: 横排文字排版
- **WHEN** 行 bbox 宽度 >= 高度（横排）
- **THEN** 字号初始候选值为高度 × 缩放率，若所有字符总宽度超过行框宽度则按比例缩小字号，字符从左到右排列、垂直居中

#### Scenario: 竖排文字排版
- **WHEN** 行 bbox 高度 > 宽度（竖排）
- **THEN** 字号初始候选值为宽度 × 缩放率，若所有字符总高度超过行框高度则按比例缩小字号，字符从上到下排列、水平居中

#### Scenario: 字号下限保护
- **WHEN** 计算出的字号小于 4 像素
- **THEN** 使用 4 像素作为最小字号

#### Scenario: 无字符数据回退
- **WHEN** 行切片的 chars 列表为空
- **THEN** 回退到按行文本整体渲染（保持现有逻辑），字号基于行 bbox 高度

### Requirement: 重新定位行框
系统 SHALL 支持右键行文本时选择"重新定位行框"，进入画框模式在右侧 PDF 视图上绘制新框，确认后按新框重新排版该行。

#### Scenario: 进入画框模式
- **WHEN** 用户右键行文本并选择"重新定位行框"
- **THEN** 屏幕上方显示"画框模式"提示，右侧 PDF 视图光标变为十字形，等待用户绘制矩形

#### Scenario: 绘制新框
- **WHEN** 画框模式下用户在右侧 PDF 上按下左键并拖拽
- **THEN** 实时显示半透明矩形框跟随鼠标，松开鼠标后弹出确认对话框

#### Scenario: 确认重新定位
- **WHEN** 用户在确认对话框中点击"确认"
- **THEN** 行 bbox 更新为绘制的新框坐标（页面图像像素坐标），行内字符按新 bbox 和方向重新分布，行图像重新裁剪，页面重新渲染

#### Scenario: 取消重新定位
- **WHEN** 用户在确认对话框中点击"取消"或按 ESC
- **THEN** 退出画框模式，不修改任何数据

### Requirement: 新增文段
系统 SHALL 支持右键空白处时选择"新增文段"，输入文本后在右侧 PDF 上画框，确认后创建新的行切片并排版显示。

#### Scenario: 输入新文本
- **WHEN** 用户右键空白处并选择"新增文段"
- **THEN** 弹出文本输入对话框，用户输入文本内容

#### Scenario: 空文本保护
- **WHEN** 用户在文本输入对话框中输入空内容或点击取消
- **THEN** 不进入画框模式，不创建新行

#### Scenario: 画框并创建新行
- **WHEN** 用户输入文本后进入画框模式，在右侧 PDF 上绘制框并确认
- **THEN** 创建新 LineSlice（page_num=当前页，bbox=新框坐标，text=输入文本，chars=按方向分布），添加到 page_lines[当前页]，页面重新渲染

## MODIFIED Requirements

### Requirement: 右键上下文菜单
右键上下文菜单 SHALL 根据点击位置区分两种菜单：
- 点击行文本图元时：显示"修改文字"、"忽略/删除"、"重新定位行框"
- 点击空白处时：显示"新增文段"

### Requirement: 字体渲染算法
`_render_page` 中的字体计算 SHALL 从逐字符独立计算改为整行统一计算。新算法根据行 bbox 判断方向、计算最大字号、统一排版所有字符。原有逐字符 bbox 定位逻辑被替换。

## Assumptions & Decisions

1. **方向判断阈值**: width >= height 为横排，height > width 为竖排。等于时默认横排（更常见）
2. **字号计算策略**: 候选字号 = min(width, height) × zoom。横排检查总宽度是否超框，竖排检查总高度是否超框。超框时按比例缩小（actual_size = candidate × target_extent / actual_extent），最小 4px
3. **字符分布**: 横排时每个字符等宽分配（char_width = line_width / num_chars），垂直居中；竖排时每个字符等高分配（char_height = line_height / num_chars），水平居中
4. **画框坐标转换**: 右侧 PDF 视口坐标 → 场景坐标（mapToScene）→ 页面图像像素坐标（除以 zoom_level），最后 clamp 到 [0, 0, img_w, img_h]
5. **画框视觉反馈**: 使用 QRubberBand(QRubberBand.Rectangle) 在 pdf_view 上显示绘制中的矩形
6. **画框模式光标**: pdf_view 设置 Qt.CrossCursor
7. **ESC 退出画框**: keyPressEvent 中检测 ESC，若在画框模式则退出
8. **不影响悬停预览**: _make_slice_pixmap、eventFilter 中的悬停逻辑（显示切片图像 + 蓝框）保持不变，仅使用行 bbox，与字体算法无关
9. **不传递 ocr_results**: HorizontalCheckWindow 不接收 ocr_results。"json 更新"指 LineSlice 数据结构（bbox、chars、text）的更新，这些数据流向精修阶段
10. **新行 line_id**: 不需要 line_id（LineSlice 无此字段），新行直接追加到 page_lines[page] 列表末尾
11. **行图像更新**: 重新定位行框后，从 page_images[page_num] 按新 bbox 重新 crop 生成 LineSlice.image
12. **画框最小尺寸**: 绘制的框宽或高 < 10 像素时视为无效，提示用户重新绘制
