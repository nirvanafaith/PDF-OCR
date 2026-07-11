import traceback

from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolBar,
    QDialog,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QRubberBand,
    QMessageBox,
    QInputDialog,
    QUndoStack,
    QShortcut,
)
from PyQt5.QtCore import Qt, pyqtSignal, QEvent, QRectF, QPointF, QTimer, QRect
from PyQt5.QtGui import (
    QPixmap,
    QImage,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QWheelEvent,
    QPainter,
    QPen,
    QBrush,
    QKeySequence,
)

from models.data_models import LineSlice, CorrectedLine
from ui.styles import get_stylesheet
from ui.zoom_utils import calculate_wheel_zoom, ZOOM_MIN, ZOOM_MAX
from undo_commands import (
    ModifyLineTextCommand,
    ToggleIgnoreCommand,
    RelocateLineFrameCommand,
)

# 模块级 native 探测结果缓存：None 表示尚未探测，非 None 表示已缓存（含失败结果）。
# 进程生命周期内只执行一次文件系统探测，后续调用直接返回缓存值。
_NATIVE_CACHE = None


def _try_native():
    """尝试加载本地 native 加速模块。

    成功返回 (pixmap_bytes_to_qpixmap_buffer, optimize_char_boxes,
             batch_crop_qimage, pil_to_qimage_buffer)；
    失败返回 (None, None, None, None)。所有 import 在函数内部完成，不影响模块加载。
    结果缓存到模块级 _NATIVE_CACHE，进程生命周期内仅探测一次。
    """
    global _NATIVE_CACHE
    if _NATIVE_CACHE is not None:
        return _NATIVE_CACHE
    try:
        from native import has_native as _has_native
        if not _has_native():
            _NATIVE_CACHE = (None, None, None, None)
            return _NATIVE_CACHE
        from native import (
            pixmap_bytes_to_qpixmap_buffer,
            optimize_char_boxes,
            batch_crop_qimage,
            pil_to_qimage_buffer,
        )
        _NATIVE_CACHE = (pixmap_bytes_to_qpixmap_buffer, optimize_char_boxes,
                         batch_crop_qimage, pil_to_qimage_buffer)
    except Exception:
        _NATIVE_CACHE = (None, None, None, None)
    return _NATIVE_CACHE


class HorizontalCheckWindow(QWidget):
    """横校阶段主窗口，用于逐页展示行切片文本与原图叠加视图，支持文字修改、行忽略及缩放浏览。

    信号:
        finished_signal(list): 横校完成时发射，携带 CorrectedLine 列表作为参数，
            由 _on_finish 方法在用户确认完成后发射。

    依赖:
        - PyQt5: QWidget, QGraphicsView, QGraphicsScene, QGraphicsTextItem,
          QGraphicsPixmapItem, QLabel, QPushButton, QSpinBox, QToolBar,
          QDialog, QLineEdit, QMenu, QSizePolicy, Qt, pyqtSignal, QRectF,
          QPointF, QTimer, QPixmap, QImage, QFont, QMouseEvent, QWheelEvent,
          QPainter
        - models.data_models.LineSlice, CorrectedLine: 行数据模型
        - ui.styles.get_stylesheet: 全局样式表
    """

    finished_signal = pyqtSignal(list)
    back_signal = pyqtSignal()
    error_occurred = pyqtSignal(str)
    # Ctrl+S 保存时发射，携带本阶段断点字典，由 MainWindow 合并后交 SessionManager.save
    save_requested = pyqtSignal(dict)

    def __init__(self, page_lines: dict, page_images: list, parent=None):
        """初始化横校窗口。

        被 MainWindow._on_vertical_finished 中创建实例调用。

        参数:
            page_lines (dict): 键为页码(int)，值为该页的 LineSlice 列表，
                包含每行的文本、边界框和图像信息。
            page_images (list): PIL Image 对象列表，索引对应页码，
                用于在场景中叠加显示原始页面图像。
            parent: 父组件，默认为 None。

        依赖:
            - models.data_models.LineSlice: page_lines 中存储的行数据类型
        """
        super().__init__(parent)
        self.page_lines = page_lines
        self.page_images = page_images
        self.zoom_level = 1.0
        self.current_page = 0
        self.total_pages = len(page_images)
        self.modifications = []
        self._first_render = True
        # 撤销/重做栈：所有行文本修改、忽略切换、行框重定位均通过 push 命令进入栈
        self._undo_stack = QUndoStack(self)
        self._hover_pixmap_item = None
        self._hover_rect_item = None
        self._slice_cache_id = None
        self._slice_cache_pixmap = None
        self._pixmap_cache = {}
        self._pixmap_cache_max = 20
        self._draw_box_mode = False
        self._draw_box_target = None  # LineSlice 或 None
        self._draw_box_text = None    # 新文本或 None
        self._draw_rubber_band = None
        self._draw_start_pos = None
        # 中键平移状态
        self._mid_panning = False
        self._mid_start_pos = None
        self._mid_start_pixmap_pos = None
        self._mid_panning_view = None
        self._mid_prev_cursor = None
        # 页码输入防抖计时器
        self._page_debounce = QTimer()
        self._page_debounce.setSingleShot(True)
        self._page_debounce.timeout.connect(self._do_render_page)
        self._init_ui()

    def _init_ui(self):
        """初始化用户界面，构建工具栏、图形视图和底部按钮布局。

        被 __init__ 调用。创建并配置以下 UI 组件：
        - 工具栏：包含翻页控件、手型工具、缩放控件
        - 图形视图：用于展示页面图像与行切片文本叠加效果
        - 底部布局：包含"完成横校"按钮

        依赖:
            - ui.styles.get_stylesheet: 获取全局样式表
            - PyQt5.QToolBar: 工具栏组件
            - PyQt5.QGraphicsView, QGraphicsScene: 图形视图与场景
        """
        self.setStyleSheet(get_stylesheet())
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 6px; padding: 4px; }")

        self.back_btn = QPushButton("← 返回")
        self.back_btn.clicked.connect(self._on_back)
        toolbar.addWidget(self.back_btn)

        toolbar.addSeparator()

        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self._on_prev_page)
        toolbar.addWidget(self.prev_btn)

        self.page_label = QLabel(f"第1/{self.total_pages}页")
        toolbar.addWidget(self.page_label)

        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, self.total_pages)
        self.page_spin.setValue(1)
        self.page_spin.valueChanged.connect(self._on_page_spin_changed)
        toolbar.addWidget(self.page_spin)

        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self._on_next_page)
        toolbar.addWidget(self.next_btn)

        toolbar.addSeparator()

        self.hand_btn = QPushButton("手型工具")
        self.hand_btn.setCheckable(True)
        self.hand_btn.clicked.connect(self._on_hand_tool_toggle)
        toolbar.addWidget(self.hand_btn)

        self.zoom_in_btn = QPushButton("放大")
        self.zoom_in_btn.clicked.connect(self._on_zoom_in)
        toolbar.addWidget(self.zoom_in_btn)

        self.zoom_input = QLineEdit("100%")
        self.zoom_input.setFixedWidth(55)
        self.zoom_input.setAlignment(Qt.AlignCenter)
        self.zoom_input.returnPressed.connect(self._on_zoom_input)
        toolbar.addWidget(self.zoom_input)

        self.zoom_out_btn = QPushButton("缩小")
        self.zoom_out_btn.clicked.connect(self._on_zoom_out)
        toolbar.addWidget(self.zoom_out_btn)

        self.fit_width_btn = QPushButton("适合宽度")
        self.fit_width_btn.clicked.connect(self._on_fit_width)
        toolbar.addWidget(self.fit_width_btn)

        self.fit_height_btn = QPushButton("适合高度")
        self.fit_height_btn.clicked.connect(self._on_fit_height)
        toolbar.addWidget(self.fit_height_btn)

        main_layout.addWidget(toolbar)

        self.draw_mode_hint = QLabel("画框模式：请在右侧PDF上绘制区域（按ESC取消）")
        self.draw_mode_hint.setStyleSheet(
            "QLabel { background-color: #fff3cd; color: #856404; "
            "padding: 6px; border-bottom: 1px solid #ffeeba; }"
        )
        self.draw_mode_hint.setAlignment(Qt.AlignCenter)
        self.draw_mode_hint.hide()
        main_layout.addWidget(self.draw_mode_hint)

        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(Qt.white)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view.setViewportUpdateMode(
            QGraphicsView.SmartViewportUpdate
        )
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        self.view.setMouseTracking(True)
        self.view.viewport().installEventFilter(self)

        # 右侧原PDF展示视图
        self.pdf_scene = QGraphicsScene()
        self.pdf_scene.setBackgroundBrush(Qt.white)

        self.pdf_view = QGraphicsView(self.pdf_scene)
        self.pdf_view.setRenderHint(QPainter.Antialiasing)
        self.pdf_view.setDragMode(QGraphicsView.NoDrag)
        self.pdf_view.setViewportUpdateMode(
            QGraphicsView.SmartViewportUpdate
        )
        self.pdf_view.viewport().installEventFilter(self)

        # 左右视图并排布局
        views_layout = QHBoxLayout()
        views_layout.setSpacing(2)
        views_layout.addWidget(self.view, 1)
        views_layout.addWidget(self.pdf_view, 1)
        main_layout.addLayout(views_layout, 1)

        # 滚动条联动
        self.view.verticalScrollBar().valueChanged.connect(self._on_left_v_scroll)
        self.view.horizontalScrollBar().valueChanged.connect(self._on_left_h_scroll)
        self.pdf_view.verticalScrollBar().valueChanged.connect(self._on_right_v_scroll)
        self.pdf_view.horizontalScrollBar().valueChanged.connect(self._on_right_h_scroll)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        self.finish_btn = QPushButton("完成横校")
        self.finish_btn.clicked.connect(self._on_finish)
        bottom_layout.addWidget(self.finish_btn)
        main_layout.addLayout(bottom_layout)

        # 注册全局快捷键（窗口级，任意子控件焦点均生效）
        self._register_shortcuts()

        self._render_page()

    def _register_shortcuts(self):
        """注册撤销/重做/保存与翻页/缩放快捷键。

        - Ctrl+Z / Ctrl+Y：撤销 / 重做
        - Ctrl+S：保存工程（发射 save_requested 信号）
        - PgUp / PgDn：上一页 / 下一页
        - Home / End：首页 / 末页
        - Ctrl+Plus / Ctrl+Minus / Ctrl+0：放大 / 缩小 / 重置缩放
        """
        # 撤销/重做
        QShortcut(QKeySequence.Undo, self, self._undo_stack.undo)
        QShortcut(QKeySequence.Redo, self, self._undo_stack.redo)
        # 保存
        QShortcut(QKeySequence.Save, self, self._save_project)
        # 翻页
        QShortcut(QKeySequence("PgUp"), self,
                  lambda: self._goto_page_relative(-1))
        QShortcut(QKeySequence("PgDown"), self,
                  lambda: self._goto_page_relative(1))
        QShortcut(QKeySequence("Home"), self, self._goto_first_page)
        QShortcut(QKeySequence("End"), self, self._goto_last_page)
        # 缩放
        QShortcut(QKeySequence("Ctrl+Plus"), self, self._zoom_in)
        QShortcut(QKeySequence("Ctrl+Minus"), self, self._zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, self._zoom_reset)

    def _calculate_line_font_size(self, line_bbox, text, zoom_level):
        """根据行 bbox 的宽高比判断横排/竖排，计算整行最大可容纳字号。

        参数:
            line_bbox: 行边界框 [x1, y1, x2, y2]
            text: 行文本内容
            zoom_level: 当前缩放率

        返回:
            tuple: (QFont, is_vertical)
                - QFont: 计算出的字体对象
                - is_vertical: True 为竖排，False 为横排
        """
        width = line_bbox[2] - line_bbox[0]
        height = line_bbox[3] - line_bbox[1]
        is_vertical = height > width
        # 候选字号 = 最短边 × 缩放率
        shortest = min(width, height) if (width > 0 and height > 0) else 4
        candidate_size = max(int(shortest * zoom_level), 4)

        font = QFont("Microsoft YaHei")
        font.setPixelSize(candidate_size)
        font.setStyleStrategy(QFont.PreferAntialias)
        fm = QFontMetrics(font)

        if is_vertical:
            # 竖排：检查总高度是否超框
            target_extent = height * zoom_level
            total_extent = sum(fm.horizontalAdvance(ch) for ch in text) if text else 0
            # 竖排时每个字符的高度约等于其宽度（方块字），用 horizontalAdvance 近似
            char_height = fm.ascent() + fm.descent()
            total_height = char_height * len(text) if text else 0
            if total_height > target_extent and target_extent > 0 and total_height > 0:
                candidate_size = max(int(candidate_size * target_extent / total_height), 4)
                font.setPixelSize(candidate_size)
        else:
            # 横排：检查总宽度是否超框
            target_extent = width * zoom_level
            total_extent = sum(fm.horizontalAdvance(ch) for ch in text) if text else 0
            if total_extent > target_extent and target_extent > 0 and total_extent > 0:
                candidate_size = max(int(candidate_size * target_extent / total_extent), 4)
                font.setPixelSize(candidate_size)

        return font, is_vertical

    def _distribute_chars_by_orientation(self, line_bbox, chars, font, is_vertical, zoom_level):
        """按方向在行框内分布字符，返回带位置信息的列表。

        参数:
            line_bbox: 行边界框 [x1, y1, x2, y2]
            chars: 字符数据列表 [{"text": ..., "bbox": ..., "bbox_valid": ...}, ...]
            font: 统一使用的 QFont
            is_vertical: True 为竖排，False 为横排
            zoom_level: 当前缩放率

        返回:
            list: [(char_text, pos_x, pos_y, char_bbox_new), ...]
        """
        x1, y1, x2, y2 = line_bbox
        line_width = x2 - x1
        line_height = y2 - y1
        num_chars = len(chars)
        if num_chars == 0:
            return []

        fm = QFontMetrics(font)
        result = []

        if is_vertical:
            # 竖排：字符从上到下等高排列，水平居中
            char_height = line_height / num_chars
            font_ascent = fm.ascent()
            font_descent = fm.descent()
            font_height = font_ascent + font_descent
            for i, char_data in enumerate(chars):
                char_text = char_data.get("text", "")
                char_width = fm.horizontalAdvance(char_text)
                # 水平居中
                x_offset = max(0, (line_width * zoom_level - char_width) / 2)
                pos_x = x1 * zoom_level + x_offset
                # 垂直排列：第 i 个字符的顶部位置
                pos_y = (y1 + i * char_height) * zoom_level
                # 垂直微调使文字在格子内居中
                pos_y += max(0, (char_height * zoom_level - font_height) / 2)
                # 更新 char 的 bbox
                new_bbox = [x1, y1 + i * char_height, x2, y1 + (i + 1) * char_height]
                char_data["bbox"] = new_bbox
                result.append((char_text, pos_x, pos_y, new_bbox))
        else:
            # 横排：字符从左到右等宽排列，垂直居中
            char_width = line_width / num_chars
            font_ascent = fm.ascent()
            font_descent = fm.descent()
            font_height = font_ascent + font_descent
            for i, char_data in enumerate(chars):
                char_text = char_data.get("text", "")
                char_actual_width = fm.horizontalAdvance(char_text)
                # 水平居中在格子内
                x_offset = max(0, (char_width * zoom_level - char_actual_width) / 2)
                pos_x = (x1 + i * char_width) * zoom_level + x_offset
                # 垂直居中
                y_offset = max(0, (line_height * zoom_level - font_height) / 2)
                pos_y = y1 * zoom_level + y_offset
                # 更新 char 的 bbox
                new_bbox = [x1 + i * char_width, y1, x1 + (i + 1) * char_width, y2]
                char_data["bbox"] = new_bbox
                result.append((char_text, pos_x, pos_y, new_bbox))

        return result

    def _put_pixmap_cache(self, key, pixmap):
        """写入像素缓存，超出上限时淘汰最旧项（FIFO）。"""
        self._pixmap_cache[key] = pixmap
        if len(self._pixmap_cache) > self._pixmap_cache_max:
            _oldest = next(iter(self._pixmap_cache))
            del self._pixmap_cache[_oldest]

    def _render_page(self):
        """渲染当前页面的图像与行切片文本到图形场景中。

        被 _on_prev_page, _on_next_page, _on_goto_page, _on_zoom_in,
        _on_zoom_out, _on_fit_width 调用。执行以下操作：
        1. 清空场景并重置悬停图元
        2. 遍历当前页的行切片，创建 QGraphicsTextItem 并设置位置、字体与颜色
        3. 加载并缩放当前页的原始图像，添加到像素缓存
        4. 设置场景矩形大小
        5. 更新页码标签、页码微调框和缩放百分比标签
        6. 首次渲染时延迟调用 _on_fit_width 自适应宽度

        依赖:
            - _pil_to_pixmap: 将 PIL Image 转换为 QPixmap
            - PyQt5.QGraphicsTextItem, QGraphicsPixmapItem: 场景图元
        """
        self.scene.clear()
        self._hover_pixmap_item = None
        self._hover_rect_item = None
        lines = self.page_lines.get(self.current_page, [])
        for line_slice in lines:
            ignored = hasattr(line_slice, "_ignored") and line_slice._ignored
            if not line_slice.chars:
                # 无字符数据时回退到按行渲染
                item = QGraphicsTextItem(line_slice.text)
                item.setDefaultTextColor(
                    Qt.gray if ignored else Qt.black
                )
                bbox = line_slice.bbox
                font_size = max((bbox[3] - bbox[1]) * self.zoom_level, 6)
                font = QFont("Microsoft YaHei", int(font_size))
                font.setStyleStrategy(QFont.PreferAntialias)
                item.setFont(font)
                item.setPos(bbox[0] * self.zoom_level, bbox[1] * self.zoom_level)
                item.setFlag(QGraphicsTextItem.ItemIsSelectable)
                item.setAcceptHoverEvents(True)
                item.setData(0, id(line_slice))
                item.setData(1, line_slice)
                self.scene.addItem(item)
                continue
            # 有字符数据时：基于行框统一计算字号并排版
            valid_chars = [c for c in line_slice.chars if c.get("bbox_valid", True)]
            if not valid_chars:
                # 所有字符均无效，回退到按行文本渲染
                item = QGraphicsTextItem(line_slice.text)
                item.setDefaultTextColor(Qt.gray if ignored else Qt.black)
                bbox = line_slice.bbox
                font_size = max((bbox[3] - bbox[1]) * self.zoom_level, 6)
                font = QFont("Microsoft YaHei", int(font_size))
                font.setStyleStrategy(QFont.PreferAntialias)
                item.setFont(font)
                item.setPos(bbox[0] * self.zoom_level, bbox[1] * self.zoom_level)
                item.setFlag(QGraphicsTextItem.ItemIsSelectable)
                item.setAcceptHoverEvents(True)
                item.setData(0, id(line_slice))
                item.setData(1, line_slice)
                self.scene.addItem(item)
                continue
            line_text = "".join(c.get("text", "") for c in valid_chars)
            font, is_vertical = self._calculate_line_font_size(
                line_slice.bbox, line_text, self.zoom_level
            )
            char_positions = self._distribute_chars_by_orientation(
                line_slice.bbox, valid_chars, font, is_vertical, self.zoom_level
            )
            for char_text, pos_x, pos_y, _ in char_positions:
                item = QGraphicsTextItem(char_text)
                item.setDefaultTextColor(Qt.gray if ignored else Qt.black)
                item.setFont(font)
                item.setPos(pos_x, pos_y)
                item.setFlag(QGraphicsTextItem.ItemIsSelectable)
                item.setAcceptHoverEvents(True)
                item.setData(0, id(line_slice))
                item.setData(1, line_slice)
                self.scene.addItem(item)

        if self.page_images and self.current_page < len(self.page_images):
            img = self.page_images[self.current_page]
            cache_key = (self.current_page, self.zoom_level)
            if cache_key not in self._pixmap_cache:
                pixmap = self._pil_to_pixmap(img)
                scaled_pixmap = pixmap.scaled(
                    int(img.width * self.zoom_level),
                    int(img.height * self.zoom_level),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self._put_pixmap_cache(cache_key, scaled_pixmap)
            w = img.width * self.zoom_level
            h = img.height * self.zoom_level
            self.scene.setSceneRect(QRectF(0, 0, w, h))

            # 渲染右侧原PDF场景
            self.pdf_scene.clear()
            pdf_cache_key = (self.current_page, self.zoom_level, 'pdf')
            if pdf_cache_key not in self._pixmap_cache:
                pdf_pixmap = self._pil_to_pixmap(img)
                pdf_scaled = pdf_pixmap.scaled(
                    int(img.width * self.zoom_level),
                    int(img.height * self.zoom_level),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self._put_pixmap_cache(pdf_cache_key, pdf_scaled)
            bg_item = QGraphicsPixmapItem(self._pixmap_cache[pdf_cache_key])
            self.pdf_scene.addItem(bg_item)
            self.pdf_scene.setSceneRect(QRectF(0, 0, w, h))
        else:
            self.scene.setSceneRect(QRectF(0, 0, 800, 1000))
            self.pdf_scene.clear()
            self.pdf_scene.setSceneRect(QRectF(0, 0, 800, 1000))

        self.page_label.setText(
            f"第{self.current_page + 1}/{self.total_pages}页"
        )
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.blockSignals(False)
        self.zoom_input.setText(f"{int(self.zoom_level * 100)}%")
        if self._first_render:
            self._first_render = False
            QTimer.singleShot(100, self._on_fit_height)

    def _remove_hover_pixmap(self):
        """移除当前场景中的鼠标悬停预览图元及右侧原PDF蓝色框。

        被 eventFilter 调用。当鼠标移出行切片文本区域或切换到新的
        行切片时，移除之前显示的行切片图像预览图元和右侧蓝色框，并重置悬停状态。
        """
        if self._hover_pixmap_item is not None:
            self.scene.removeItem(self._hover_pixmap_item)
            self._hover_pixmap_item = None
        if self._hover_rect_item is not None:
            self.pdf_scene.removeItem(self._hover_rect_item)
            self._hover_rect_item = None

    def _handle_mid_pan(self, event, view):
        """处理中键拖拽平移，返回 True 表示事件已被处理。

        在左视图和右视图的 eventFilter 中共用。中键按下时记录起始全局坐标
        和滚动条位置，移动时按 delta 平移滚动条，释放时恢复光标。
        不影响左键画框、右键菜单等现有交互。
        """
        if not isinstance(event, QMouseEvent):
            return False
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.MiddleButton:
            self._mid_panning = True
            self._mid_panning_view = view
            self._mid_start_pos = event.globalPos()
            self._mid_start_pixmap_pos = (
                view.horizontalScrollBar().value(),
                view.verticalScrollBar().value(),
            )
            self._mid_prev_cursor = view.cursor()
            view.setCursor(Qt.ClosedHandCursor)
            return True
        if event.type() == QEvent.MouseMove and self._mid_panning and self._mid_panning_view is view:
            delta = event.globalPos() - self._mid_start_pos
            view.horizontalScrollBar().setValue(self._mid_start_pixmap_pos[0] - delta.x())
            view.verticalScrollBar().setValue(self._mid_start_pixmap_pos[1] - delta.y())
            return True
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.MiddleButton:
            if self._mid_panning and self._mid_panning_view is view:
                self._mid_panning = False
                self._mid_panning_view = None
                view.setCursor(self._mid_prev_cursor)
                return True
        return False

    def eventFilter(self, obj, event):
        """事件过滤器，处理鼠标悬停时显示行切片图像预览。

        由 view.viewport 的事件过滤器触发。监听视口上的鼠标移动事件，
        当鼠标悬停在行切片文本图元上时，在文本上方显示对应的行切片
        原始图像预览。使用缓存机制避免重复生成同一行的预览图。

        参数:
            obj: 事件目标对象，仅处理 view.viewport() 的事件。
            event: 事件对象，仅处理 QMouseMove 类型的鼠标事件。

        返回:
            bool: 始终返回 False，不拦截事件，允许事件继续传播。

        调用关系:
            - 调用 _remove_hover_pixmap 移除旧预览
            - 调用 _make_slice_pixmap 生成行切片预览图

        依赖:
            - PyQt5.QMouseEvent: 鼠标事件类型判断
            - PyQt5.QGraphicsPixmapItem: 预览图元
        """
        if obj is self.view.viewport():
            if self._handle_mid_pan(event, self.view):
                return True
            new_zoom = calculate_wheel_zoom(event, self.zoom_level)
            if new_zoom is not None:
                self.zoom_level = new_zoom
                self._render_page()
                return True
            if isinstance(event, QWheelEvent):
                v_bar = self.view.verticalScrollBar()
                delta = event.angleDelta().y()
                if delta > 0 and v_bar.value() == v_bar.minimum():
                    if self.current_page > 0:
                        self.current_page -= 1
                        self._render_page()
                        QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                            self.view.verticalScrollBar().maximum()))
                    return True
                elif delta < 0 and v_bar.value() == v_bar.maximum():
                    if self.current_page < self.total_pages - 1:
                        self.current_page += 1
                        self._render_page()
                        QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                            self.view.verticalScrollBar().minimum()))
                    return True
            if isinstance(event, QMouseEvent):
                if event.type() == QEvent.MouseMove:
                    scene_pos = self.view.mapToScene(event.pos())
                    item = self.scene.itemAt(scene_pos, self.view.transform())
                    if isinstance(item, QGraphicsTextItem):
                        ls = item.data(1)
                        if ls is not None:
                            if self._hover_pixmap_item is not None and self._hover_pixmap_item.data(0) == id(ls):
                                return False
                            self._remove_hover_pixmap()
                            ls_id = id(ls)
                            if self._slice_cache_id == ls_id and self._slice_cache_pixmap is not None:
                                pixmap = self._slice_cache_pixmap
                            else:
                                pixmap = self._make_slice_pixmap(ls)
                                self._slice_cache_id = ls_id
                                self._slice_cache_pixmap = pixmap
                            if pixmap is not None and pixmap.width() > 0:
                                page_img = self.page_images[self.current_page]
                                full_w = page_img.width * self.zoom_level
                                scale_x = full_w / pixmap.width()
                                target_w = max(1, int(pixmap.width() * scale_x))
                                target_h = max(1, int(pixmap.height() * scale_x))
                                scaled_pixmap = pixmap.scaled(
                                    target_w,
                                    target_h,
                                    Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation,
                                )
                                pi = QGraphicsPixmapItem(scaled_pixmap)
                                pi_h = scaled_pixmap.height()
                                line_x = 0
                                line_y = ls.bbox[1] * self.zoom_level
                                pi.setPos(line_x, line_y - pi_h)
                                pi.setZValue(100)
                                pi.setData(0, id(ls))
                                self.scene.addItem(pi)
                                self._hover_pixmap_item = pi

                            # 在右侧原PDF场景中画蓝色框
                            if self._hover_rect_item is not None:
                                self.pdf_scene.removeItem(self._hover_rect_item)
                                self._hover_rect_item = None
                            bbox = ls.bbox
                            rect = QRectF(
                                bbox[0] * self.zoom_level,
                                bbox[1] * self.zoom_level,
                                (bbox[2] - bbox[0]) * self.zoom_level,
                                (bbox[3] - bbox[1]) * self.zoom_level,
                            )
                            pen = QPen(Qt.blue, 2)
                            brush = QBrush(Qt.transparent)
                            rect_item = QGraphicsRectItem(rect)
                            rect_item.setPen(pen)
                            rect_item.setBrush(brush)
                            rect_item.setZValue(10)
                            self.pdf_scene.addItem(rect_item)
                            self._hover_rect_item = rect_item
                        else:
                            self._remove_hover_pixmap()
                    else:
                        self._remove_hover_pixmap()
            return False
        elif obj is self.pdf_view.viewport():
            if self._handle_mid_pan(event, self.pdf_view):
                return True
            if self._draw_box_mode and isinstance(event, QMouseEvent):
                if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                    self._draw_start_pos = event.pos()
                    if self._draw_rubber_band is None:
                        self._draw_rubber_band = QRubberBand(QRubberBand.Rectangle, self.pdf_view.viewport())
                    self._draw_rubber_band.setGeometry(QRect(self._draw_start_pos, self._draw_start_pos))
                    self._draw_rubber_band.show()
                    return True
                elif event.type() == QEvent.MouseMove and self._draw_start_pos is not None:
                    self._draw_rubber_band.setGeometry(
                        QRect(self._draw_start_pos, event.pos()).normalized()
                    )
                    return True
                elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                    if self._draw_start_pos is not None and self._draw_rubber_band is not None:
                        rect = QRect(self._draw_start_pos, event.pos()).normalized()
                        self._apply_drawn_box(rect)
                    return True
            if isinstance(event, QWheelEvent):
                v_bar = self.pdf_view.verticalScrollBar()
                delta = event.angleDelta().y()
                if delta > 0 and v_bar.value() == v_bar.minimum():
                    if self.current_page > 0:
                        self.current_page -= 1
                        self._render_page()
                        QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                            self.view.verticalScrollBar().maximum()))
                        QTimer.singleShot(0, lambda: self.pdf_view.verticalScrollBar().setValue(
                            self.pdf_view.verticalScrollBar().maximum()))
                    return True
                elif delta < 0 and v_bar.value() == v_bar.maximum():
                    if self.current_page < self.total_pages - 1:
                        self.current_page += 1
                        self._render_page()
                        QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                            self.view.verticalScrollBar().minimum()))
                        QTimer.singleShot(0, lambda: self.pdf_view.verticalScrollBar().setValue(
                            self.pdf_view.verticalScrollBar().minimum()))
                    return True
            return False
        return super().eventFilter(obj, event)

    def _make_slice_pixmap(self, ls: LineSlice):
        """根据行切片数据生成全宽页面切片预览 QPixmap。

        被 eventFilter 调用。从页面原图中裁剪该行对应的区域，
        宽度横跨整个PDF页面（从左边界到右边界），上下坐标保持行bbox的Y范围。

        参数:
            ls (LineSlice): 行切片数据对象，包含 page_num、bbox 属性。

        返回:
            QPixmap | None: 生成的预览图像；若无法生成有效图像则返回 None。

        依赖:
            - _pil_to_pixmap: 将 PIL Image 转换为 QPixmap
            - models.data_models.LineSlice: 行切片数据模型
        """
        if (
            self.page_images is not None
            and ls.page_num < len(self.page_images)
        ):
            page_img = self.page_images[ls.page_num]
            bbox = ls.bbox
            pad = 20
            x1 = 0
            y1 = max(int(bbox[1]) - pad, 0)
            x2 = page_img.width
            y2 = min(int(bbox[3]) + pad, page_img.height)
            if x2 <= x1 or y2 <= y1:
                return None
            cropped = page_img.crop((x1, y1, x2, y2))
            return self._pil_to_pixmap(cropped)
        return None

    def _on_left_v_scroll(self, value):
        """左侧视图垂直滚动时同步右侧视图。"""
        self.pdf_view.verticalScrollBar().blockSignals(True)
        self.pdf_view.verticalScrollBar().setValue(value)
        self.pdf_view.verticalScrollBar().blockSignals(False)

    def _on_left_h_scroll(self, value):
        """左侧视图水平滚动时同步右侧视图。"""
        self.pdf_view.horizontalScrollBar().blockSignals(True)
        self.pdf_view.horizontalScrollBar().setValue(value)
        self.pdf_view.horizontalScrollBar().blockSignals(False)

    def _on_right_v_scroll(self, value):
        """右侧视图垂直滚动时同步左侧视图。"""
        self.view.verticalScrollBar().blockSignals(True)
        self.view.verticalScrollBar().setValue(value)
        self.view.verticalScrollBar().blockSignals(False)

    def _on_right_h_scroll(self, value):
        """右侧视图水平滚动时同步左侧视图。"""
        self.view.horizontalScrollBar().blockSignals(True)
        self.view.horizontalScrollBar().setValue(value)
        self.view.horizontalScrollBar().blockSignals(False)

    def _on_context_menu(self, pos):
        """处理右键上下文菜单，提供修改文字、忽略行、重新定位行框及新增文段入口。

        由 view.customContextMenuRequested 信号触发。点击行文本图元时
        显示"修改文字"、"忽略/删除"、"重新定位行框"三项；点击空白处时
        显示"新增文段"。

        参数:
            pos: 视口坐标系中的右键点击位置，由信号自动传入。

        调用关系:
            - 调用 _on_modify_text 执行文字修改
            - 调用 _on_ignore_line 执行行忽略
            - 调用 _on_relocate_line 进入重新定位画框模式
            - 调用 _on_add_text_segment 进入新增文段画框模式

        依赖:
            - PyQt5.QMenu: 右键菜单组件
        """
        scene_pos = self.view.mapToScene(pos)
        item = self.scene.itemAt(scene_pos, self.view.transform())
        menu = QMenu(self)
        if isinstance(item, QGraphicsTextItem):
            modify_action = menu.addAction("修改文字")
            ls = item.data(1)
            is_ignored = ls is not None and hasattr(ls, "_ignored") and ls._ignored
            ignore_action = menu.addAction("取消忽略" if is_ignored else "忽略/删除")
            relocate_action = menu.addAction("重新定位行框")
            chosen = menu.exec(self.view.mapToGlobal(pos))
            if chosen == modify_action:
                self._on_modify_text(item)
            elif chosen == ignore_action:
                self._on_ignore_line(item)
            elif chosen == relocate_action:
                self._on_relocate_line(item)
        else:
            add_text_action = menu.addAction("新增文段")
            chosen = menu.exec(self.view.mapToGlobal(pos))
            if chosen == add_text_action:
                self._on_add_text_segment()

    def _on_modify_text(self, item: QGraphicsTextItem):
        """打开修改文字对话框，允许用户编辑行切片的文本内容。

        被 _on_context_menu 调用。弹出对话框让用户输入新文本，
        确认后更新行切片的 text 属性、图元显示内容，并记录修改操作。

        参数:
            item (QGraphicsTextItem): 被右键点击的文本图元，
                其 data(1) 存储了关联的 LineSlice 对象。

        依赖:
            - PyQt5.QDialog, QLineEdit, QPushButton: 对话框组件
            - models.data_models.LineSlice: 行切片数据模型
        """
        ls = item.data(1)
        if ls is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("修改文字")
        dialog.setMinimumWidth(400)
        dialog_layout = QVBoxLayout(dialog)
        prompt = QLabel("请输入新的文字内容：")
        dialog_layout.addWidget(prompt)
        line_edit = QLineEdit()
        line_edit.setText(ls.text)
        line_edit.selectAll()
        dialog_layout.addWidget(line_edit)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        dialog_layout.addLayout(btn_layout)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        line_edit.returnPressed.connect(dialog.accept)
        if dialog.exec() != QDialog.Accepted:
            return
        new_text = line_edit.text().strip()
        if not new_text or new_text == ls.text:
            return
        old_text = ls.text
        # 通过撤销栈 push 命令执行修改，命令 redo 会调用 _apply_modify_line_text
        self._undo_stack.push(
            ModifyLineTextCommand(self, ls, old_text, new_text)
        )
        self.modifications.append(
            {"type": "modify_text", "old_text": old_text, "details": new_text}
        )

    def _sync_chars_with_text(self, ls):
        """在修改行文本后同步更新字符列表。

        当横校修改了 LineSlice.text 后，需要同步更新 LineSlice.chars，
        以确保后续精修阶段能读取到修改后的文字。

        - 字符数相同时：逐个替换原字符的 text，保留原 bbox
        - 字符数不同时：按行 bbox 等间距分配新字符的 bbox

        参数:
            ls: 被修改了 text 属性的 LineSlice 对象。

        调用关系:
            被 _on_modify_text 调用。
        """
        if not ls.chars:
            return
        new_text = ls.text
        old_chars = ls.chars

        if len(new_text) == len(old_chars):
            for i, ch in enumerate(new_text):
                old_chars[i]["text"] = ch
        else:
            line_bbox = ls.bbox
            line_width = line_bbox[2] - line_bbox[0]
            char_width = line_width / len(new_text) if new_text else line_width
            new_chars = []
            for i, ch in enumerate(new_text):
                new_chars.append({
                    "text": ch,
                    "bbox": [
                        line_bbox[0] + i * char_width,
                        line_bbox[1],
                        line_bbox[0] + (i + 1) * char_width,
                        line_bbox[3],
                    ],
                    "bbox_valid": True,
                })
            ls.chars = new_chars

    # ============== 撤销/重做命令的 _apply_xxx 辅助方法 ==============
    # 约定：这些方法仅直接修改数据并刷新界面，不要再 push 命令（避免递归）。
    # line_index 参数实际传入 LineSlice 对象引用，保证 undo/redo 时即使翻页也能改对。

    def _apply_modify_line_text(self, line_index, new_text):
        """修改指定行的文本并刷新界面（供 ModifyLineTextCommand 调用）。

        参数:
            line_index: 实际为 LineSlice 对象引用。
            new_text: 新文本内容。
        """
        ls = line_index
        ls.text = new_text
        self._sync_chars_with_text(ls)
        self._render_page()

    def _apply_toggle_ignore(self, line_index, new_ignored):
        """切换指定行的忽略状态并刷新界面（供 ToggleIgnoreCommand 调用）。

        参数:
            line_index: 实际为 LineSlice 对象引用。
            new_ignored: bool，True 表示忽略，False 表示取消忽略。
        """
        ls = line_index
        ls._ignored = bool(new_ignored)
        self._render_page()

    def _apply_relocate_line(self, line_index, new_box):
        """重新定位指定行的框并刷新界面（供 RelocateLineFrameCommand 调用）。

        参数:
            line_index: 实际为 LineSlice 对象引用。
            new_box: 新框坐标 [x1, y1, x2, y2]（图像像素坐标）。
        """
        ls = line_index
        # 复用 _relocate_line_frame 的核心数据修改逻辑（不记录 modifications）
        self._relocate_line_frame(ls, list(new_box))
        self._render_page()

    def _on_ignore_line(self, item: QGraphicsTextItem):
        """切换指定行切片的忽略状态，并在界面上以灰色/正常显示。

        被 _on_context_menu 调用。切换行切片的 _ignored 属性，
        将文本颜色改为灰色(忽略)或黑色(恢复)以示区分，并记录操作。

        参数:
            item (QGraphicsTextItem): 被右键点击的文本图元，
                其 data(1) 存储了关联的 LineSlice 对象。

        依赖:
            - models.data_models.LineSlice: 行切片数据模型
        """
        ls = item.data(1)
        if ls is None:
            return
        old_ignored = bool(getattr(ls, "_ignored", False))
        new_ignored = not old_ignored
        # 通过撤销栈 push 命令执行切换，命令 redo 会调用 _apply_toggle_ignore
        self._undo_stack.push(
            ToggleIgnoreCommand(self, ls, old_ignored, new_ignored)
        )
        self.modifications.append(
            {"type": "ignore" if new_ignored else "unignore",
             "text": ls.text, "details": "ignored" if new_ignored else "unignored"}
        )

    def _enter_draw_box_mode(self, target_ls=None, new_text=None):
        """进入画框模式，等待用户在右侧PDF上绘制矩形。

        参数:
            target_ls: 要重新定位的 LineSlice（重新定位行框场景）
            new_text: 新增文段的文本（新增文段场景）
        """
        self._draw_box_mode = True
        self._draw_box_target = target_ls
        self._draw_box_text = new_text
        self._draw_rubber_band = None
        self._draw_start_pos = None
        self.draw_mode_hint.show()
        self.pdf_view.setCursor(Qt.CrossCursor)
        self.pdf_view.setMouseTracking(True)

    def _exit_draw_box_mode(self):
        """退出画框模式，重置所有状态。"""
        self._draw_box_mode = False
        self._draw_box_target = None
        self._draw_box_text = None
        if self._draw_rubber_band is not None:
            self._draw_rubber_band.hide()
            self._draw_rubber_band.deleteLater()
            self._draw_rubber_band = None
        self._draw_start_pos = None
        self.draw_mode_hint.hide()
        self.pdf_view.unsetCursor()

    def _on_relocate_line(self, item: QGraphicsTextItem):
        """右键菜单"重新定位行框"入口，进入画框模式。

        参数:
            item: 被右键点击的文本图元，其 data(1) 存储关联的 LineSlice。
        """
        ls = item.data(1)
        if ls is None:
            return
        self._enter_draw_box_mode(target_ls=ls)

    def _on_add_text_segment(self):
        """右键空白处"新增文段"入口，弹出文本输入对话框后进入画框模式。"""
        text, ok = QInputDialog.getText(self, "新增文段", "请输入文本内容：")
        if not ok or not text.strip():
            return
        self._enter_draw_box_mode(new_text=text.strip())

    def _apply_drawn_box(self, view_rect):
        """应用绘制的矩形框，转换为图像像素坐标并执行相应操作。

        参数:
            view_rect: 视口坐标系下的 QRect
        """
        # 视口坐标→场景坐标
        tl_scene = self.pdf_view.mapToScene(view_rect.topLeft())
        br_scene = self.pdf_view.mapToScene(view_rect.bottomRight())
        # 场景坐标÷zoom→图像像素坐标
        zoom = self.zoom_level if self.zoom_level > 0 else 1.0
        x1 = tl_scene.x() / zoom
        y1 = tl_scene.y() / zoom
        x2 = br_scene.x() / zoom
        y2 = br_scene.y() / zoom
        # clamp 到页面边界
        if self.page_images and self.current_page < len(self.page_images):
            img_w = self.page_images[self.current_page].width
            img_h = self.page_images[self.current_page].height
            x1 = max(0, min(x1, img_w))
            y1 = max(0, min(y1, img_h))
            x2 = max(0, min(x2, img_w))
            y2 = max(0, min(y2, img_h))
        new_bbox = [x1, y1, x2, y2]
        # 检查最小尺寸
        if (x2 - x1) < 10 or (y2 - y1) < 10:
            QMessageBox.warning(self, "提示", "绘制的框太小，请重新绘制至少 10x10 像素的区域。")
            self._exit_draw_box_mode()
            return
        # 弹出确认对话框
        reply = QMessageBox.question(
            self, "确认",
            f"确认使用此框？\n尺寸: {int(x2-x1)} x {int(y2-y1)} 像素",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            self._exit_draw_box_mode()
            return
        # 根据状态执行对应操作
        if self._draw_box_target is not None:
            target_ls = self._draw_box_target
            old_box = list(target_ls.bbox)
            # 通过撤销栈 push 命令执行重定位，命令 redo 会调用 _apply_relocate_line
            self._undo_stack.push(
                RelocateLineFrameCommand(self, target_ls, old_box, list(new_bbox))
            )
        elif self._draw_box_text is not None:
            self._add_new_text_segment(self._draw_box_text, new_bbox)
            self._render_page()
        self._exit_draw_box_mode()

    def _add_new_text_segment(self, text, new_bbox):
        """创建新的 LineSlice 并添加到当前页。

        参数:
            text: 新文段文本
            new_bbox: 新框坐标 [x1, y1, x2, y2]（图像像素坐标）
        """
        # 按新 bbox 方向构建 chars
        width = new_bbox[2] - new_bbox[0]
        height = new_bbox[3] - new_bbox[1]
        is_vertical = height > width
        num_chars = len(text)
        chars = []
        if num_chars > 0:
            if is_vertical:
                char_h = height / num_chars
                for i, ch in enumerate(text):
                    chars.append({
                        "text": ch,
                        "bbox": [new_bbox[0], new_bbox[1] + i * char_h,
                                 new_bbox[2], new_bbox[1] + (i + 1) * char_h],
                        "bbox_valid": True,
                    })
            else:
                char_w = width / num_chars
                for i, ch in enumerate(text):
                    chars.append({
                        "text": ch,
                        "bbox": [new_bbox[0] + i * char_w, new_bbox[1],
                                 new_bbox[0] + (i + 1) * char_w, new_bbox[3]],
                        "bbox_valid": True,
                    })
        # 从页面图像裁剪行图像
        line_image = None
        if self.page_images and self.current_page < len(self.page_images):
            page_img = self.page_images[self.current_page]
            x1 = max(0, int(round(new_bbox[0])))
            y1 = max(0, int(round(new_bbox[1])))
            x2 = min(page_img.width, int(round(new_bbox[2])))
            y2 = min(page_img.height, int(round(new_bbox[3])))
            if x2 > x1 and y2 > y1:
                line_image = page_img.crop((x1, y1, x2, y2))
        # 创建 LineSlice 并追加
        new_ls = LineSlice(
            page_num=self.current_page,
            bbox=list(new_bbox),
            polygon=[],
            text=text,
            confidence=1.0,
            chars=chars,
            image=line_image,
        )
        if self.current_page not in self.page_lines:
            self.page_lines[self.current_page] = []
        self.page_lines[self.current_page].append(new_ls)
        self.modifications.append({"type": "add_text_segment", "details": text})

    def _relocate_line_frame(self, line_slice, new_bbox):
        """重新定位行框，更新 bbox、chars 分布和 image（核心数据修改，不记录 modifications）。

        被 _apply_relocate_line 调用。仅修改数据，不渲染、不记录 modifications，
        避免命令 undo/redo 时重复记录。

        参数:
            line_slice: 要更新的 LineSlice 对象
            new_bbox: 新框坐标 [x1, y1, x2, y2]（图像像素坐标）
        """
        line_slice.bbox = list(new_bbox)
        # 按新 bbox 方向重新分布 chars
        if line_slice.chars:
            width = new_bbox[2] - new_bbox[0]
            height = new_bbox[3] - new_bbox[1]
            is_vertical = height > width
            num_chars = len(line_slice.chars)
            if is_vertical:
                char_h = height / num_chars if num_chars > 0 else height
                for i, c in enumerate(line_slice.chars):
                    c["bbox"] = [new_bbox[0], new_bbox[1] + i * char_h,
                                 new_bbox[2], new_bbox[1] + (i + 1) * char_h]
                    c["bbox_valid"] = True
            else:
                char_w = width / num_chars if num_chars > 0 else width
                for i, c in enumerate(line_slice.chars):
                    c["bbox"] = [new_bbox[0] + i * char_w, new_bbox[1],
                                 new_bbox[0] + (i + 1) * char_w, new_bbox[3]]
                    c["bbox_valid"] = True
        # 重新裁剪行图像
        if self.page_images and line_slice.page_num < len(self.page_images):
            page_img = self.page_images[line_slice.page_num]
            x1 = max(0, int(round(new_bbox[0])))
            y1 = max(0, int(round(new_bbox[1])))
            x2 = min(page_img.width, int(round(new_bbox[2])))
            y2 = min(page_img.height, int(round(new_bbox[3])))
            if x2 > x1 and y2 > y1:
                line_slice.image = page_img.crop((x1, y1, x2, y2))

    def _on_hand_tool_toggle(self):
        """切换手型拖拽工具的启用状态。

        由 hand_btn.clicked 信号触发。启用时设置视图为滚动拖拽模式
        并显示张开手掌光标；禁用时恢复无拖拽模式和箭头光标。
        """
        if self.hand_btn.isChecked():
            self.view.setDragMode(QGraphicsView.ScrollHandDrag)
            self.view.setCursor(Qt.OpenHandCursor)
        else:
            self.view.setDragMode(QGraphicsView.NoDrag)
            self.view.setCursor(Qt.ArrowCursor)

    def _on_prev_page(self):
        """切换到上一页。

        由 prev_btn.clicked 信号触发。当当前页非首页时，页码减一
        并调用 _render_page 重新渲染。

        调用关系:
            - 调用 _render_page 重新渲染页面
        """
        if self.current_page > 0:
            self.current_page -= 1
            self._render_page()

    def _on_next_page(self):
        """切换到下一页。

        由 next_btn.clicked 信号触发。当当前页非末页时，页码加一
        并调用 _render_page 重新渲染。

        调用关系:
            - 调用 _render_page 重新渲染页面
        """
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_page()

    def _on_goto_page(self, page_num: int):
        """跳转到指定页码。

        由 page_spin.valueChanged 信号触发。将页码转换为从零开始的
        索引并调用 _render_page 重新渲染。

        参数:
            page_num (int): 目标页码（从 1 开始），由微调框信号自动传入。

        调用关系:
            - 调用 _render_page 重新渲染页面
        """
        idx = page_num - 1
        if 0 <= idx < self.total_pages:
            self.current_page = idx
            self._render_page()

    def _on_page_spin_changed(self, _value):
        """页码微调框值变化时启动防抖计时器，避免长按箭头堆积渲染。"""
        # start(300) 会自动重置正在运行的计时器，等效于先 stop 再 start
        self._page_debounce.start(300)

    def _do_render_page(self):
        """防抖计时器超时后执行实际翻页渲染。"""
        idx = self.page_spin.value() - 1
        if 0 <= idx < self.total_pages:
            self.current_page = idx
            self._render_page()

    def _on_zoom_input(self):
        """缩放输入框回车处理，修改缩放率。"""
        text = self.zoom_input.text().strip().rstrip('%')
        try:
            zoom_pct = int(text)
            if 10 <= zoom_pct <= 1000:
                self.zoom_level = zoom_pct / 100
                self._render_page()
        except ValueError:
            pass
        self.zoom_input.setText(f"{int(self.zoom_level * 100)}%")

    def _on_zoom_in(self):
        if self.zoom_level < ZOOM_MAX:
            self.zoom_level += 0.25
            self._render_page()

    def _on_zoom_out(self):
        if self.zoom_level > ZOOM_MIN:
            self.zoom_level -= 0.25
            self._render_page()

    def _on_fit_width(self):
        """将视图缩放调整为适合视口宽度。

        由 fit_width_btn.clicked 信号和首次渲染触发。根据当前页面
        图像宽度与视口可用宽度的比值计算 zoom_level，然后调用
        _render_page 重新渲染。

        调用关系:
            - 调用 _render_page 重新渲染页面
        """
        if not self.page_images or self.current_page >= len(self.page_images):
            return
        view_width = self.view.viewport().width() - 20
        img_width = self.page_images[self.current_page].width
        if img_width > 0:
            self.zoom_level = view_width / img_width
            self._render_page()

    def _on_fit_height(self):
        """将视图缩放调整为适合视口高度。"""
        if not self.page_images or self.current_page >= len(self.page_images):
            return
        view_height = self.view.viewport().height() - 20
        img_height = self.page_images[self.current_page].height
        if img_height > 0:
            self.zoom_level = view_height / img_height
            self._render_page()

    def resizeEvent(self, event):
        """窗口大小变化时，若最大化则自动适配高度。"""
        super().resizeEvent(event)
        is_maximized = bool(self.windowState() & Qt.WindowMaximized)
        if is_maximized and not getattr(self, '_was_maximized', False):
            if self.page_images:
                QTimer.singleShot(50, self._on_fit_height)
        self._was_maximized = is_maximized

    def _on_finish(self):
        """完成横校操作，弹出确认对话框并发射完成信号。

        由 finish_btn.clicked 信号触发。统计修改和忽略的操作数量，
        弹出确认对话框供用户确认。确认后调用 _build_corrected_lines
        构建校对结果列表，并通过 finished_signal 发射。

        调用关系:
            - 调用 _build_corrected_lines 构建校对结果
            - 发射 finished_signal 信号

        依赖:
            - PyQt5.QDialog, QPushButton: 确认对话框组件
        """
        modify_count = sum(
            1 for m in self.modifications if m["type"] == "modify_text"
        )
        ignore_count = sum(
            1 for m in self.modifications if m["type"] == "ignore"
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("确认完成横校")
        dialog.setMinimumWidth(400)
        dialog_layout = QVBoxLayout(dialog)
        summary = QLabel(
            f"修改文字：{modify_count} 处\n"
            f"忽略行：{ignore_count} 处"
        )
        dialog_layout.addWidget(summary)
        btn_layout = QHBoxLayout()
        confirm_btn = QPushButton("确认")
        return_btn = QPushButton("返回继续校验")
        btn_layout.addStretch()
        btn_layout.addWidget(confirm_btn)
        btn_layout.addWidget(return_btn)
        dialog_layout.addLayout(btn_layout)
        confirm_btn.clicked.connect(dialog.accept)
        return_btn.clicked.connect(dialog.reject)
        if dialog.exec() == QDialog.Accepted:
            corrected = self._build_corrected_lines()
            self.finished_signal.emit(corrected)

    def _report_error(self, exc):
        """打印异常 traceback 并通过 error_occurred 信号回显到状态栏。"""
        traceback.print_exc()
        self.error_occurred.emit(f"操作失败：{exc}")

    def _pil_to_pixmap(self, pil_image) -> QPixmap:
        """将 PIL Image 对象转换为 QPixmap。

        被 _render_page, eventFilter, _make_slice_pixmap 调用。
        优先调用 native (H1) 直通路径，跳过 PIL convert + tobytes 的多次拷贝；
        native 不可用时回落到原 PIL→QImage 路径，行为不变。

        参数:
            pil_image: PIL Image 对象，支持任意图像模式。

        返回:
            QPixmap: 转换后的 QPixmap 对象；若输入为 None 则返回空 QPixmap。

        依赖:
            - PyQt5.QPixmap, QImage: 图像格式转换
            - PIL.Image: 输入图像格式
        """
        if pil_image is None:
            return QPixmap()
        # H4: native 统一转换路径（RGB→RGBA 扩展 + 紧凑化在 C++ 内完成）
        try:
            pil_to_qimage_buffer = _try_native()[3]
            if pil_to_qimage_buffer is not None:
                mode = pil_image.mode
                if mode in ("RGB", "RGBA"):
                    raw = pil_image.tobytes("raw", mode)
                    buf = pil_to_qimage_buffer(
                        raw, pil_image.width, pil_image.height, mode, 0
                    )
                    if buf is not None:
                        qimage = QImage(
                            buf,
                            pil_image.width,
                            pil_image.height,
                            pil_image.width * 4,
                            QImage.Format_RGBA8888,
                        )
                        return QPixmap.fromImage(qimage.copy())
                else:
                    # P/L 等模式先 convert("RGB") 再传入 H4
                    pil_rgb = pil_image.convert("RGB")
                    raw = pil_rgb.tobytes("raw", "RGB")
                    buf = pil_to_qimage_buffer(
                        raw, pil_rgb.width, pil_rgb.height, "RGB", 0
                    )
                    if buf is not None:
                        qimage = QImage(
                            buf,
                            pil_rgb.width,
                            pil_rgb.height,
                            pil_rgb.width * 4,
                            QImage.Format_RGBA8888,
                        )
                        return QPixmap.fromImage(qimage.copy())
        except Exception as exc:
            self._report_error(exc)
        # Fallback: 原 PIL→QImage 路径
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")
        data = bytearray(pil_image.tobytes("raw", "RGBA"))
        qimage = QImage(
            data,
            pil_image.width,
            pil_image.height,
            QImage.Format_RGBA8888,
        )
        return QPixmap.fromImage(qimage)

    def _build_corrected_lines(self) -> list:
        """遍历所有页面的行切片，构建校对结果列表。

        被 _on_finish 调用。按页码排序遍历所有行切片，将每个 LineSlice
        转换为 CorrectedLine 对象，包含文本、边界框、页码和忽略状态。

        返回:
            list: CorrectedLine 对象列表，包含所有页面的校对结果。

        依赖:
            - models.data_models.CorrectedLine: 校对结果数据模型
            - models.data_models.LineSlice: 行切片数据模型
        """
        result = []
        for page_num in sorted(self.page_lines.keys()):
            for ls in self.page_lines[page_num]:
                ignored = hasattr(ls, "_ignored") and ls._ignored
                result.append(
                    CorrectedLine(
                        text=ls.text,
                        bbox=list(ls.bbox),
                        page_num=ls.page_num,
                        ignored=ignored,
                    )
                )
        return result

    def _on_back(self):
        """处理返回按钮点击事件，发射返回信号。

        调用关系:
            由 back_btn.clicked 信号触发，发射 back_signal。
        """
        self.back_signal.emit()

    def keyPressEvent(self, event):
        """处理按键事件，ESC 退出画框模式。"""
        if event.key() == Qt.Key_Escape and self._draw_box_mode:
            self._exit_draw_box_mode()
            return
        super().keyPressEvent(event)

    # ============== Ctrl+S 保存与断点恢复 ==============

    def _save_project(self):
        """Ctrl+S 保存入口：收集本阶段断点并发射 save_requested 信号。

        由 MainWindow 接收信号后合并全局数据，再调用 SessionManager.save。
        断点结构：
            {"horizontal": {"current_page": ..., "zoom_level": ...}}
        """
        breakpoints = {
            "horizontal": {
                "current_page": self.current_page,
                "zoom_level": self.zoom_level,
            }
        }
        self.save_requested.emit(breakpoints)

    def _restore_breakpoint_state(self, breakpoints):
        """恢复横校阶段断点状态。

        参数:
            breakpoints: 横校阶段断点字典，形如
                {"current_page": int, "zoom_level": float}；
                也兼容传入外层 {"horizontal": {...}} 结构。
        """
        # 兼容传入外层 {"horizontal": {...}} 或直接 {...}
        if isinstance(breakpoints, dict) and "horizontal" in breakpoints:
            bp = breakpoints.get("horizontal", {}) or {}
        else:
            bp = breakpoints or {}

        page = bp.get("current_page", 0)
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = 0
        if 0 <= page < self.total_pages:
            self.current_page = page

        zoom = bp.get("zoom_level", 1.0)
        try:
            zoom = float(zoom)
        except (TypeError, ValueError):
            zoom = 1.0
        # 与 Phase 1 缩放逻辑保持一致：通过 zoom_level 重新渲染（而非 view.scale）
        self.zoom_level = zoom

        # 同步页码微调框（阻塞信号避免触发防抖），再即时渲染当前页
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(self.current_page + 1)
        self.page_spin.blockSignals(False)
        self._do_render_page()

    # ============== 翻页与缩放辅助方法（供快捷键调用） ==============

    def _goto_page_relative(self, delta):
        """相对翻页：从当前页前进/后退 delta 页。

        参数:
            delta: 整数，正为向后翻，负为向前翻。
        """
        max_page = self.total_pages if self.total_pages > 0 else 1
        # current_page 为 0-based，page_spin 为 1-based
        new_page = max(1, min(max_page, self.current_page + 1 + delta))
        self.page_spin.setValue(new_page)

    def _goto_first_page(self):
        """跳转到首页。"""
        self.page_spin.setValue(1)

    def _goto_last_page(self):
        """跳转到末页。"""
        if self.total_pages > 0:
            self.page_spin.setValue(self.total_pages)

    def _zoom_in(self):
        """放大一级（复用工具栏 _on_zoom_in 逻辑）。"""
        self._on_zoom_in()

    def _zoom_out(self):
        """缩小一级（复用工具栏 _on_zoom_out 逻辑）。"""
        self._on_zoom_out()

    def _zoom_reset(self):
        """重置缩放至 100%。"""
        self.zoom_level = 1.0
        self._render_page()