# Tasks

- [x] Task 1: Win7 兼容性改造(依赖锁版 + PyQt6 → PyQt5 迁移)
  - [ ] SubTask 1.1: 更新 `requirements.txt`,锁定 Win7 + Python 3.8 兼容版本,移除未使用的 `paddlepaddle-gpu`
    - 锁版目标: `PyQt5==5.15.10`、`PyMuPDF==1.23.8`、`Pillow==9.5.0`、`numpy==1.24.4`、`reportlab==3.6.13`
    - 保留: `RapidOCR` 相关依赖(若实际代码用到 rapidocr,需查阅其 Win7 + Python 3.8 兼容版本,否则不加入 requirements)
  - [ ] SubTask 1.2: 全量 PyQt6 → PyQt5 枚举与 API 短形式迁移,涉及文件:
    - `main.py`、`ui/import_window.py`、`ui/vertical_check_window.py`、`ui/horizontal_check_window.py`、`ui/refine_window.py`、`ui/styles.py`、`ui/zoom_utils.py`、`pdf_processor/pdf_output.py`
    - 迁移规则示例: `Qt.AlignmentFlag.AlignCenter` → `Qt.AlignCenter`;`Qt.MouseButton.LeftButton` → `Qt.LeftButton`;`Qt.ItemDataRole.UserRole` → `Qt.UserRole`;`QEvent.Type.X` → `QEvent.X`;`QGraphicsView.ViewportAnchor.AnchorViewCenter` → `QGraphicsView.AnchorViewCenter`;`Qt.ScrollBarPolicy.ScrollBarAlwaysOff` → `Qt.ScrollBarAlwaysOff`;`Qt.AspectRatioMode.KeepAspectRatio` → `Qt.KeepAspectRatio`;`Qt.TransformationMode.SmoothTransformation` → `Qt.SmoothTransformation`;`Qt.WidgetAttribute.WA_StyledBackground` → `Qt.WA_StyledBackground`;`Qt.FocusPolicy.StrongFocus` → `Qt.StrongFocus`;`Qt.BrushStyle.NoBrush` → `Qt.NoBrush`;`Qt.CursorShape.ClosedHandCursor` → `Qt.ClosedHandCursor`;`Qt.KeyboardModifier.ControlModifier` → `Qt.ControlModifier`;`Qt.KeyboardModifier.ShiftModifier` → `Qt.ShiftModifier`;`Qt.KeyboardModifier.AltModifier` → `Qt.AltModifier`;`QDialog.DialogCode.Accepted` → `QDialog.Accepted`;`QFileDialog.Option.ReadOnly` → `QFileDialog.ReadOnly`;`QGraphicsView.DragMode.NoDrag` → `QGraphicsView.NoDrag`;`QGraphicsView.ViewportUpdateMode.FullViewportUpdate` → `QGraphicsView.FullViewportUpdate`;`QSizePolicy.Policy.Expanding` → `QSizePolicy.Expanding`;`QSizePolicy.Policy.Fixed` → `QSizePolicy.Fixed`;`QSizePolicy.Policy.Preferred` → `QSizePolicy.Preferred`;`Qt.Key.Key_Space` → `Qt.Key_Space`(Qt.Key_* 在 PyQt5 中已存在,可保留)
  - [ ] SubTask 1.3: 验证 PyQt5 import 路径正确(`from PyQt5.QtWidgets import ...` 等),并删除 `__pycache__` 中旧 .pyc

- [x] Task 2: 纵校原图预览与切片展示四项核心改造
  - [ ] SubTask 2.1: `PreviewGraphicsView` 重构为无边界拖拽
    - `__init__` 中保留 `setDragMode(NoDrag)`、`setTransformationAnchor(AnchorViewCenter)`、隐藏滚动条、`AlignLeft|AlignTop` 对齐
    - 新增 `_pixmap_item` 与 `_rect_item` 实例属性(初始 None)
    - `mousePressEvent`: 记录 `_pan_start_pos`、`_pan_start_pixmap_pos`(pixmap_item.pos())、设置 ClosedHandCursor
    - `mouseMoveEvent`: 计算 `delta = event.pos() - _pan_start_pos`,将 viewport delta 转 scene delta = delta / transform().m11(),调用 `self._pixmap_item.moveBy(dx_scene, dy_scene)`,rect_item 作为子项跟随
    - `mouseReleaseEvent`: 取消 panning 状态
    - `wheelEvent`: 保留 Ctrl+滚轮缩放(修改 `self.scale(factor, factor)`,以 AnchorViewCenter 为锚点)
    - `fit_to_width`: 保留 resetTransform + scale(viewport_w / scene_rect.width) 行为(注意 scene_rect 不再是 pixmap 大小)
    - 新增 `set_scene_pixmap(pixmap, rect_in_pixmap_coords)`: 由外部调用,创建 pixmap_item + rect_item(rect_item.setParentItem(pixmap_item)),rect 坐标为相对 pixmap 本地坐标
    - `center_on_rect(rect_in_scene)`: 总是 resetTransform;按 min(viewport_w/(rect_w*1.4), viewport_h/(rect_h*1.4)) 计算 target_scale,clamp 到 [_min_zoom, _max_zoom];`setTransform(QTransform().scale(target_scale, target_scale))`;最后 `centerOn(rect.center())` 严格居中
    - 在 `VerticalCheckWindow._show_line_preview` 中:创建 pixmap_item 后调用 `preview_view.set_scene_pixmap(...)`,然后 `center_on_rect(rect_item.sceneBoundingRect())`
    - 在 `PreviewGraphicsView.__init__` 中设置 `sceneRect` 为大范围常量(如 `QRectF(-50000, -50000, 100000, 100000)`),解除 `centerOn` 边界
  - [ ] SubTask 2.2: 切片展示左上起排固定间隙
    - `_init_ui` 中 `grid_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)`(原为 Expanding),使容器不撑满宽度
    - `grid_layout.setContentsMargins(0, 0, 0, 0)`、`grid_layout.setSpacing(self._K_SLICE_SPACING)`(已存在,确认)
    - `grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)` 防止均匀拉伸
    - `scroll_vlayout.setAlignment(Qt.AlignTop | Qt.AlignLeft)`(已存在,确认)
    - `_recalc_layout` 中保留列数计算逻辑,确保行优先排列(_render_current_page 中 `row = page_idx // cols; col = page_idx % cols` 已正确,确认)
  - [ ] SubTask 2.3: 切片图像完整放缩
    - `SliceItemWidget.__init__` 中:`pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)`(原为 `KeepAspectRatioByExpanding` + `FastTransformation`)
    - 验证 `image_label.setFixedSize(80, 80)` + `setAlignment(Qt.AlignCenter)` 使图像居中显示
    - 可选优化: 改为 `self.contentsRect()` 动态计算可用尺寸,但当前 80×80 固定可接受,保持简单
  - [ ] SubTask 2.4: 红框严格居中
    - `center_on_rect` 移除 `if target_scale > 0 and abs(target_scale - current_scale) > 0.01` 阈值判断,改为总是 `setTransform`
    - `_show_line_preview` 最后调用顺序: `set_scene_pixmap` → `center_on_rect(rect_item.sceneBoundingRect())`(不再调用 `fit_to_width`,因 center_on_rect 已重置 transform)
    - 确保 `rect_item` 是 `pixmap_item` 的子项,其 `sceneBoundingRect()` 会反映 pixmap_item 的 pos 偏移与 scale

- [x] Task 3: 审校与启动脚本
  - [x] SubTask 3.1: 通读所有修改文件,使用 context7 MCP 查询 PyQt5 文档验证 API 使用正确(重点 `QGraphicsPixmapItem`、`QGraphicsRectItem.setParentItem`、`QTransform`、`QGraphicsView.centerOn` 行为)
  - [x] SubTask 3.2: 检查 `_show_line_preview` 中红框 rect 坐标转换逻辑(原 `rect_x = cx1 - crop_x1` 等)在 pixmap_item.setPos(0,0) 初始情况下仍正确;拖动后 rect_item 作为子项跟随,sceneBoundingRect 自动反映新位置
  - [x] SubTask 3.3: 检查 `center_on_rect` 中 `rect.center()` 返回 QPointF 时的 `centerOn` 调用签名正确
  - [x] SubTask 3.4: 检查 PyQt5 中 `QGraphicsScene.setSceneRect(QRectF)` 接受大范围参数无副作用
  - [x] SubTask 3.5: 创建 `D:\hx\software2\run.bat`,逻辑:
    ```
    @echo off
    chcp 65001 > nul
    cd /d "%~dp0"
    set PYTHONIOENCODING=utf-8
    set PYTHONUTF8=1
    if exist "venv\Scripts\activate.bat" (
        call "venv\Scripts\activate.bat"
    )
    python main.py
    if errorlevel 1 pause
    ```
  - [ ] SubTask 3.6: 最终全量自检 - 确认所有 `from PyQt6` 已替换为 `from PyQt5`;确认 `PyQt6.QtCore`、`PyQt6.QtGui`、`PyQt6.QtWidgets` 全部迁移;确认枚举短形式无遗漏;确认 run.bat 语法正确

# Task Dependencies
- Task 2 依赖 Task 1 完成(PyQt5 枚举短形式必须先迁移完成,否则 Task 2 中新代码会混入 PyQt6 长形式枚举)
- Task 3 依赖 Task 1 与 Task 2 完成
- SubTask 2.1、2.2、2.3、2.4 之间相互独立,可在 vertical_check_window.py 中一次性修改
