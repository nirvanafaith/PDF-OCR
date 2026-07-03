# Checklist

## Task 1: 字体排版算法
- [x] `_calculate_line_font_size` 方法根据 width/height 判断横排/竖排
- [x] 候选字号 = min(width, height) × zoom，最小 4px
- [x] 横排时检查总宽度是否超框，超框则按比例缩小字号
- [x] 竖排时检查总高度是否超框，超框则按比例缩小字号
- [x] `_distribute_chars_by_orientation` 横排时字符从左到右等宽排列、垂直居中
- [x] `_distribute_chars_by_orientation` 竖排时字符从上到下等高排列、水平居中
- [x] `_render_page` 中有 chars 数据时使用新算法，无 chars 时回退到原逻辑
- [x] ignored 行仍显示灰色文字
- [x] QGraphicsTextItem 保留 ItemIsSelectable、AcceptHoverEvents、setData(0/1) 设置

## Task 2: 不影响现有功能
- [x] `_make_slice_pixmap` 方法未被修改
- [x] eventFilter 中悬停预览逻辑（显示切片图像）未被修改
- [x] eventFilter 中蓝框标记逻辑（_hover_rect_item）未被修改
- [x] 字体算法仅影响 QGraphicsTextItem 的 font 和 pos

## Task 3: 重新定位行框
- [x] 右键行文本时菜单包含"重新定位行框"选项
- [x] 点击后显示"画框模式"提示标签
- [x] pdf_view 光标变为 CrossCursor
- [x] 画框模式下按下左键创建 QRubberBand
- [x] 拖拽时 QRubberBand 跟随鼠标更新
- [x] 松开鼠标后弹出确认对话框
- [x] 确认后行 bbox 更新为新框坐标（页面图像像素坐标）
- [x] 行内字符按新 bbox 和方向重新分布
- [x] 行图像重新裁剪
- [x] 页面重新渲染显示新排版
- [x] 取消时不修改任何数据
- [x] ESC 键退出画框模式

## Task 4: 新增文段
- [x] 右键空白处时菜单显示"新增文段"选项
- [x] 点击后弹出文本输入对话框
- [x] 空文本或取消时不进入画框模式
- [x] 输入文本后进入画框模式
- [x] 画框确认后创建新 LineSlice（page_num=当前页，bbox=新框，text=输入文本）
- [x] 新行的 chars 按方向分布
- [x] 新行的 image 按新框裁剪
- [x] 新行追加到 page_lines[当前页]
- [x] 页面重新渲染显示新行

## 通用验证
- [x] `python -m py_compile ui\horizontal_check_window.py` 通过
- [x] Grep 确认 `_calculate_line_font_size`、`_distribute_chars_by_orientation`、`_enter_draw_box_mode`、`_exit_draw_box_mode`、`_apply_drawn_box`、`_add_new_text_segment`、`_relocate_line_frame` 方法均存在
- [x] Grep 确认 `_make_slice_pixmap` 内容未被修改
- [x] Grep 确认 `_hover_rect_item` 蓝框逻辑未被修改
- [x] 画框坐标转换正确：视口坐标 → 场景坐标 → 页面像素坐标（÷ zoom）
- [x] 画框最小尺寸检查（宽高 ≥ 10px）
- [x] context7 确认 QRubberBand、QFontMetrics.horizontalAdvance、mapToScene API 使用正确
