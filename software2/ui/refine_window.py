from PyQt5.QtWidgets import (
    QWidget,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QGraphicsPixmapItem,
    QLabel,
    QPushButton,
    QSpinBox,
    QToolBar,
    QDialog,
    QLineEdit,
    QMenu,
    QFileDialog,
    QVBoxLayout,
    QHBoxLayout,
    QProgressDialog,
    QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QEvent, QRectF, QPointF, QTimer
from PyQt5.QtGui import QPixmap, QImage, QFont, QFontMetrics, QPen, QBrush, QPainter, QCursor, QWheelEvent
import os

from models.data_models import RefineTextItem, CorrectedChar, LineSlice
from pdf_processor.pdf_output import PDFOutputGenerator, PDFOutputWorker
from ui.styles import get_stylesheet
from ui.zoom_utils import calculate_wheel_zoom, ZOOM_MIN, ZOOM_MAX


class MovableTextItem(QGraphicsRectItem):
    """精修窗口中可拖拽/缩放的文字项组件。

    基于 QGraphicsRectItem 实现的文字项，支持在精修窗口中进行拖拽移动、
    四角缩放、选中高亮、右键菜单编辑和删除等交互操作。每个实例对应一个
    RefineTextItem 数据模型，界面上的位置和尺寸变更会同步反映到数据模型中。

    类属性:
        HANDLE_SIZE: 缩放手柄的像素尺寸，默认为 8。

    依赖:
        - PyQt5.QtWidgets.QGraphicsRectItem: 矩形图元基类
        - PyQt5.QtWidgets.QGraphicsTextItem: 内嵌的文字图元
        - models.data_models.RefineTextItem: 关联的文字数据模型
    """

    HANDLE_SIZE = 8

    def __init__(self, text_item_data: RefineTextItem, zoom_level: float):
        """初始化可拖拽文字项。

        根据文字数据模型的边界框和当前缩放级别创建矩形图元，设置内嵌文字、
        缩放手柄和选中状态的视觉样式。

        参数:
            text_item_data: 文字项数据模型，包含文字内容、边界框、页码等信息。
            zoom_level: 当前缩放级别，用于将原始坐标映射到场景坐标。

        调用关系:
            被 RefineWindow._render_page 和 RefineWindow._add_text_at 中创建实例。

        依赖:
            - models.data_models.RefineTextItem: 文字数据模型
        """
        bbox = text_item_data.bbox
        x1, y1, x2, y2 = bbox
        w = (x2 - x1) * zoom_level
        h = (y2 - y1) * zoom_level
        super().__init__(0, 0, w, h)
        self.setPos(x1 * zoom_level, y1 * zoom_level)
        self._data = text_item_data
        self._zoom_level = zoom_level
        self._handles = {}
        self._selected = False
        self._resize_handle = None
        self._start_rect = None
        self._start_pos = None
        self._start_item_pos = None
        self._moving = False
        self._move_start_scene_pos = None
        self._move_start_pos = None
        self._activated = False
        self.setFlag(QGraphicsRectItem.ItemIsMovable, False)
        self.setFlag(QGraphicsRectItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(False)
        self.setPen(QPen(Qt.NoPen))
        self._text_item = QGraphicsTextItem(text_item_data.text, self)
        font = QFont("Microsoft YaHei")
        font.setPixelSize(max(int(h), 1))
        self._text_item.setFont(font)
        self._text_item.setDefaultTextColor(Qt.red)
        self._text_item.document().setDocumentMargin(0)
        self._center_text()
        self._create_handles()
        self._update_selection_visual()

    def activate(self):
        """激活文字项的拖拽和悬停交互能力。

        启用后，文字项可被鼠标拖拽移动，并响应悬停事件。
        激活状态下用户可对文字项进行选中、拖拽、缩放等操作。

        调用关系:
            被 RefineWindow._on_drag_toggle 调用。
        """
        self._activated = True
        self.setFlag(QGraphicsRectItem.ItemIsMovable, False)
        self.setAcceptHoverEvents(True)

    def deactivate(self):
        """停用文字项的拖拽和悬停交互能力。

        停用后，文字项不可被鼠标拖拽移动，取消选中状态并更新视觉样式。
        通常在切换到其他工具模式时调用。

        调用关系:
            被 RefineWindow._on_hand_tool_toggle、RefineWindow._on_drag_toggle、
            RefineWindow._on_add_text_toggle 调用。
        """
        self._activated = False
        self.setFlag(QGraphicsRectItem.ItemIsMovable, False)
        self.setAcceptHoverEvents(False)
        self.setSelected(False)
        self._selected = False
        self._update_selection_visual()

    def _center_text(self):
        """将内嵌文字在矩形区域内居中显示。

        计算文字边界框与矩形区域的偏移量，将文字图元定位到矩形中心位置。

        调用关系:
            被 __init__、mouseMoveEvent、update_zoom 调用。
        """
        rect = self.rect()
        text_rect = self._text_item.boundingRect()
        x = (rect.width() - text_rect.width()) / 2
        y = (rect.height() - text_rect.height()) / 2
        self._text_item.setPos(x, y)

    def _calculate_max_font_size(self, text, frame_w, frame_h):
        """计算框内能容纳的最大字体大小。

        以框高为候选字号，用 QFontMetrics 测量字符宽高，
        超出框宽/框高时按比例缩小，最小 1px。

        参数:
            text: 字符文本
            frame_w: 框宽度（场景像素）
            frame_h: 框高度（场景像素）

        返回:
            QFont: 设置好 pixelSize 的字体对象
        """
        candidate = int(frame_h) if frame_h > 0 else 1
        font = QFont("Microsoft YaHei")
        font.setPixelSize(candidate)
        font.setStyleStrategy(QFont.PreferAntialias)
        fm = QFontMetrics(font)
        char_w = fm.horizontalAdvance(text) if text else 0
        char_h = fm.ascent() + fm.descent()
        if char_w > frame_w and frame_w > 0:
            candidate = int(candidate * frame_w / char_w)
        if char_h > frame_h and frame_h > 0:
            candidate = int(candidate * frame_h / char_h)
        candidate = max(candidate, 1)
        font.setPixelSize(candidate)
        return font

    def _create_handles(self):
        """创建四个角的缩放手柄图元。

        在矩形的左上、右上、左下、右下四个角各创建一个蓝色小矩形作为缩放手柄，
        初始状态下手柄不可见，仅在选中时显示。

        调用关系:
            被 __init__ 调用。
        """
        hs = self.HANDLE_SIZE
        for name in ("topLeft", "top", "topRight", "left", "right",
                     "bottomLeft", "bottom", "bottomRight"):
            handle = QGraphicsRectItem(self)
            handle.setPen(QPen(Qt.blue, 1))
            handle.setBrush(QBrush(Qt.blue))
            handle.setFlag(QGraphicsRectItem.ItemIsMovable, False)
            handle.setFlag(QGraphicsRectItem.ItemIsSelectable, False)
            handle.setVisible(False)
            handle.setData(0, name)
            self._handles[name] = handle
        self._position_handles()

    def _position_handles(self):
        """根据当前矩形位置更新四个缩放手柄的坐标。

        将手柄定位到矩形的四个角，每个手柄以角点为中心对称放置。

        调用关系:
            被 __init__、mouseMoveEvent、update_zoom 调用。
        """
        hs = self.HANDLE_SIZE
        half = hs / 2
        rect = self.rect()
        cx = rect.left() + rect.width() / 2
        cy = rect.top() + rect.height() / 2
        positions = {
            "topLeft": QPointF(rect.left() - half, rect.top() - half),
            "top": QPointF(cx - half, rect.top() - half),
            "topRight": QPointF(rect.right() - half, rect.top() - half),
            "left": QPointF(rect.left() - half, cy - half),
            "right": QPointF(rect.right() - half, cy - half),
            "bottomLeft": QPointF(rect.left() - half, rect.bottom() - half),
            "bottom": QPointF(cx - half, rect.bottom() - half),
            "bottomRight": QPointF(rect.right() - half, rect.bottom() - half),
        }
        for name, pos in positions.items():
            handle = self._handles[name]
            handle.setRect(QRectF(pos.x(), pos.y(), hs, hs))

    def _update_selection_visual(self):
        """根据选中状态更新文字项的视觉样式。

        选中时显示蓝色虚线边框和四个缩放手柄，未选中时隐藏边框和手柄。

        调用关系:
            被 setSelected、deactivate 调用。
        """
        if self._selected:
            self.setPen(QPen(Qt.blue, 1, Qt.DashLine))
            for handle in self._handles.values():
                handle.setVisible(True)
        else:
            self.setPen(QPen(Qt.NoPen))
            for handle in self._handles.values():
                handle.setVisible(False)

    def setSelected(self, selected: bool):
        """设置文字项的选中状态并更新视觉样式。

        参数:
            selected: 是否选中，True 为选中，False 为取消选中。

        调用关系:
            被 mousePressEvent、mouseDoubleClickEvent、RefineWindow.eventFilter 调用。
        """
        self._selected = selected
        self._update_selection_visual()

    def isSelected(self) -> bool:
        """判断文字项是否处于选中状态。

        返回:
            True 表示已选中，False 表示未选中。

        调用关系:
            被 keyPressEvent、RefineWindow.eventFilter 调用。
        """
        return self._selected

    def _handle_at(self, scene_pos: QPointF):
        """检测场景坐标下是否存在缩放手柄。

        遍历所有缩放手柄，判断给定的场景坐标是否落在某个可见手柄的范围内。

        参数:
            scene_pos: 场景坐标系下的检测点。

        返回:
            命中的手柄名称（如 "topLeft"），若无命中则返回 None。

        调用关系:
            被 mousePressEvent 调用。
        """
        for name, handle in self._handles.items():
            if handle.isVisible() and handle.contains(self.mapFromScene(scene_pos)):
                return name
        return None

    def mousePressEvent(self, event):
        """处理鼠标按下事件。

        未激活时忽略事件。激活状态下，若点击到缩放手柄则进入缩放模式；
        若点击到文字项本身则进入移动模式并选中该项，同时取消其他项的选中状态。

        参数:
            event: 鼠标按下事件对象。

        调用关系:
            由鼠标按下事件触发。
        """
        if not self._activated:
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            handle_name = self._handle_at(event.scenePos())
            if handle_name:
                self._resize_handle = handle_name
                self._start_rect = QRectF(self.rect())
                self._start_pos = QPointF(event.scenePos())
                self._start_item_pos = QPointF(self.pos())
                event.accept()
                return
            else:
                self._moving = True
                self._move_start_scene_pos = QPointF(event.scenePos())
                self._move_start_pos = QPointF(self.pos())
                self.setSelected(True)
                if self.scene():
                    for item in self.scene().items():
                        if isinstance(item, MovableTextItem) and item is not self:
                            item.setSelected(False)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """处理鼠标移动事件，实现缩放和移动功能。

        缩放模式：根据鼠标移动增量调整矩形尺寸和图元位置，
        保持 rect() 始终从 (0,0) 开始，同时更新字体大小、手柄位置和文字居中。
        移动模式：手动更新图元位置。

        参数:
            event: 鼠标移动事件对象。

        调用关系:
            由鼠标移动事件触发。
        """
        if self._resize_handle and self._start_rect and self._start_pos:
            delta = event.scenePos() - self._start_pos
            sr = self._start_rect
            start_pos = self._start_item_pos

            new_w = sr.width()
            new_h = sr.height()
            dx = 0.0
            dy = 0.0
            handle = self._resize_handle

            if handle in ("topLeft", "left", "bottomLeft"):
                new_w = sr.width() - delta.x()
                dx = delta.x()
            if handle in ("topRight", "right", "bottomRight"):
                new_w = sr.width() + delta.x()
            if handle in ("topLeft", "top", "topRight"):
                new_h = sr.height() - delta.y()
                dy = delta.y()
            if handle in ("bottomLeft", "bottom", "bottomRight"):
                new_h = sr.height() + delta.y()

            if new_w < 5:
                if handle in ("topLeft", "left", "bottomLeft"):
                    dx = sr.width() - 5
                new_w = 5
            if new_h < 5:
                if handle in ("topLeft", "top", "topRight"):
                    dy = sr.height() - 5
                new_h = 5

            self.setPos(start_pos.x() + dx, start_pos.y() + dy)
            self.setRect(QRectF(0, 0, new_w, new_h))

            font = self._calculate_max_font_size(self._data.text, new_w, new_h)
            self._text_item.setFont(font)
            self._position_handles()
            self._center_text()
            event.accept()
            return

        if self._moving:
            delta = event.scenePos() - self._move_start_scene_pos
            self.setPos(self._move_start_pos + delta)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """处理鼠标释放事件，结束缩放或移动操作。

        清除缩放状态或移动状态，完成一次交互。

        参数:
            event: 鼠标释放事件对象。

        调用关系:
            由鼠标释放事件触发。
        """
        if self._resize_handle:
            self._resize_handle = None
            self._start_rect = None
            self._start_pos = None
            self._start_item_pos = None
            event.accept()
            return
        if self._moving:
            self._moving = False
            self._move_start_scene_pos = None
            self._move_start_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    _HANDLE_CURSORS = {
        "topLeft": Qt.SizeFDiagCursor,
        "bottomRight": Qt.SizeFDiagCursor,
        "topRight": Qt.SizeBDiagCursor,
        "bottomLeft": Qt.SizeBDiagCursor,
        "top": Qt.SizeVerCursor,
        "bottom": Qt.SizeVerCursor,
        "left": Qt.SizeHorCursor,
        "right": Qt.SizeHorCursor,
    }

    def hoverMoveEvent(self, event):
        if not self._activated:
            super().hoverMoveEvent(event)
            return
        handle_name = self._handle_at(event.scenePos())
        if handle_name:
            self.setCursor(self._HANDLE_CURSORS.get(handle_name, Qt.ArrowCursor))
        else:
            self.setCursor(Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        """处理鼠标双击事件，选中文字项。

        未激活时忽略事件。激活状态下双击左键将文字项设为选中状态。

        参数:
            event: 鼠标双击事件对象。

        调用关系:
            由鼠标双击事件触发。
        """
        if not self._activated:
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self.setSelected(True)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """处理右键上下文菜单事件。

        未激活时忽略事件。激活状态下弹出右键菜单，提供"修改文字"和"删除"两个选项。
        选择"修改文字"将打开编辑对话框，选择"删除"将标记数据为忽略并隐藏图元。

        参数:
            event: 上下文菜单事件对象。

        调用关系:
            由右键菜单事件触发。
        """
        if not self._activated:
            event.ignore()
            return
        menu = QMenu()
        modify_action = menu.addAction("修改文字")
        delete_action = menu.addAction("删除")
        chosen = menu.exec(event.screenPos())
        if chosen == modify_action:
            self._edit_text()
        elif chosen == delete_action:
            self._data.ignored = True
            self.setVisible(False)

    def _edit_text(self):
        """打开文字编辑对话框，修改文字项的内容。

        弹出模态对话框，用户可输入新的文字内容。确认后更新数据模型和界面显示；
        若用户取消或输入为空则不做任何修改。

        调用关系:
            被 contextMenuEvent 调用。

        依赖:
            - PyQt5.QtWidgets.QDialog: 模态对话框
            - PyQt5.QtWidgets.QLineEdit: 文字输入框
        """
        dialog = QDialog()
        dialog.setWindowTitle("修改文字")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        prompt = QLabel("请输入新的文字内容：")
        layout.addWidget(prompt)
        line_edit = QLineEdit()
        line_edit.setText(self._data.text)
        line_edit.selectAll()
        layout.addWidget(line_edit)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        line_edit.returnPressed.connect(dialog.accept)
        if dialog.exec() != QDialog.Accepted:
            return
        new_text = line_edit.text().strip()
        if not new_text:
            return
        self._data.text = new_text
        self._text_item.setPlainText(new_text)

    def update_zoom(self, new_zoom: float):
        """根据新的缩放级别更新文字项的位置和尺寸。

        计算新旧缩放比例，按比例调整图元位置、矩形尺寸和字体大小，
        并重新定位手柄和居中文字。

        参数:
            new_zoom: 新的缩放级别。

        调用关系:
            被 RefineWindow._render_page 调用（缩放时需要）。

        依赖:
            - PyQt5.QtGui.QFont: 字体对象
        """
        old_zoom = self._zoom_level
        if old_zoom == 0:
            return
        ratio = new_zoom / old_zoom
        pos = self.pos()
        self.setPos(pos.x() * ratio, pos.y() * ratio)
        rect = self.rect()
        new_w = rect.width() * ratio
        new_h = rect.height() * ratio
        self.setRect(QRectF(0, 0, new_w, new_h))
        font = self._calculate_max_font_size(self._data.text, new_w, new_h)
        self._text_item.setFont(font)
        self._zoom_level = new_zoom
        self._position_handles()
        self._center_text()


class RefineWindow(QWidget):
    """精修阶段主窗口。

    提供页面浏览、缩放、文字项拖拽编辑、新增文字、输出校对结果等功能的
    集成交互界面。用户可在页面图像上对识别文字进行位置调整、内容修改、
    删除和新增操作，最终将校对结果输出为 PDF 文件。

    信号:
        finished_signal: 精修完成信号，无参数，通知主窗口精修流程结束。
        save_signal: 保存信号，参数为 (corrected_chars, page_images, output_path)，
            携带校对后的字符列表、页面图像列表和输出文件路径。

    依赖:
        - PyQt5.QtWidgets.QWidget: 窗口基类
        - PyQt5.QtWidgets.QGraphicsView / QGraphicsScene: 图形视图框架
        - models.data_models.RefineTextItem, CorrectedChar, LineSlice: 数据模型
        - ui.styles.get_stylesheet: 全局样式表
    """

    finished_signal = pyqtSignal()
    output_complete_signal = pyqtSignal(str, str)
    back_signal = pyqtSignal()

    def __init__(self, page_lines: dict, page_images: list, parent=None):
        """初始化精修窗口。

        接收页面行数据和页面图像，初始化缩放级别、当前页码、交互模式等状态，
        将原始字符数据转换为精修文字项，并构建用户界面。

        参数:
            page_lines: 页面行数据字典，键为页码，值为 LineSlice 列表。
            page_images: 页面图像列表，元素为 PIL.Image 对象。
            parent: 父窗口对象，默认为 None。

        调用关系:
            被 MainWindow._on_vertical_finished 中创建实例。

        依赖:
            - models.data_models.RefineTextItem: 精修文字项数据模型
            - ui.styles.get_stylesheet: 全局样式表
        """
        super().__init__(parent)
        self.page_lines = page_lines
        self.page_images = page_images
        self.zoom_level = 1.0
        self.current_page = 0
        self.total_pages = len(page_images)
        self.page_items = {}
        self._drag_mode = False
        self._add_text_mode = False
        self._selected_item = None
        self._first_render = True
        self._pixmap_cache = {}
        self._output_worker = None
        self._convert_chars()
        self._init_ui()

    def _convert_chars(self):
        """将页面行数据中的字符信息转换为精修文字项数据。

        遍历所有页面的行数据，提取每个字符的文字内容和边界框，
        创建 RefineTextItem 实例并按页码归类存储到 page_items 中。
        跳过已忽略的行和无效的字符数据。

        调用关系:
            被 __init__ 调用。

        依赖:
            - models.data_models.RefineTextItem: 精修文字项数据模型
            - models.data_models.LineSlice: 行切片数据模型
        """
        for page_num, lines in self.page_lines.items():
            if page_num not in self.page_items:
                self.page_items[page_num] = []
            for ls in lines:
                if hasattr(ls, "_ignored") and ls._ignored:
                    continue
                for char_data in ls.chars:
                    text = char_data.get("text", "")
                    if not text:
                        continue
                    bbox = char_data.get("bbox", [0, 0, 0, 0])
                    if len(bbox) < 4:
                        continue
                    font_size = bbox[3] - bbox[1]
                    item = RefineTextItem(
                        text=text,
                        bbox=list(bbox),
                        page_num=ls.page_num,
                        font_size=font_size,
                        ignored=False,
                    )
                    self.page_items[page_num].append(item)

    def _init_ui(self):
        """构建精修窗口的用户界面。

        创建工具栏（翻页、缩放、工具切换、输出按钮）和图形视图区域，
        设置事件过滤器和右键菜单策略，完成首次页面渲染。

        调用关系:
            被 __init__ 调用。

        依赖:
            - ui.styles.get_stylesheet: 全局样式表
            - MovableTextItem: 精修文字项组件
        """
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.setStyleSheet(get_stylesheet())
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
        self.page_spin.valueChanged.connect(self._on_goto_page)
        toolbar.addWidget(self.page_spin)

        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self._on_next_page)
        toolbar.addWidget(self.next_btn)

        toolbar.addSeparator()

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

        toolbar.addSeparator()

        self.hand_btn = QPushButton("手型工具")
        self.hand_btn.setCheckable(True)
        self.hand_btn.clicked.connect(self._on_hand_tool_toggle)
        toolbar.addWidget(self.hand_btn)

        self.drag_btn = QPushButton("拖拽")
        self.drag_btn.setCheckable(True)
        self.drag_btn.clicked.connect(self._on_drag_toggle)
        toolbar.addWidget(self.drag_btn)

        self.add_text_btn = QPushButton("新增文字")
        self.add_text_btn.setCheckable(True)
        self.add_text_btn.clicked.connect(self._on_add_text_toggle)
        toolbar.addWidget(self.add_text_btn)

        toolbar.addSeparator()

        self.output_btn = QPushButton("输出")
        self.output_btn.clicked.connect(self._on_output)
        toolbar.addWidget(self.output_btn)

        self.finish_btn = QPushButton("确认完成")
        self.finish_btn.setStyleSheet(
            "QPushButton { background-color: #198754; color: white; "
            "min-height: 28px; padding: 4px 12px; border: none; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background-color: #157347; }"
        )
        self.finish_btn.clicked.connect(self._on_finish_confirm)
        toolbar.addWidget(self.finish_btn)

        main_layout.addWidget(toolbar)

        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(Qt.white)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view.setViewportUpdateMode(
            QGraphicsView.SmartViewportUpdate
        )
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.viewport().installEventFilter(self)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        main_layout.addWidget(self.view, 1)

        self._render_page()

    def _render_page(self):
        """渲染当前页面的图像和文字项到场景中。

        清空场景后，根据当前页码和缩放级别绘制页面背景图像（带缓存），
        然后创建当前页面的所有 MovableTextItem 文字项。首次渲染时自动
        延迟调用适合宽度功能。

        调用关系:
            被 _on_prev_page、_on_next_page、_on_goto_page、_on_zoom_in、
            _on_zoom_out、_on_fit_width 调用。

        依赖:
            - MovableTextItem: 精修文字项组件
            - _pil_to_pixmap: PIL 图像转 QPixmap 工具方法
        """
        self.scene.clear()
        self._selected_item = None
        if self.page_images and self.current_page < len(self.page_images):
            img = self.page_images[self.current_page]
            cache_key = (self.current_page, self.zoom_level)
            if cache_key in self._pixmap_cache:
                scaled_pixmap = self._pixmap_cache[cache_key]
            else:
                pixmap = self._pil_to_pixmap(img)
                scaled_pixmap = pixmap.scaled(
                    int(img.width * self.zoom_level),
                    int(img.height * self.zoom_level),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self._pixmap_cache = {cache_key: scaled_pixmap}
            bg_item = QGraphicsPixmapItem(scaled_pixmap)
            bg_item.setZValue(0)
            self.scene.addItem(bg_item)
            self.scene.setSceneRect(
                QRectF(0, 0, img.width * self.zoom_level, img.height * self.zoom_level)
            )
        else:
            self.scene.setSceneRect(QRectF(0, 0, 800, 1000))

        items = self.page_items.get(self.current_page, [])
        for text_item_data in items:
            if text_item_data.ignored:
                continue
            movable = MovableTextItem(text_item_data, self.zoom_level)
            movable.setZValue(1)
            if self._drag_mode:
                movable.activate()
            self.scene.addItem(movable)

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

    def _sync_current_page(self):
        """将场景中文字项的位置和内容同步回数据模型。

        遍历场景中所有 MovableTextItem，根据其当前场景坐标和缩放级别
        反算出原始坐标系下的边界框，并更新关联的 RefineTextItem 数据模型
        的 bbox、text 和 font_size 字段。

        调用关系:
            被 _on_prev_page、_on_next_page、_on_goto_page、_on_zoom_in、
            _on_zoom_out、_on_fit_width、_on_output 调用。
        """
        for item in self.scene.items():
            if isinstance(item, MovableTextItem):
                data = item._data
                pos = item.pos()
                rect = item.rect()
                data.bbox = [
                    pos.x() / item._zoom_level,
                    pos.y() / item._zoom_level,
                    (pos.x() + rect.width()) / item._zoom_level,
                    (pos.y() + rect.height()) / item._zoom_level,
                ]
                data.text = item._text_item.toPlainText()
                data.font_size = rect.height() / item._zoom_level

    def _on_hand_tool_toggle(self):
        """处理手型工具按钮的切换事件。

        激活时关闭拖拽和新增文字模式，停用所有文字项的交互能力，
        将视图切换为滚动拖拽模式并显示抓手光标。取消时恢复默认模式。

        调用关系:
            由 hand_btn.clicked 信号触发。
        """
        if self.hand_btn.isChecked():
            self._drag_mode = False
            self._add_text_mode = False
            self.drag_btn.setChecked(False)
            self.add_text_btn.setChecked(False)
            for item in self.scene.items():
                if isinstance(item, MovableTextItem):
                    item.deactivate()
            self.view.setDragMode(QGraphicsView.ScrollHandDrag)
            self.view.setCursor(Qt.OpenHandCursor)
        else:
            self.view.setDragMode(QGraphicsView.NoDrag)
            self.view.setCursor(Qt.ArrowCursor)

    def _on_drag_toggle(self):
        """处理拖拽按钮的切换事件。

        激活时启用手型工具和新增文字模式，激活场景中所有文字项的交互能力，
        将视图设为无拖拽模式并显示箭头光标。取消时停用所有文字项并清除选中状态。

        调用关系:
            由 drag_btn.clicked 信号触发。
        """
        if self.drag_btn.isChecked():
            self._drag_mode = True
            self._add_text_mode = False
            self.hand_btn.setChecked(False)
            self.add_text_btn.setChecked(False)
            self.view.setDragMode(QGraphicsView.NoDrag)
            self.view.setCursor(Qt.ArrowCursor)
            for item in self.scene.items():
                if isinstance(item, MovableTextItem):
                    item.activate()
        else:
            self._drag_mode = False
            self._selected_item = None
            self.view.setCursor(Qt.ArrowCursor)
            for item in self.scene.items():
                if isinstance(item, MovableTextItem):
                    item.deactivate()

    def _on_add_text_toggle(self):
        """处理新增文字按钮的切换事件。

        激活时关闭手型和拖拽模式，停用所有文字项的交互能力，
        将视图设为无拖拽模式并显示十字光标。取消时恢复默认光标。

        调用关系:
            由 add_text_btn.clicked 信号触发。
        """
        if self.add_text_btn.isChecked():
            self._add_text_mode = True
            self._drag_mode = False
            self.hand_btn.setChecked(False)
            self.drag_btn.setChecked(False)
            self.view.setDragMode(QGraphicsView.NoDrag)
            self.view.setCursor(Qt.CrossCursor)
            for item in self.scene.items():
                if isinstance(item, MovableTextItem):
                    item.deactivate()
        else:
            self._add_text_mode = False
            self.view.setCursor(Qt.ArrowCursor)

    def eventFilter(self, obj, event):
        """事件过滤器，处理视图视口上的鼠标按下事件。

        在拖拽模式下，若鼠标左键点击的位置不在任何 MovableTextItem 上，
        则取消所有文字项的选中状态并清除选中项引用。

        参数:
            obj: 事件接收对象。
            event: 事件对象。

        返回:
            始终调用父类事件过滤器并返回其结果。

        调用关系:
            由 view.viewport 的事件过滤器触发。
        """
        if obj is self.view.viewport():
            new_zoom = calculate_wheel_zoom(event, self.zoom_level)
            if new_zoom is not None:
                self._sync_current_page()
                self.zoom_level = new_zoom
                self._render_page()
                return True
            if isinstance(event, QWheelEvent):
                v_bar = self.view.verticalScrollBar()
                delta = event.angleDelta().y()
                if delta > 0 and v_bar.value() == v_bar.minimum():
                    if self.current_page > 0:
                        self._sync_current_page()
                        self.current_page -= 1
                        self._render_page()
                        QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                            self.view.verticalScrollBar().maximum()))
                    return True
                elif delta < 0 and v_bar.value() == v_bar.maximum():
                    if self.current_page < self.total_pages - 1:
                        self._sync_current_page()
                        self.current_page += 1
                        self._render_page()
                        QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                            self.view.verticalScrollBar().minimum()))
                    return True
            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton and self._drag_mode:
                    scene_pos = self.view.mapToScene(event.pos())
                    item = self.scene.itemAt(scene_pos, self.view.transform())
                    if isinstance(item, QGraphicsTextItem) and isinstance(item.parentItem(), MovableTextItem):
                        item = item.parentItem()
                    if not isinstance(item, MovableTextItem):
                        for it in self.scene.items():
                            if isinstance(it, MovableTextItem):
                                it.setSelected(False)
                        self._selected_item = None
        return super().eventFilter(obj, event)

    def _on_context_menu(self, pos):
        """处理视图的右键上下文菜单请求。

        在拖拽模式下，若右键点击位置在已有文字项上，则弹出菜单
        提供"修改文字"和"删除"选项。在新增文字模式下，若右键点击
        位置不在已有文字项上，则弹出菜单提供"添加文字"选项。

        参数:
            pos: 视口坐标系下的右键点击位置。

        调用关系:
            由 view.customContextMenuRequested 信号触发。
        """
        scene_pos = self.view.mapToScene(pos)
        item = self.scene.itemAt(scene_pos, self.view.transform())
        if isinstance(item, QGraphicsTextItem) and isinstance(item.parentItem(), MovableTextItem):
            item = item.parentItem()
        if isinstance(item, MovableTextItem):
            if self._drag_mode:
                menu = QMenu(self)
                modify_action = menu.addAction("修改文字")
                delete_action = menu.addAction("删除")
                chosen = menu.exec(self.view.mapToGlobal(pos))
                if chosen == modify_action:
                    item._edit_text()
                elif chosen == delete_action:
                    item._data.ignored = True
                    item.setVisible(False)
                    item.setSelected(False)
                    self._selected_item = None
            return
        if self._add_text_mode:
            menu = QMenu(self)
            add_action = menu.addAction("添加文字")
            chosen = menu.exec(self.view.mapToGlobal(pos))
            if chosen == add_action:
                self._add_text_at(scene_pos)

    def _add_text_at(self, scene_pos: QPointF):
        """在指定场景位置添加新的文字项。

        弹出对话框让用户输入文字，确认后根据当前页面的平均字体大小
        计算新文字项的边界框，为每个字符创建独立的 RefineTextItem 数据模型
        和 MovableTextItem 图元并添加到场景中。第一个字摆在输入位置，
        之后的字按序往右侧排列，每个字不重叠。

        参数:
            scene_pos: 场景坐标系下的插入位置。

        调用关系:
            被 _on_context_menu 调用。

        依赖:
            - models.data_models.RefineTextItem: 精修文字项数据模型
            - MovableTextItem: 精修文字项组件
            - _get_avg_font_size: 获取当前页面平均字体大小
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("添加文字")
        dialog.setMinimumWidth(300)
        layout = QVBoxLayout(dialog)
        prompt = QLabel("请输入文字：")
        layout.addWidget(prompt)
        line_edit = QLineEdit()
        layout.addWidget(line_edit)
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        line_edit.returnPressed.connect(dialog.accept)
        if dialog.exec() != QDialog.Accepted:
            return
        new_text = line_edit.text().strip()
        if not new_text:
            return
        avg_font_size = self._get_avg_font_size()
        base_x = scene_pos.x() / self.zoom_level
        base_y = scene_pos.y() / self.zoom_level
        h = avg_font_size
        w = avg_font_size
        if self.current_page not in self.page_items:
            self.page_items[self.current_page] = []
        for i, ch in enumerate(new_text):
            char_x = base_x + i * w
            new_item = RefineTextItem(
                text=ch,
                bbox=[char_x, base_y, char_x + w, base_y + h],
                page_num=self.current_page,
                font_size=h,
                ignored=False,
            )
            self.page_items[self.current_page].append(new_item)
            movable = MovableTextItem(new_item, self.zoom_level)
            movable.setZValue(1)
            if self._drag_mode:
                movable.activate()
            self.scene.addItem(movable)

    def _get_avg_font_size(self) -> float:
        """计算当前页面未忽略文字项的平均字体大小。

        遍历当前页面的所有文字项数据，统计未忽略项的字体大小总和与数量，
        计算平均值。若无有效文字项则返回默认值 20.0。

        返回:
            当前页面未忽略文字项的平均字体大小，默认 20.0。

        调用关系:
            被 _add_text_at 调用。
        """
        items = self.page_items.get(self.current_page, [])
        if not items:
            return 20.0
        total = sum(it.font_size for it in items if not it.ignored)
        count = sum(1 for it in items if not it.ignored)
        return total / count if count > 0 else 20.0

    def keyPressEvent(self, event):
        """处理键盘按键事件。

        在拖拽模式下，按下 Delete 键将删除当前选中的文字项（标记为忽略并隐藏）。
        其他按键事件交由父类处理。

        参数:
            event: 键盘按键事件对象。

        调用关系:
            由键盘事件触发（Delete 键删除选中项）。
        """
        if event.key() == Qt.Key_Delete and self._drag_mode:
            for item in self.scene.items():
                if isinstance(item, MovableTextItem) and item.isSelected():
                    item._data.ignored = True
                    item.setVisible(False)
                    item.setSelected(False)
                    self._selected_item = None
                    break
            return
        super().keyPressEvent(event)

    def _on_prev_page(self):
        """切换到上一页。

        同步当前页面数据后，将页码减一并重新渲染页面。
        若已在第一页则不执行操作。

        调用关系:
            由 prev_btn.clicked 信号触发。
        """
        if self.current_page > 0:
            self._sync_current_page()
            self.current_page -= 1
            self._render_page()

    def _on_next_page(self):
        """切换到下一页。

        同步当前页面数据后，将页码加一并重新渲染页面。
        若已在最后一页则不执行操作。

        调用关系:
            由 next_btn.clicked 信号触发。
        """
        if self.current_page < self.total_pages - 1:
            self._sync_current_page()
            self.current_page += 1
            self._render_page()

    def _on_goto_page(self, page_num: int):
        """跳转到指定页码。

        同步当前页面数据后，将页码设置为目标页并重新渲染页面。
        若目标页与当前页相同则不执行操作。

        参数:
            page_num: 目标页码（从 1 开始计数）。

        调用关系:
            由 page_spin.valueChanged 信号触发。
        """
        idx = page_num - 1
        if 0 <= idx < self.total_pages and idx != self.current_page:
            self._sync_current_page()
            self.current_page = idx
            self._render_page()

    def _on_zoom_input(self):
        """缩放输入框回车处理，修改缩放率。"""
        text = self.zoom_input.text().strip().rstrip('%')
        try:
            zoom_pct = int(text)
            if 10 <= zoom_pct <= 1000:
                self._sync_current_page()
                self.zoom_level = zoom_pct / 100
                self._render_page()
        except ValueError:
            pass
        self.zoom_input.setText(f"{int(self.zoom_level * 100)}%")

    def _on_zoom_in(self):
        if self.zoom_level < ZOOM_MAX:
            self._sync_current_page()
            self.zoom_level += 0.25
            self._render_page()

    def _on_zoom_out(self):
        if self.zoom_level > ZOOM_MIN:
            self._sync_current_page()
            self.zoom_level -= 0.25
            self._render_page()

    def _on_fit_width(self):
        """将页面缩放至适合视图宽度。

        根据视图视口宽度和当前页面图像宽度计算缩放级别，
        使页面图像恰好填满视图宽度（两侧各留 10 像素边距）。

        调用关系:
            由 fit_width_btn.clicked 信号和首次渲染触发。
        """
        if not self.page_images or self.current_page >= len(self.page_images):
            return
        view_width = self.view.viewport().width() - 20
        img_width = self.page_images[self.current_page].width
        if img_width > 0:
            self._sync_current_page()
            self.zoom_level = view_width / img_width
            self._render_page()

    def _on_fit_height(self):
        """将页面缩放至适合视图高度。"""
        if not self.page_images or self.current_page >= len(self.page_images):
            return
        view_height = self.view.viewport().height() - 20
        img_height = self.page_images[self.current_page].height
        if img_height > 0:
            self._sync_current_page()
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

    def _on_output(self):
        """处理输出按钮点击事件，保存校对结果。

        同步当前页面数据后，弹出文件保存对话框让用户选择输出基础路径，
        然后启动工作线程生成红色和透明两种文字颜色的PDF文件，
        同时显示进度条弹窗。

        调用关系:
            由 output_btn.clicked 信号触发。

        依赖:
            - _build_corrected_chars: 构建校对字符列表
            - _start_pdf_generation: 启动PDF生成工作线程
        """
        self._sync_current_page()
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存文件", "", "PDF 文件 (*.pdf);;所有文件 (*)"
        )
        if not output_path:
            return
        corrected_chars = self._build_corrected_chars()

        base, ext = os.path.splitext(output_path)
        red_path = f"{base}_红{ext}"
        transparent_path = f"{base}_透明{ext}"

        self._start_pdf_generation(
            corrected_chars, red_path, transparent_path, is_finish=False
        )

    def _build_corrected_chars(self) -> list:
        """构建所有页面的校对字符列表。

        按页码顺序遍历所有文字项数据，为每个项创建 CorrectedChar 实例，
        包含文字内容、边界框、页码和忽略状态。

        返回:
            CorrectedChar 实例列表，包含所有页面的校对字符数据。

        调用关系:
            被 _on_output 调用。

        依赖:
            - models.data_models.CorrectedChar: 校对字符数据模型
        """
        result = []
        for page_num in sorted(self.page_items.keys()):
            for item in self.page_items[page_num]:
                result.append(
                    CorrectedChar(
                        text=item.text,
                        bbox=list(item.bbox),
                        page_num=item.page_num,
                        ignored=item.ignored,
                    )
                )
        return result

    def _pil_to_pixmap(self, pil_image) -> QPixmap:
        """将 PIL 图像对象转换为 QPixmap。

        若图像模式不是 RGBA 则先进行转换，然后通过原始字节数据创建 QImage，
        再转换为 QPixmap 返回。若输入为 None 则返回空的 QPixmap。

        参数:
            pil_image: PIL.Image 图像对象，可为 None。

        返回:
            转换后的 QPixmap 对象，输入为 None 时返回空 QPixmap。

        调用关系:
            被 _render_page 调用。

        依赖:
            - PyQt5.QtGui.QImage: Qt 图像对象
            - PyQt5.QtGui.QPixmap: Qt 像素图对象
        """
        if pil_image is None:
            return QPixmap()
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")
        data = pil_image.tobytes("raw", "RGBA")
        qimage = QImage(
            data,
            pil_image.width,
            pil_image.height,
            QImage.Format_RGBA8888,
        )
        return QPixmap.fromImage(qimage)

    def _on_finish_confirm(self):
        """处理确认完成按钮点击事件。

        弹出确认对话框，用户确认后自动保存精修结果（弹出保存对话框，
        生成红色和透明两个PDF文件），同时显示进度条弹窗，
        生成完成后发射 finished_signal 信号通知主窗口返回画框阶段。

        调用关系:
            由 finish_btn.clicked 信号触发。

        依赖:
            - _sync_current_page: 同步当前页面数据
            - _build_corrected_chars: 构建校对字符列表
            - _start_pdf_generation: 启动PDF生成工作线程
        """
        reply = QMessageBox.question(
            self, "确认完成",
            "确认完成后将保存精修结果并返回画框页面。\n是否确认？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._sync_current_page()
            output_path, _ = QFileDialog.getSaveFileName(
                self, "保存文件", "", "PDF 文件 (*.pdf);;所有文件 (*)"
            )
            if output_path:
                corrected_chars = self._build_corrected_chars()
                base, ext = os.path.splitext(output_path)
                red_path = f"{base}_红{ext}"
                transparent_path = f"{base}_透明{ext}"
                self._start_pdf_generation(
                    corrected_chars, red_path, transparent_path, is_finish=True
                )
            else:
                self.finished_signal.emit()

    def _start_pdf_generation(self, corrected_chars, red_path, transparent_path,
                              is_finish=False):
        """启动PDF生成工作线程并显示进度条弹窗。

        创建 QProgressDialog 和 PDFOutputWorker，将工作线程的进度信号
        连接到进度条更新，生成完成后发射相应的完成信号。

        参数:
            corrected_chars: 校对后的字符对象列表。
            red_path: 红色文字版PDF的输出路径。
            transparent_path: 透明文字版PDF的输出路径。
            is_finish: 是否为确认完成操作，True 表示生成完成后
                还需发射 finished_signal 返回画框阶段。

        调用关系:
            被 _on_output 和 _on_finish_confirm 调用。

        依赖:
            - PDFOutputGenerator: PDF生成器实例
            - PDFOutputWorker: PDF生成工作线程
            - QProgressDialog: 进度条弹窗
        """
        progress_dialog = QProgressDialog("正在准备...", None, 0, 100, self)
        progress_dialog.setWindowTitle("正在生成PDF")
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)

        generator = PDFOutputGenerator()
        worker = PDFOutputWorker(
            generator, corrected_chars, self.page_images,
            red_path, transparent_path,
        )

        def on_progress(percent, desc):
            progress_dialog.setValue(percent)
            progress_dialog.setLabelText(desc)

        def on_finished():
            progress_dialog.setValue(100)
            progress_dialog.close()
            self.output_complete_signal.emit(red_path, transparent_path)
            if is_finish:
                self.finished_signal.emit()
            self._output_worker = None

        def on_error(err_msg):
            progress_dialog.close()
            QMessageBox.critical(self, "生成失败", f"PDF生成过程中出错：\n{err_msg}")
            self._output_worker = None

        worker.progress_signal.connect(on_progress)
        worker.finished_signal.connect(on_finished)
        worker.error_signal.connect(on_error)
        worker.finished_signal.connect(worker.deleteLater)
        worker.error_signal.connect(worker.deleteLater)

        self._output_worker = worker
        worker.start()

    def _on_back(self):
        """处理返回按钮点击事件，发射返回信号。

        调用关系:
            由 back_btn.clicked 信号触发，发射 back_signal。
        """
        self.back_signal.emit()

    def cleanup(self):
        """清理精修窗口资源。

        清空图形场景中的所有图元，释放相关资源。
        在精修流程结束后由主窗口调用。

        调用关系:
            被 MainWindow._on_refine_finished 调用。
        """
        self.scene.clear()