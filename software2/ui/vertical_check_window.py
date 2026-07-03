import traceback

from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QGridLayout,
    QLabel,
    QPushButton,
    QMenu,
    QDialog,
    QLineEdit,
    QGroupBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsPixmapItem,
    QStackedWidget,
    QSizePolicy,
    QRubberBand,
    QMessageBox,
    QCheckBox,
    QToolTip,
    QStyledItemDelegate,
    QStyle,
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize, QPoint, QEvent, QRect, QRectF, QPointF, QTimer
from PyQt5.QtGui import QPixmap, QImage, QPen, QBrush, QColor, QCursor, QTransform

from collections import OrderedDict

from models.data_models import CharSlice, flatten_bbox
from ui.styles import get_stylesheet


class PreviewGraphicsView(QGraphicsView):
    """支持无边界鼠标拖拽平移与 Ctrl+滚轮缩放的原图预览视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panning = False
        self._pan_start_pos = QPoint()
        self._pan_start_center = QPointF()
        self._pixmap_item = None
        self._rect_item = None
        self._pan_start_pixmap_pos = QPointF()
        self._min_zoom = 0.1
        self._max_zoom = 10.0
        # 蓝框交互状态
        self._highlighted_overlay = None
        self._overlay_interaction_enabled = False
        # 红框调整状态
        self._red_rect_selected = False
        self._resizing = False
        self._resize_handle = None
        self._resize_start_rect = None
        self._resize_start_pos = None
        self._resized_dirty = False
        self._resized_rect = None

        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setSceneRect(QRectF(-50000, -50000, 100000, 100000))

    def _hit_red_rect_handle(self, view_pos):
        """检测点击是否落在红框的某个调整手柄上(视图像素空间,非对称容差)。

        框外容差 margin_out(防止误点),框内容差 margin_in(更易点中手柄)。
        边中点平行方向用 margin_mid 对称容差。
        返回手柄标识字符串("tl"/"t"/"tr"/"l"/"r"/"bl"/"b"/"br")或 None。
        角优先于边。
        """
        if self._rect_item is None:
            return None
        scene_rect = self._rect_item.sceneBoundingRect()
        if scene_rect is None or not scene_rect.isValid():
            return None
        # 映射到 view 坐标(QPolygon),取包围矩形
        view_poly = self.mapFromScene(scene_rect)
        view_rect = view_poly.boundingRect()
        margin_out = 3   # 框外容差(防止误点)
        margin_in = 12   # 框内容差(更容易点中手柄)
        margin_mid = 6   # 边中点平行方向容差
        x = view_pos.x()
        y = view_pos.y()
        left = view_rect.left()
        right = view_rect.right()
        top = view_rect.top()
        bottom = view_rect.bottom()
        mid_x = view_rect.center().x()
        mid_y = view_rect.center().y()
        # 4 角优先(非对称区间:框外小,框内大)
        # left/top: 外侧为负,内侧为正;right/bottom: 外侧为正,内侧为负
        if (-margin_out <= (x - left) <= margin_in) and (-margin_out <= (y - top) <= margin_in):
            return "tl"
        if (-margin_in <= (x - right) <= margin_out) and (-margin_out <= (y - top) <= margin_in):
            return "tr"
        if (-margin_out <= (x - left) <= margin_in) and (-margin_in <= (y - bottom) <= margin_out):
            return "bl"
        if (-margin_in <= (x - right) <= margin_out) and (-margin_in <= (y - bottom) <= margin_out):
            return "br"
        # 4 边中点(垂直方向非对称,平行方向对称)
        if (-margin_out <= (y - top) <= margin_in) and abs(x - mid_x) <= margin_mid:
            return "t"
        if (-margin_in <= (y - bottom) <= margin_out) and abs(x - mid_x) <= margin_mid:
            return "b"
        if (-margin_out <= (x - left) <= margin_in) and abs(y - mid_y) <= margin_mid:
            return "l"
        if (-margin_in <= (x - right) <= margin_out) and abs(y - mid_y) <= margin_mid:
            return "r"
        return None

    def _pixmap_size(self):
        """返回当前 pixmap 的 (width, height),若无则 (0, 0)。"""
        if self._pixmap_item is None or self._pixmap_item.pixmap().isNull():
            return (0, 0)
        pm = self._pixmap_item.pixmap()
        return (pm.width(), pm.height())

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        # 优先级 1:红框边角调整(红框优先于蓝框,重叠区域归红框)
        if self._rect_item is not None:
            handle = self._hit_red_rect_handle(event.pos())
            if handle is not None:
                self._resizing = True
                self._resize_handle = handle
                self._resize_start_rect = QRectF(self._rect_item.rect())
                self._resize_start_pos = QPoint(event.pos())
                event.accept()
                return
            # 优先级 2:红框内部选中
            scene_pos = self.mapToScene(event.pos())
            view_poly = self.mapFromScene(self._rect_item.sceneBoundingRect())
            if view_poly.boundingRect().contains(event.pos()):
                self._red_rect_selected = True
                sel_pen = QPen(QColor("#ff0000"))
                sel_pen.setWidth(3)
                sel_pen.setCosmetic(True)
                self._rect_item.setPen(sel_pen)
                event.accept()
                return

        # 优先级 3:蓝框高亮(需勾选"显示其他字框")
        if self._overlay_interaction_enabled and self.scene() is not None:
            scene_pos = self.mapToScene(event.pos())
            item = self.scene().itemAt(scene_pos, self.transform())
            if item is not None and item.data(Qt.UserRole) is not None:
                # 命中蓝框:高亮该框
                if self._highlighted_overlay is not None and self._highlighted_overlay is not item:
                    blue_pen = QPen(QColor("#0d6efd"))
                    blue_pen.setWidth(1)
                    blue_pen.setCosmetic(True)
                    self._highlighted_overlay.setPen(blue_pen)
                hl_pen = QPen(QColor("#ff9500"))
                hl_pen.setWidth(2)
                hl_pen.setCosmetic(True)
                item.setPen(hl_pen)
                self._highlighted_overlay = item
                event.accept()
                return

        # 优先级 4:平移
        self._panning = True
        self._pan_start_pos = event.pos()
        if self._pixmap_item is not None:
            self._pan_start_pixmap_pos = QPointF(self._pixmap_item.pos())
        self.setCursor(QCursor(Qt.ClosedHandCursor))
        event.accept()

    def mouseMoveEvent(self, event):
        if self._resizing and self._rect_item is not None:
            delta = event.pos() - self._resize_start_pos
            scale = self.transform().m11()
            if scale == 0:
                event.accept()
                return
            local_dx = delta.x() / scale
            local_dy = delta.y() / scale
            start = self._resize_start_rect
            new_x = start.x()
            new_y = start.y()
            new_w = start.width()
            new_h = start.height()
            handle = self._resize_handle
            pm_w, pm_h = self._pixmap_size()
            min_size = 4.0
            if "l" in handle:
                new_x = start.x() + local_dx
                new_w = start.width() - local_dx
                if new_w < min_size:
                    new_x = start.right() - min_size
                    new_w = min_size
                if new_x < 0:
                    new_w = new_w + new_x
                    new_x = 0
            if "r" in handle:
                new_w = start.width() + local_dx
                if new_w < min_size:
                    new_w = min_size
                if pm_w > 0 and new_x + new_w > pm_w:
                    new_w = pm_w - new_x
            if "t" in handle:
                new_y = start.y() + local_dy
                new_h = start.height() - local_dy
                if new_h < min_size:
                    new_y = start.bottom() - min_size
                    new_h = min_size
                if new_y < 0:
                    new_h = new_h + new_y
                    new_y = 0
            if "b" in handle:
                new_h = start.height() + local_dy
                if new_h < min_size:
                    new_h = min_size
                if pm_h > 0 and new_y + new_h > pm_h:
                    new_h = pm_h - new_y
            self._rect_item.setRect(QRectF(new_x, new_y, max(min_size, new_w), max(min_size, new_h)))
            event.accept()
            return

        if self._panning:
            delta = event.pos() - self._pan_start_pos
            current_scale = self.transform().m11()
            if current_scale != 0 and self._pixmap_item is not None:
                dx_scene = delta.x() / current_scale
                dy_scene = delta.y() / current_scale
                self._pixmap_item.setPos(
                    self._pan_start_pixmap_pos.x() + dx_scene,
                    self._pan_start_pixmap_pos.y() + dy_scene,
                )
            event.accept()
        else:
            # 非拖拽状态:检测红框手柄/内部、设置 cursor、显示蓝框 tooltip
            handle = None
            in_red = False
            if self._rect_item is not None:
                handle = self._hit_red_rect_handle(event.pos())
                if handle is None:
                    view_poly = self.mapFromScene(self._rect_item.sceneBoundingRect())
                    if view_poly.boundingRect().contains(event.pos()):
                        in_red = True

            # cursor 切换(8 手柄 + 内部 + 默认)
            if handle in ("tl", "br"):
                self.setCursor(QCursor(Qt.SizeFDiagCursor))
            elif handle in ("tr", "bl"):
                self.setCursor(QCursor(Qt.SizeBDiagCursor))
            elif handle in ("l", "r"):
                self.setCursor(QCursor(Qt.SizeHorCursor))
            elif handle in ("t", "b"):
                self.setCursor(QCursor(Qt.SizeVerCursor))
            elif in_red:
                self.setCursor(QCursor(Qt.SizeAllCursor))
            else:
                self.unsetCursor()

            # 蓝框 tooltip 立即显示(仅当不在红框上,且勾选了"显示其他字框")
            if (handle is None and not in_red
                    and self._overlay_interaction_enabled
                    and self.scene() is not None):
                scene_pos = self.mapToScene(event.pos())
                item = self.scene().itemAt(scene_pos, self.transform())
                if item is not None and item.data(Qt.UserRole) is not None:
                    QToolTip.showText(event.globalPos(), str(item.data(Qt.UserRole)))

            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._resizing:
            self._resizing = False
            if self._rect_item is not None and self._resize_start_rect is not None:
                final_rect = self._rect_item.rect()
                if (abs(final_rect.x() - self._resize_start_rect.x()) > 0.5 or
                        abs(final_rect.y() - self._resize_start_rect.y()) > 0.5 or
                        abs(final_rect.width() - self._resize_start_rect.width()) > 0.5 or
                        abs(final_rect.height() - self._resize_start_rect.height()) > 0.5):
                    self._resized_dirty = True
                    self._resized_rect = QRectF(final_rect)
            self._resize_handle = None
            self._resize_start_rect = None
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                event.accept()
                return
            factor = 1.15 if delta > 0 else 0.87
            current_scale = self.transform().m11()
            new_scale = current_scale * factor
            if self._min_zoom <= new_scale <= self._max_zoom:
                self.scale(factor, factor)
            event.accept()
        else:
            event.accept()

    def fit_to_width(self):
        """将 pixmap 内容按视图宽度等比缩放，保持宽高比。"""
        if self._pixmap_item is None or self._pixmap_item.pixmap().isNull():
            return
        pixmap_w = self._pixmap_item.pixmap().width()
        viewport_w = self.viewport().width()
        if pixmap_w <= 0 or viewport_w <= 0:
            return
        factor = viewport_w / pixmap_w
        self.resetTransform()
        self.scale(factor, factor)

    def set_scene_pixmap(self, pixmap, rect_in_pixmap_coords, overlay_rects=None):
        """创建 pixmap_item 与作为其子项的 rect_item（红框）及叠加蓝框。

        参数:
            pixmap: 待显示的 QPixmap。
            rect_in_pixmap_coords: 红框在 pixmap 本地坐标系中的 QRectF。
            overlay_rects: 可选,叠加蓝框列表,每项为 (QRectF, char_text) 元组,
                用于显示同行其他字符的 bbox 与悬停提示。随 pixmap_item 清除自动回收。
        """
        # 清除旧 item
        if self._pixmap_item is not None:
            scene = self.scene()
            if scene is not None:
                scene.removeItem(self._pixmap_item)
        self._pixmap_item = None
        self._rect_item = None
        self._highlighted_overlay = None
        self._red_rect_selected = False
        self._resizing = False
        self._resize_handle = None

        if pixmap.isNull():
            return

        # 创建 pixmap_item，初始 pos 设为 (0, 0)
        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._pixmap_item.setPos(0, 0)
        scene = self.scene()
        if scene is not None:
            scene.addItem(self._pixmap_item)

        # 创建 rect_item 作为 pixmap_item 的子项，坐标相对 pixmap 本地
        if (rect_in_pixmap_coords.isValid() and
                rect_in_pixmap_coords.width() > 0 and
                rect_in_pixmap_coords.height() > 0):
            self._rect_item = QGraphicsRectItem(rect_in_pixmap_coords)
            pen = QPen(QColor("#dc3545"))
            pen.setWidth(2)
            pen.setCosmetic(True)
            self._rect_item.setPen(pen)
            self._rect_item.setBrush(QBrush(Qt.NoBrush))
            self._rect_item.setParentItem(self._pixmap_item)

        # 创建叠加蓝框(同行其他字符),作为 pixmap_item 子项
        if overlay_rects:
            blue_pen = QPen(QColor("#0d6efd"))
            blue_pen.setWidth(1)
            blue_pen.setCosmetic(True)
            for ov_item_data in overlay_rects:
                ov_rect, char_text = ov_item_data
                if (ov_rect.isValid() and
                        ov_rect.width() > 0 and
                        ov_rect.height() > 0):
                    ov_item = QGraphicsRectItem(ov_rect)
                    ov_item.setPen(blue_pen)
                    ov_item.setBrush(QBrush(Qt.NoBrush))
                    ov_item.setToolTip(char_text)
                    ov_item.setData(Qt.UserRole, char_text)
                    ov_item.setParentItem(self._pixmap_item)

    def center_on_rect(self, rect):
        """将指定矩形区域严格居中显示在视图中央，并缩放以适配视口。

        参数:
            rect: 需要居中的矩形区域（QRectF 或 QRect，scene 坐标）。
        """
        if rect is None or rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return
        viewport_w = self.viewport().width()
        viewport_h = self.viewport().height()
        if viewport_w <= 0 or viewport_h <= 0:
            return
        margin_factor = 1.4
        target_scale = min(
            viewport_w / (rect.width() * margin_factor),
            viewport_h / (rect.height() * margin_factor),
        )
        if target_scale <= 0:
            return
        target_scale = max(self._min_zoom, min(self._max_zoom, target_scale))
        self.setTransform(QTransform().scale(target_scale, target_scale))
        center = rect.center() if isinstance(rect, QRectF) else QPointF(rect.center())
        self.centerOn(center)


class SliceItemWidget(QWidget):
    """纵校窗口中的单个字符切片展示组件。

    信号:
        clicked(int, object): 当用户左键点击切片时发射，参数为切片索引和键盘修饰符。
        right_clicked(int): 当用户在右键菜单中选择"修改字符"时发射。
        delete_clicked(int): 当用户在右键菜单中选择"删除"时发射。
        modifyRequested(int): 双击或回车触发的就地修改请求。
    """

    clicked = pyqtSignal(int, object)
    right_clicked = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)
    modifyRequested = pyqtSignal(int, str)

    def __init__(self, pixmap: QPixmap, index: int, warn_bg: bool = False,
                 char_text: str = "", selected: bool = False, parent=None):
        super().__init__(parent)
        self.index = index
        self.char_text = char_text
        self._selected = selected
        self._warn_bg = warn_bg
        self.setFixedSize(90, 90)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

        # 绝对定位:图像满铺,输入框浮在右下角
        self.image_label = QLabel(self)
        self.image_label.setGeometry(0, 0, 90, 90)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("QLabel { background-color: transparent; }")
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                80, 80,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)
        else:
            self.image_label.setText("(无)")

        self.image_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.image_label.customContextMenuRequested.connect(self._show_context_menu)

        self._char_input = QLineEdit(self)
        self._char_input.setGeometry(63, 68, 22, 18)
        self._char_input.setAlignment(Qt.AlignRight)
        self._char_input.setText(char_text)
        self._char_input.setStyleSheet(
            "QLineEdit { background-color: rgba(255,255,255,200); "
            "border: 1px solid #0D6EFD; border-radius: 2px; "
            "font-size: 12px; padding: 0px 2px; }"
        )
        self._char_input.returnPressed.connect(self._on_edit_finished)
        self._char_input.editingFinished.connect(self._on_edit_finished)

        self._update_style()

    def _update_style(self):
        """根据当前状态切换 QSS 样式（state 属性切换模式）。"""
        if self._selected:
            self.setProperty("state", "selected")
        elif self._warn_bg:
            self.setProperty("state", "warn")
        else:
            self.setProperty("state", "normal")
        style = self.style()
        if style:
            style.unpolish(self)
            style.polish(self)
        self.update()

    def set_selected(self, selected: bool):
        """设置选中状态并刷新样式。"""
        if self._selected != selected:
            self._selected = selected
            self._update_style()

    def set_char_text(self, text: str):
        """更新字符文本并同步输入框显示。"""
        self.char_text = text
        self._char_input.setText(text)

    def set_pixmap(self, pixmap: QPixmap):
        """更新切片显示的图像(用于红框调整后刷新单个切片)。"""
        if pixmap.isNull():
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("(无)")
        else:
            scaled = pixmap.scaled(
                80, 80,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)
            self.image_label.setText("")  # 清除可能残留的"(无)"

    def _on_edit_finished(self):
        """完成编辑,发射修改信号(带新文字参数)。

        防重入:returnPressed 与 editingFinished 双触发时,
        第二次 new_text == self.char_text 自动跳过。
        """
        new_text = self._char_input.text().strip()
        if new_text and new_text != self.char_text:
            self.char_text = new_text
            self.modifyRequested.emit(self.index, new_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index, event.modifiers())
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        """将按键事件交给父窗口处理，阻止 scroll_area 消费方向键。

        SliceItemWidget 获得焦点后，方向键事件默认会传播到 scroll_area，
        被 QAbstractScrollArea.keyPressEvent 消费用于视口滚动，导致
        VerticalCheckWindow.keyPressEvent 收不到方向键导航切片。
        本方法将所有按键事件交给父窗口（VerticalCheckWindow）处理。
        """
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, '_navigate_selection'):
                event.accept()
                parent.keyPressEvent(event)
                return
            parent = parent.parent()
        super().keyPressEvent(event)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        modify_action = menu.addAction("修改字符")
        delete_action = menu.addAction("删除")
        action = menu.exec(self.image_label.mapToGlobal(pos))
        if action == modify_action:
            self.right_clicked.emit(self.index)
        elif action == delete_action:
            self.delete_clicked.emit(self.index)


class NoArrowListWidget(QListWidget):
    """不响应方向键的 QListWidget。

    方向键(↑/↓/←/→)被忽略并传播给父窗口，由主窗口的 keyPressEvent
    处理切片导航或 Ctrl+↑/↓ 字符集合跳转。防止点击列表条目后
    方向键误切换字符集合。
    """

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
            event.ignore()
        else:
            super().keyPressEvent(event)


class CharListDelegate(QStyledItemDelegate):
    """字符列表委托：为已检查条目绘制浅蓝底色。

    绕过 QSS ::item 规则对 setBackground 的覆盖，通过自定义绘制
    实现"已检查"条目的 #b3d9ff 底色。选中态由 QSS ::item:selected
    处理(#0D6EFD)，未选中且已检查时由本委托绘制浅蓝底色。

    数据角色:
        Qt.UserRole + 1: bool，True 表示已检查
    """

    CHECKED_ROLE = Qt.UserRole + 1

    def paint(self, painter, option, index):
        checked = index.data(self.CHECKED_ROLE) == True
        is_selected = bool(option.state & QStyle.State_Selected)

        if is_selected:
            # 选中态: 交由 QSS ::item:selected 处理(#0D6EFD + 白字)
            super().paint(painter, option, index)
        elif checked:
            # 已检查(非选中): 自绘浅蓝底色 + 黑字左对齐，绕过 QSS
            # 左右各 12px padding 匹配 QSS ::item { padding: 8px 12px }
            painter.save()
            painter.fillRect(option.rect, QColor("#b3d9ff"))
            painter.setPen(QColor("black"))
            painter.setFont(option.font)
            text = index.data(Qt.DisplayRole)
            text_rect = option.rect.adjusted(12, 0, -12, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.restore()
        else:
            # 默认态: 交由 QSS/style 处理
            super().paint(painter, option, index)


class VerticalCheckWindow(QWidget):
    """纵校阶段主窗口。"""

    finished_signal = pyqtSignal(dict, tuple)
    back_signal = pyqtSignal()

    _K_SLICE_SIZE = 90
    _K_SLICE_SPACING = 8
    _NAV_BTN_STYLE = (
        "QPushButton { background-color: #0D6EFD; color: white; "
        "min-height: 44px; min-width: 120px; padding: 10px 30px; "
        "border: none; border-radius: 6px; font-size: 14px; }"
        "QPushButton:hover { background-color: #0b5ed7; }"
    )

    def __init__(self, char_slices: dict, page_images: list, ocr_results: tuple = None, parent=None):
        super().__init__(parent)
        self.char_slices = char_slices
        self.page_images = page_images
        self.ocr_results = ocr_results if ocr_results is not None else ([], [])
        self._current_char_text = ""
        self._current_page = 0
        self._current_page_size = 100
        self._current_columns = 8
        self._current_rows = 8
        self._pixmap_cache = OrderedDict()
        self._max_cache_size = 2000
        self._line_preview_cache = OrderedDict()
        self._max_line_preview_cache = 100

        self._selected_indices = set()
        self._last_clicked_index = None
        self._current_preview_index = None
        # 当前预览的裁剪偏移(pixmap 本地→页面绝对坐标的偏移量)
        self._current_crop_offset = (0, 0)
        self._current_slice_widgets = {}
        self._pending_modifications = {}
        # 已检查过的字符集合(点击"下一步"后永久标记浅蓝底色)
        self._checked_chars = set()

        self._alt_selecting = False
        self._alt_select_origin = None

        self._relayout_debounce_timer = QTimer(self)
        self._relayout_debounce_timer.setSingleShot(True)
        self._relayout_debounce_timer.setInterval(50)
        self._relayout_debounce_timer.timeout.connect(self._relayout_now)

        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(get_stylesheet())
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(16, 16, 16, 16)

        left_group = QGroupBox("字符列表")
        left_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #dee2e6; "
            "border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }"
        )
        left_layout = QVBoxLayout(left_group)
        # 字符跳转输入框 + 确认按钮(原 back_btn 位置)
        jump_layout = QHBoxLayout()
        jump_layout.setContentsMargins(0, 0, 0, 0)
        self.jump_edit = QLineEdit()
        self.jump_edit.setPlaceholderText("跳转字符")
        self.jump_btn = QPushButton("确认")
        self.jump_btn.clicked.connect(self._on_jump_char)
        self.jump_edit.returnPressed.connect(self._on_jump_char)
        jump_layout.addWidget(self.jump_edit, 1)
        jump_layout.addWidget(self.jump_btn)
        left_layout.addLayout(jump_layout)
        self.label_list = NoArrowListWidget()
        self.label_list.setMinimumWidth(120)
        self.label_list.setMaximumWidth(200)
        self.label_list.setItemDelegate(CharListDelegate(self.label_list))
        self.label_list.currentItemChanged.connect(self._on_label_selected)
        self.label_list.setStyleSheet(
            "QListWidget { font-size: 20px; }"
            "QListWidget::item { padding: 8px 12px; min-height: 36px; }"
            "QListWidget::item:selected { background-color: #0D6EFD; color: white; }"
            "QListWidget::item:hover { background-color: #e7f1ff; color: black; }"
            "QListWidget::item:selected:hover { background-color: #e7f1ff; color: black; }"
        )
        left_layout.addWidget(self.label_list)
        main_layout.addWidget(left_group, 0)

        right_column_layout = QVBoxLayout()
        right_column_layout.setSpacing(12)

        preview_group = QGroupBox("原图预览")
        preview_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #dee2e6; "
            "border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }"
        )
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(4, 4, 4, 4)

        # 原图预览工具栏:显示其他字框复选框
        preview_toolbar = QHBoxLayout()
        preview_toolbar.setContentsMargins(0, 0, 0, 4)
        self.show_other_chars_cb = QCheckBox("显示其他字框")
        self.show_other_chars_cb.stateChanged.connect(self._on_overlay_toggle)
        preview_toolbar.addWidget(self.show_other_chars_cb)
        preview_toolbar.addStretch()
        preview_layout.addLayout(preview_toolbar)

        self.preview_stack = QStackedWidget()
        self.preview_stack.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )

        hint_page = QWidget()
        hint_layout = QVBoxLayout(hint_page)
        hint_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_hint_label = QLabel("请选择切片查看来源")
        self.preview_hint_label.setAlignment(Qt.AlignCenter)
        self.preview_hint_label.setStyleSheet(
            "QLabel { color: #6c757d; font-size: 14px; background-color: transparent; }"
        )
        hint_layout.addWidget(self.preview_hint_label)
        self.preview_stack.addWidget(hint_page)

        self.preview_view = PreviewGraphicsView()
        self.preview_view.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.preview_view.setMinimumHeight(150)
        self.preview_view.setStyleSheet(
            "QGraphicsView { background-color: #f8f9fa; border: 1px solid #dee2e6; }"
        )
        self.preview_scene = QGraphicsScene(self)
        self.preview_view.setScene(self.preview_scene)
        self.preview_stack.addWidget(self.preview_view)

        preview_layout.addWidget(self.preview_stack)
        right_column_layout.addWidget(preview_group, 3)

        right_group = QGroupBox("切片展示")
        right_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #dee2e6; "
            "border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }"
        )
        right_layout = QVBoxLayout(right_group)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.installEventFilter(self)
        # viewport 接收滚轮事件,需单独安装 eventFilter 实现翻页
        self.scroll_area.viewport().installEventFilter(self)
        self.scroll_content = QWidget()
        scroll_vlayout = QVBoxLayout(self.scroll_content)
        scroll_vlayout.setContentsMargins(0, 0, 0, 0)
        scroll_vlayout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid_container = QWidget()
        self.grid_container.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Preferred,
        )
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(self._K_SLICE_SPACING)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.grid_container.installEventFilter(self)
        scroll_vlayout.addWidget(self.grid_container)
        self.scroll_area.setWidget(self.scroll_content)
        right_layout.addWidget(self.scroll_area, 1)

        page_nav_layout = QHBoxLayout()
        self.prev_page_btn = QPushButton("上一页")
        self.prev_page_btn.clicked.connect(self._on_prev_page)
        self.page_info_label = QLabel("")
        self.page_info_label.setAlignment(Qt.AlignCenter)
        self.next_page_btn = QPushButton("下一页")
        self.next_page_btn.clicked.connect(self._on_next_page)
        page_nav_layout.addWidget(self.prev_page_btn)
        page_nav_layout.addStretch()
        page_nav_layout.addWidget(self.page_info_label)
        page_nav_layout.addStretch()
        page_nav_layout.addWidget(self.next_page_btn)
        right_layout.addLayout(page_nav_layout)

        bottom_layout = QHBoxLayout()
        self.prev_step_btn = QPushButton("上一步")
        self.prev_step_btn.setStyleSheet(self._NAV_BTN_STYLE)
        self.prev_step_btn.clicked.connect(self._on_prev_step)
        bottom_layout.addWidget(self.prev_step_btn)
        bottom_layout.addStretch()
        self.next_button = QPushButton("下一步")
        self.next_button.setStyleSheet(self._NAV_BTN_STYLE)
        self.next_button.clicked.connect(self._on_next_step)
        bottom_layout.addWidget(self.next_button)
        right_layout.addLayout(bottom_layout)

        right_column_layout.addWidget(right_group, 7)
        main_layout.addLayout(right_column_layout, 1)

        self._recalc_layout()
        self._refresh_label_list()

    def _recalc_layout(self):
        """根据 viewport 宽度动态计算网格列数、行数和每页容量。"""
        viewport_width = self.scroll_area.viewport().width()
        if viewport_width <= 0:
            return
        spacing = self.grid_layout.spacing()
        avail = viewport_width - 2
        cols = max(1, int((avail + spacing) / (self._K_SLICE_SIZE + spacing)))
        item_h = self._K_SLICE_SIZE + spacing
        viewport_height = self.scroll_area.viewport().height()
        rows = max(1, int(viewport_height / item_h)) if viewport_height > 0 else 1
        page_size = max(1, cols * rows)
        changed = (cols != self._current_columns or page_size != self._current_page_size)
        self._current_columns = cols
        self._current_rows = rows
        self._current_page_size = page_size
        if changed and self._current_char_text:
            total = len(self.char_slices.get(self._current_char_text, []))
            total_pages = max(1, (total + self._current_page_size - 1) // self._current_page_size)
            if self._current_page >= total_pages:
                self._current_page = total_pages - 1
            self._render_current_page()

    def _relayout_now(self):
        """防抖触发的重新布局。"""
        self._recalc_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_debounce_timer.start()

    def _on_label_selected(self, current, previous):
        if current is None:
            return
        try:
            # 焦点切换前提交红框拖拽修改
            self._commit_pending_red_box_resize()
            char_text = current.data(Qt.UserRole)

            # 切换字符组时，先 flush 旧字符组的待修改
            if char_text != self._current_char_text:
                self.label_list.blockSignals(True)
                self._flush_pending_modifications()
                self.label_list.blockSignals(False)

            # 在重建后的列表中重新选中目标
            self.label_list.blockSignals(True)
            found = False
            for i in range(self.label_list.count()):
                item = self.label_list.item(i)
                if item.data(Qt.UserRole) == char_text:
                    self.label_list.setCurrentItem(item)
                    found = True
                    break
            if not found and self.label_list.count() > 0:
                self.label_list.setCurrentRow(0)
                item = self.label_list.currentItem()
                if item:
                    char_text = item.data(Qt.UserRole)
            self.label_list.blockSignals(False)

            self._clear_line_preview()
            self._selected_indices.clear()
            self._last_clicked_index = None
            self._current_preview_index = None
            # 同一字符保留页码，切换才重置
            self._update_slice_display(char_text, char_text != self._current_char_text)
        except Exception:
            self.label_list.blockSignals(False)
            traceback.print_exc()

    def _update_slice_display(self, char_text: str, reset_page: bool = True):
        self._current_char_text = char_text
        if reset_page:
            self._current_page = 0
        else:
            slices = self.char_slices.get(char_text, [])
            total_pages = max(1, (len(slices) + self._current_page_size - 1) // self._current_page_size)
            if self._current_page >= total_pages:
                self._current_page = total_pages - 1
        self._selected_indices.clear()
        self._last_clicked_index = None
        self._pending_modifications.clear()
        self._render_current_page()
        self._update_nav_button_texts()
        # 默认选中第一个切片并显示原图预览
        slices = self.char_slices.get(char_text, [])
        if slices:
            first_idx = self._current_page * self._current_page_size
            if 0 <= first_idx < len(slices):
                self._selected_indices = {first_idx}
                self._last_clicked_index = first_idx
                self._refresh_slice_selection_visuals()
                self._preview_slice(first_idx)

    def _clear_line_preview(self):
        self.preview_scene.clear()
        self.preview_view._pixmap_item = None
        self.preview_view._rect_item = None
        self.preview_stack.setCurrentIndex(0)

    def _on_slice_clicked(self, slice_index: int, modifiers):
        """处理切片点击事件，支持 Shift/Ctrl 多选。"""
        try:
            # 焦点切换前提交红框拖拽修改
            self._commit_pending_red_box_resize()
            slices = self.char_slices.get(self._current_char_text, [])
            if slice_index < 0 or slice_index >= len(slices):
                return

            if modifiers & Qt.ControlModifier:
                if slice_index in self._selected_indices:
                    self._selected_indices.discard(slice_index)
                else:
                    self._selected_indices.add(slice_index)
            elif modifiers & Qt.ShiftModifier:
                if self._last_clicked_index is not None:
                    lo = min(self._last_clicked_index, slice_index)
                    hi = max(self._last_clicked_index, slice_index)
                    for i in range(lo, hi + 1):
                        self._selected_indices.add(i)
                else:
                    self._selected_indices.add(slice_index)
            else:
                self._selected_indices = {slice_index}

            self._last_clicked_index = slice_index
            self._refresh_slice_selection_visuals()
            self._preview_slice(slice_index)
        except Exception:
            traceback.print_exc()

    def _refresh_slice_selection_visuals(self):
        """刷新所有切片的选中状态视觉效果。"""
        for idx, widget in self._current_slice_widgets.items():
            widget.set_selected(idx in self._selected_indices)

    def _preview_slice(self, slice_index: int):
        """预览指定索引的切片。"""
        # 焦点切换前提交红框拖拽修改(防止 set_scene_pixmap 重建时丢弃调整结果)
        self._commit_pending_red_box_resize()
        slices = self.char_slices.get(self._current_char_text, [])
        if 0 <= slice_index < len(slices):
            self._current_preview_index = slice_index
            self._show_line_preview(slices[slice_index])

    def _show_line_preview(self, char_slice: CharSlice):
        """在顶部预览区显示选中切片所在 PDF 页面的矩形区域，并用红框标出该切片。

        矩形裁剪（2.2）、绝对坐标红框（2.3）、min/max 回退（2.4）。
        """
        try:
            self.preview_scene.clear()
            self.preview_view._pixmap_item = None
            self.preview_view._rect_item = None

            lines, chars = self.ocr_results
            line_box = None
            for line_data in lines:
                if (line_data.get("page_num") == char_slice.page_num and
                        line_data.get("line_id") == char_slice.line_id):
                    line_box = line_data.get("box")
                    break

            page_num = char_slice.page_num
            if page_num >= len(self.page_images):
                return

            page_image = self.page_images[page_num]
            img_w, img_h = page_image.size

            cx1, cy1, cx2, cy2 = char_slice.bbox

            # 复用横校 _make_slice_pixmap 算法:全页宽度,y 范围为行 bbox ± pad
            pad = 20
            if line_box is not None:
                line_flat = flatten_bbox(line_box)
                line_y1, line_y2 = line_flat[1], line_flat[3]
            else:
                # 回退:用字符 bbox 的 y 范围
                line_y1, line_y2 = cy1, cy2

            crop_x1 = 0
            crop_y1 = max(0, int(line_y1) - pad)
            crop_x2 = img_w
            crop_y2 = min(img_h, int(line_y2) + pad)

            if crop_y2 <= crop_y1:
                return

            # 记录当前裁剪偏移(供红框拖拽提交时还原页面绝对坐标)
            self._current_crop_offset = (crop_x1, crop_y1)

            cache_key = (page_num, crop_y1, crop_y2)
            if cache_key in self._line_preview_cache:
                strip_pixmap = self._line_preview_cache[cache_key]
                self._line_preview_cache.move_to_end(cache_key)
            else:
                strip_image = page_image.crop((crop_x1, crop_y1, crop_x2, crop_y2))
                strip_pixmap = self._pil_to_pixmap(strip_image)
                self._line_preview_cache[cache_key] = strip_pixmap
                if len(self._line_preview_cache) > self._max_line_preview_cache:
                    self._line_preview_cache.popitem(last=False)

            if strip_pixmap.isNull():
                return

            # 准备红框在 pixmap 本地坐标系的矩形
            rect_x = cx1 - crop_x1
            rect_y = cy1 - crop_y1
            rect_w = max(1, cx2 - cx1)
            rect_h = max(1, cy2 - cy1)

            min_display = 16
            if rect_w < min_display or rect_h < min_display:
                center_x = rect_x + rect_w / 2
                center_y = rect_y + rect_h / 2
                rect_w = max(rect_w, min_display)
                rect_h = max(rect_h, min_display)
                rect_x = center_x - rect_w / 2
                rect_y = center_y - rect_h / 2

            rect_in_pixmap = QRectF(rect_x, rect_y, rect_w, rect_h)

            # 收集同行其他字符的蓝框(若复选框已勾选),每项 (rect, char_text)
            overlay_rects = None
            if self.show_other_chars_cb.isChecked():
                overlay_rects = []
                for char_data in chars:
                    if (char_data.get("page_num") == char_slice.page_num and
                            char_data.get("line_id") == char_slice.line_id and
                            char_data.get("char_id") != char_slice.char_id):
                        ov_bbox = flatten_bbox(char_data.get("box", [0, 0, 0, 0]))
                        ox = ov_bbox[0] - crop_x1
                        oy = ov_bbox[1] - crop_y1
                        ow = max(1, ov_bbox[2] - ov_bbox[0])
                        oh = max(1, ov_bbox[3] - ov_bbox[1])
                        ov_text = char_data.get("char", "")
                        overlay_rects.append((QRectF(ox, oy, ow, oh), ov_text))

            self.preview_stack.setCurrentIndex(1)
            self.preview_view.set_scene_pixmap(strip_pixmap, rect_in_pixmap, overlay_rects)

            # 居中: 使用 rect_item 的 sceneBoundingRect (反映 pixmap_item 的 pos 偏移)
            if self.preview_view._rect_item is not None:
                self.preview_view.center_on_rect(self.preview_view._rect_item.sceneBoundingRect())
        except Exception:
            traceback.print_exc()

    def _on_overlay_toggle(self, state):
        """复选框状态变化时重新渲染当前预览,以显示/隐藏蓝框叠加。"""
        try:
            self.preview_view._overlay_interaction_enabled = bool(state)
            if self._current_preview_index is not None:
                self._preview_slice(self._current_preview_index)
        except Exception:
            traceback.print_exc()

    def _compute_low_score_threshold(self, slices: list) -> float:
        if not slices:
            return -1.0
        scores = sorted(s.score for s in slices)
        threshold_index = max(0, int(len(scores) * 0.1) - 1)
        if len(scores) < 10:
            threshold_index = 0
        return scores[threshold_index]

    def _render_current_page(self):
        """渲染当前页的切片图像到网格布局中。"""
        try:
            for i in reversed(range(self.grid_layout.count())):
                widget = self.grid_layout.itemAt(i).widget()
                if widget is not None:
                    widget.deleteLater()
            self._current_slice_widgets.clear()

            slices = self.char_slices.get(self._current_char_text, [])
            total = len(slices)
            total_pages = max(1, (total + self._current_page_size - 1) // self._current_page_size)

            start = self._current_page * self._current_page_size
            end = min(start + self._current_page_size, total)
            page_slices = slices[start:end]

            low_score_threshold = self._compute_low_score_threshold(slices)

            cols = self._current_columns
            for page_idx, char_slice in enumerate(page_slices):
                global_idx = start + page_idx
                cache_key = (self._current_char_text, global_idx)
                if cache_key in self._pixmap_cache:
                    pixmap = self._pixmap_cache[cache_key]
                    self._pixmap_cache.move_to_end(cache_key)
                else:
                    pixmap = self._pil_to_pixmap(char_slice.image) if char_slice.image else QPixmap()
                    self._pixmap_cache[cache_key] = pixmap
                    if len(self._pixmap_cache) > self._max_cache_size:
                        self._pixmap_cache.popitem(last=False)

                warn_bg = char_slice.score <= low_score_threshold
                is_selected = global_idx in self._selected_indices
                item_widget = SliceItemWidget(
                    pixmap, global_idx, warn_bg=warn_bg,
                    char_text=self._current_char_text, selected=is_selected,
                )
                item_widget.clicked.connect(self._on_slice_clicked)
                item_widget.right_clicked.connect(self._on_relocate)
                item_widget.delete_clicked.connect(self._on_delete_slice)
                item_widget.modifyRequested.connect(self._on_slice_modify_requested)
                row = page_idx // cols
                col = page_idx % cols
                self.grid_layout.addWidget(item_widget, row, col)
                self._current_slice_widgets[global_idx] = item_widget

            self.page_info_label.setText(
                f"第 {self._current_page + 1}/{total_pages} 页，共 {total} 个"
            )
            self.prev_page_btn.setEnabled(self._current_page > 0)
            self.next_page_btn.setEnabled(self._current_page < total_pages - 1)
        except Exception:
            traceback.print_exc()

    def _on_slice_modify_requested(self, slice_index: int, new_text: str):
        """处理就地修改请求(右下角输入框编辑完成)。

        暂不移动切片,只更新 OCR results、记录挂起修改、刷新显示。
        若该切片在选中集中且选中数>1,连锁同步所有选中切片。
        实际移动在 _flush_pending_modifications(下一步)时进行。
        """
        try:
            current_char = self._current_char_text
            slices = self.char_slices.get(current_char, [])
            if slice_index < 0 or slice_index >= len(slices):
                return
            char_slice = slices[slice_index]
            # 更新 OCR results (复用修改字符的 JSON 更新逻辑)
            self._update_ocr_results_char(char_slice, new_text)
            # 记录挂起修改
            self._pending_modifications[slice_index] = new_text
            # 更新当前 widget 显示
            widget = self._current_slice_widgets.get(slice_index)
            if widget is not None:
                widget.set_char_text(new_text)
            # 连锁修改:若该切片在选中集中且选中数>1,同步所有选中切片
            if (slice_index in self._selected_indices
                    and len(self._selected_indices) > 1):
                for idx in list(self._selected_indices):
                    if idx == slice_index:
                        continue
                    if idx < 0 or idx >= len(slices):
                        continue
                    sub_slice = slices[idx]
                    self._update_ocr_results_char(sub_slice, new_text)
                    self._pending_modifications[idx] = new_text
                    sub_widget = self._current_slice_widgets.get(idx)
                    if sub_widget is not None:
                        sub_widget.set_char_text(new_text)
        except Exception:
            traceback.print_exc()

    def _apply_modify_to_selection(self, slice_index: int, new_text: str):
        """将修改应用到指定索引的切片(对话框方式立即移动)。

        供 _on_relocate 右键"修改字符"对话框使用,立即移动切片。
        """
        try:
            current_char = self._current_char_text
            slices = self.char_slices.get(current_char, [])
            if slice_index < 0 or slice_index >= len(slices):
                return
            char_slice = slices[slice_index]
            self._update_ocr_results_char(char_slice, new_text)
            self._move_slice_to_new_char(slice_index, new_text)
        except Exception:
            traceback.print_exc()

    def _move_slice_to_new_char(self, slice_index: int, new_text: str):
        """实际移动切片到新字符集合(在 flush 或对话框确认时调用)。"""
        try:
            current_char = self._current_char_text
            slices = self.char_slices.get(current_char, [])
            if slice_index < 0 or slice_index >= len(slices):
                return
            char_slice = slices[slice_index]

            keys_to_remove = [k for k in self._pixmap_cache
                              if k[0] in (current_char, new_text)]
            for k in keys_to_remove:
                del self._pixmap_cache[k]

            slices.pop(slice_index)
            char_slice.text = new_text

            if new_text not in self.char_slices:
                self.char_slices[new_text] = []
            self.char_slices[new_text].append(char_slice)

            if not slices:
                del self.char_slices[current_char]
        except Exception:
            traceback.print_exc()

    def _flush_pending_modifications(self):
        """批量应用所有挂起的修改(按索引降序处理以避免偏移问题)。

        若集合键发生变化(有删除或新增),刷新左侧导航栏。
        """
        if not self._pending_modifications:
            return
        # 记录 flush 前的集合键,用于检测变化
        old_keys = set(self.char_slices.keys())
        for idx in sorted(self._pending_modifications.keys(), reverse=True):
            new_text = self._pending_modifications[idx]
            self._move_slice_to_new_char(idx, new_text)
        self._pending_modifications.clear()
        # 若集合发生变化(有删除或新增),刷新导航栏
        if set(self.char_slices.keys()) != old_keys:
            self._refresh_label_list()

    def flush_current_pending(self):
        """公共方法：刷新当前字符组的挂起修改。

        被外部（如 main.py）在发射 finished_signal 之前调用，
        确保所有未提交的就地修改都被应用。
        """
        self._flush_pending_modifications()

    def _on_relocate(self, slice_index: int):
        """处理切片修改字符（重定位）操作，保留原有对话框方式。"""
        try:
            self._pending_modifications.clear()
            current_item = self.label_list.currentItem()
            if current_item is None:
                return
            current_char = current_item.data(Qt.UserRole)
            slices = self.char_slices.get(current_char, [])
            if slice_index < 0 or slice_index >= len(slices):
                return

            char_slice = slices[slice_index]

            dialog = QDialog(self)
            dialog.setWindowTitle("修改字符")
            dialog.setMinimumWidth(300)
            dialog_layout = QVBoxLayout(dialog)

            prompt = QLabel("请输入正确的文字内容：")
            dialog_layout.addWidget(prompt)

            line_edit = QLineEdit()
            line_edit.setText(current_char)
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
            if not new_text or new_text == current_char:
                return

            self._apply_modify_to_selection(slice_index, new_text)

            self._refresh_label_list()

            self.label_list.blockSignals(True)
            if current_char in self.char_slices:
                for i in range(self.label_list.count()):
                    item = self.label_list.item(i)
                    if item.data(Qt.UserRole) == current_char:
                        self.label_list.setCurrentItem(item)
                        break
                self._update_slice_display(current_char, reset_page=False)
            elif self.label_list.count() > 0:
                self.label_list.setCurrentRow(0)
            self.label_list.blockSignals(False)
        except Exception:
            self.label_list.blockSignals(False)
            traceback.print_exc()

    def _on_delete_slice(self, slice_index: int):
        """处理切片删除操作。"""
        try:
            self._pending_modifications.clear()
            current_item = self.label_list.currentItem()
            if current_item is None:
                return
            current_char = current_item.data(Qt.UserRole)
            original_row = self.label_list.currentRow()
            slices = self.char_slices.get(current_char, [])
            if slice_index < 0 or slice_index >= len(slices):
                return
            char_slice = slices[slice_index]
            self._update_ocr_results_char(char_slice, "")

            keys_to_remove = [k for k in self._pixmap_cache
                              if k[0] == current_char]
            for k in keys_to_remove:
                del self._pixmap_cache[k]

            slices.pop(slice_index)
            if not slices:
                del self.char_slices[current_char]
            self._refresh_label_list()

            self.label_list.blockSignals(True)
            if current_char in self.char_slices:
                for i in range(self.label_list.count()):
                    item = self.label_list.item(i)
                    if item.data(Qt.UserRole) == current_char:
                        self.label_list.setCurrentItem(item)
                        break
                self._update_slice_display(current_char, reset_page=False)
            elif self.label_list.count() > 0:
                # 集合已删光:跳转到原集合向下数的下一个(若已是最后则回上一个)
                target_row = min(original_row, self.label_list.count() - 1)
                self.label_list.setCurrentRow(target_row)
                current_item = self.label_list.currentItem()
                if current_item:
                    self._update_slice_display(current_item.data(Qt.UserRole))
            self.label_list.blockSignals(False)
        except Exception:
            self.label_list.blockSignals(False)
            traceback.print_exc()

    def _on_next_step(self):
        """处理"下一步"按钮点击事件。

        非最后一项:先 flush 当前字符组挂起修改(移动切片到新集合),
        再切换到下一个字符组。
        最后一项:flush + 发射 finished_signal。
        """
        try:
            # 焦点切换前提交红框拖拽修改
            self._commit_pending_red_box_resize()
            # 标记当前集合为"已检查"(永久浅蓝底色)
            if self._current_char_text:
                self._checked_chars.add(self._current_char_text)
                # 立即更新当前行 item 的 checked 标记(委托绘制浅蓝底色,绕过 QSS)
                current_row_now = self.label_list.currentRow()
                if 0 <= current_row_now < self.label_list.count():
                    checked_item = self.label_list.item(current_row_now)
                    if checked_item is not None:
                        checked_item.setData(CharListDelegate.CHECKED_ROLE, True)
                        # 触发委托重绘该 item
                        self.label_list.update(self.label_list.indexFromItem(checked_item))
            current_row = self.label_list.currentRow()
            if current_row < self.label_list.count() - 1:
                # 切换前 flush 当前字符组的挂起修改(移动切片到新集合)
                self._flush_pending_modifications()
                self.label_list.blockSignals(True)
                # flush 后列表可能缩短(原集合被撤销),加越界保护
                target_row = min(current_row + 1, self.label_list.count() - 1)
                self.label_list.setCurrentRow(target_row)
                self.label_list.blockSignals(False)
                new_item = self.label_list.currentItem()
                if new_item:
                    char_text = new_item.data(Qt.UserRole)
                    self._clear_line_preview()
                    self._selected_indices.clear()
                    self._last_clicked_index = None
                    self._current_preview_index = None
                    self._update_slice_display(char_text, reset_page=True)
            else:
                self.flush_current_pending()
                from PyQt5.QtWidgets import QApplication
                QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
                try:
                    self.finished_signal.emit(self.char_slices, self.ocr_results)
                finally:
                    QApplication.restoreOverrideCursor()
        except Exception:
            from PyQt5.QtWidgets import QApplication
            QApplication.restoreOverrideCursor()
            traceback.print_exc()

    def _refresh_label_list(self):
        """刷新左侧字符列表。"""
        self.label_list.currentItemChanged.disconnect(self._on_label_selected)
        self.label_list.blockSignals(True)
        self.label_list.clear()

        sorted_keys = sorted(self.char_slices.keys(), key=lambda k: ord(k[0]) if k else 0)
        for char_text in sorted_keys:
            item = QListWidgetItem(char_text)
            item.setData(Qt.UserRole, char_text)
            # 已检查标记: 委托据此绘制浅蓝底色(绕过 QSS ::item 覆盖)
            item.setData(CharListDelegate.CHECKED_ROLE, char_text in self._checked_chars)
            self.label_list.addItem(item)

        self.label_list.blockSignals(False)
        self.label_list.currentItemChanged.connect(self._on_label_selected)

        if self.label_list.count() > 0:
            self.label_list.setCurrentRow(0)
        self._update_nav_button_texts()

    def _pil_to_pixmap(self, pil_image) -> QPixmap:
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

    def eventFilter(self, obj, event):
        # 切片展示区滚轮: 翻页(不滚动)
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Wheel:
            delta = event.angleDelta().y()
            if delta > 0:
                self._on_prev_page()
            elif delta < 0:
                self._on_next_page()
            event.accept()
            return True

        if obj is self.scroll_area and event.type() == QEvent.Resize:
            self._relayout_debounce_timer.start()
            return False

        if obj is self.grid_container and event.type() == QEvent.MouseButtonPress:
            if (event.modifiers() & Qt.AltModifier and
                    event.button() == Qt.LeftButton):
                self._alt_selecting = True
                self._alt_select_origin = event.pos()
                return True
            # 非 Alt 修饰的左键点击:检查是否点击空白,若是则清空选中
            if event.button() == Qt.LeftButton:
                pos = event.pos()
                hit_widget = False
                for idx, widget in self._current_slice_widgets.items():
                    if widget.geometry().contains(pos):
                        hit_widget = True
                        break
                if not hit_widget:
                    self._selected_indices.clear()
                    self._last_clicked_index = None
                    self._refresh_slice_selection_visuals()

        if obj is self.grid_container and event.type() == QEvent.MouseMove:
            if self._alt_selecting and self._alt_select_origin is not None:
                current_pos = event.pos()
                origin = self._alt_select_origin
                rect = QRect(origin, current_pos).normalized()
                self._select_in_rect(rect)
                return True

        if obj is self.grid_container and event.type() == QEvent.MouseButtonRelease:
            if self._alt_selecting and event.button() == Qt.LeftButton:
                self._alt_selecting = False
                self._alt_select_origin = None
                return True

        return super().eventFilter(obj, event)

    def _select_in_rect(self, rect: QRect):
        """Alt+拖拽框选：将矩形区域内的切片加入选区。"""
        try:
            new_selection = set()
            for idx, widget in self._current_slice_widgets.items():
                widget_rect = widget.geometry()
                if rect.intersects(widget_rect):
                    new_selection.add(idx)
            if new_selection:
                self._selected_indices = new_selection
                self._refresh_slice_selection_visuals()
                if self._selected_indices:
                    first = min(self._selected_indices)
                    self._preview_slice(first)
        except Exception:
            traceback.print_exc()

    def _delete_selected(self):
        """删除所有选中的切片（Keyboard Delete 键）。"""
        if not self._selected_indices:
            return
        try:
            current_char = self._current_char_text
            original_row = self.label_list.currentRow()
            slices = self.char_slices.get(current_char, [])
            for idx in sorted(self._selected_indices, reverse=True):
                if 0 <= idx < len(slices):
                    char_slice = slices[idx]
                    self._update_ocr_results_char(char_slice, "")
            keys_to_remove = [k for k in self._pixmap_cache if k[0] == current_char]
            for k in keys_to_remove:
                del self._pixmap_cache[k]

            for idx in sorted(self._selected_indices, reverse=True):
                if 0 <= idx < len(slices):
                    slices.pop(idx)

            self._selected_indices.clear()
            self._last_clicked_index = None

            if not slices:
                del self.char_slices[current_char]

            self._refresh_label_list()

            if current_char in self.char_slices:
                for i in range(self.label_list.count()):
                    item = self.label_list.item(i)
                    if item.data(Qt.UserRole) == current_char:
                        self.label_list.setCurrentItem(item)
                        break
                self._update_slice_display(current_char, reset_page=False)
            elif self.label_list.count() > 0:
                # 集合已删光:跳转到原集合向下数的下一个(若已是最后则回上一个)
                target_row = min(original_row, self.label_list.count() - 1)
                self.label_list.setCurrentRow(target_row)
                current_item = self.label_list.currentItem()
                if current_item:
                    self._update_slice_display(current_item.data(Qt.UserRole))
        except Exception:
            traceback.print_exc()

    def _update_ocr_results_char(self, char_slice: CharSlice, new_text: str):
        lines, chars = self.ocr_results
        if not chars:
            return
        for char_data in chars:
            if (char_data.get("page_num") == char_slice.page_num and
                char_data.get("line_id") == char_slice.line_id and
                char_data.get("char_id") == char_slice.char_id):
                char_data["char"] = new_text
                break

    def _update_ocr_results_char_box(self, char_slice: CharSlice, new_bbox):
        """更新 ocr_results 中匹配字符的 box 字段为新的扁平 bbox。"""
        lines, chars = self.ocr_results
        if not chars:
            return
        for char_data in chars:
            if (char_data.get("page_num") == char_slice.page_num and
                char_data.get("line_id") == char_slice.line_id and
                char_data.get("char_id") == char_slice.char_id):
                char_data["box"] = list(new_bbox)
                break

    def _refresh_slice_widget(self, idx: int):
        """刷新指定索引切片的缩略图显示(若该切片在当前页可见)。

        用于红框拖拽提交后,立即更新网格中对应 widget 的图像,
        避免用户切页或切字符组才能看到新切片。
        """
        widget = self._current_slice_widgets.get(idx)
        if widget is None:
            return  # 切片不在当前页,无需刷新
        slices = self.char_slices.get(self._current_char_text, [])
        if idx < 0 or idx >= len(slices):
            return
        char_slice = slices[idx]
        pixmap = self._pil_to_pixmap(char_slice.image) if char_slice.image else QPixmap()
        widget.set_pixmap(pixmap)
        # 重新填充缓存,避免下次 _render_current_page 重复计算
        cache_key = (self._current_char_text, idx)
        self._pixmap_cache[cache_key] = pixmap
        self._pixmap_cache.move_to_end(cache_key)
        if len(self._pixmap_cache) > self._max_cache_size:
            self._pixmap_cache.popitem(last=False)

    def _commit_pending_red_box_resize(self):
        """焦点切换前提交红框拖拽修改:按新红框重新裁切切片并更新 JSON。

        红框 _resized_rect 为 pixmap 本地坐标(行裁剪图坐标系),
        叠加 _current_crop_offset 后还原为页面绝对坐标,据此重新裁切
        page_image 并更新 char_slice.image/bbox 与 ocr_results 的 box。
        """
        view = self.preview_view
        if not getattr(view, "_resized_dirty", False) or self._current_preview_index is None:
            return
        slices = self.char_slices.get(self._current_char_text, [])
        idx = self._current_preview_index
        if idx < 0 or idx >= len(slices):
            return
        char_slice = slices[idx]
        local_rect = view._resized_rect
        if local_rect is None or not local_rect.isValid():
            return
        crop_x1, crop_y1 = self._current_crop_offset
        new_x1 = local_rect.x() + crop_x1
        new_y1 = local_rect.y() + crop_y1
        new_x2 = local_rect.right() + crop_x1
        new_y2 = local_rect.bottom() + crop_y1

        page_num = char_slice.page_num
        if page_num >= len(self.page_images):
            return
        page_image = self.page_images[page_num]
        img_w, img_h = page_image.size
        # clamp 到页面图像边界
        new_x1 = max(0, min(new_x1, img_w))
        new_y1 = max(0, min(new_y1, img_h))
        new_x2 = max(0, min(new_x2, img_w))
        new_y2 = max(0, min(new_y2, img_h))
        if new_x2 <= new_x1 or new_y2 <= new_y1:
            return

        new_bbox = [new_x1, new_y1, new_x2, new_y2]
        try:
            char_slice.image = page_image.crop((new_x1, new_y1, new_x2, new_y2))
        except Exception:
            traceback.print_exc()
            return
        char_slice.bbox = list(new_bbox)
        self._update_ocr_results_char_box(char_slice, new_bbox)
        # 失效该切片的 pixmap 缓存,使下次渲染重新加载
        cache_key = (self._current_char_text, idx)
        self._pixmap_cache.pop(cache_key, None)
        # 立即刷新该切片的网格缩略图显示(若在当前页可见)
        self._refresh_slice_widget(idx)
        # 清除脏状态,避免重复提交
        view._resized_dirty = False
        view._resized_rect = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._on_next_step()
        elif event.key() == Qt.Key_Delete:
            self._delete_selected()
        elif event.key() == Qt.Key_Escape:
            for child in self.children():
                if isinstance(child, QDialog) and child.isVisible():
                    child.reject()
                    return
        elif (event.modifiers() & Qt.ControlModifier
                and event.key() == Qt.Key_Up):
            # Ctrl+↑: 跳转到上一个字符集合
            self._goto_prev_char()
        elif (event.modifiers() & Qt.ControlModifier
                and event.key() == Qt.Key_Down):
            # Ctrl+↓: 跳转到下一个字符集合
            self._goto_next_char()
        elif (not (event.modifiers() & Qt.ControlModifier)
                and len(self._selected_indices) == 1
                and self._last_clicked_index is not None):
            # 单选切片时方向键导航(当前页内循环); Ctrl 修饰时不走此分支
            if event.key() == Qt.Key_Up:
                self._navigate_selection(-self._current_columns)
            elif event.key() == Qt.Key_Down:
                self._navigate_selection(self._current_columns)
            elif event.key() == Qt.Key_Left:
                self._navigate_selection(-1)
            elif event.key() == Qt.Key_Right:
                self._navigate_selection(1)
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def _navigate_selection(self, delta: int):
        """在当前页可见切片内按 delta 步长循环导航选中。

        参数:
            delta: 步长,Up=-cols,Down=+cols,Left=-1,Right=+1。
        """
        try:
            start = self._current_page * self._current_page_size
            page_idx = self._last_clicked_index - start
            slices = self.char_slices.get(self._current_char_text, [])
            page_slices_len = min(self._current_page_size, len(slices) - start)
            if page_slices_len <= 0:
                return
            if page_idx < 0 or page_idx >= page_slices_len:
                return
            new_page_idx = (page_idx + delta) % page_slices_len
            new_global_idx = start + new_page_idx
            self._selected_indices.clear()
            self._selected_indices.add(new_global_idx)
            self._last_clicked_index = new_global_idx
            self._refresh_slice_selection_visuals()
            self._preview_slice(new_global_idx)
        except Exception:
            traceback.print_exc()

    def _on_prev_page(self):
        # 焦点切换前提交红框拖拽修改
        self._commit_pending_red_box_resize()
        if self._current_page > 0:
            self._current_page -= 1
            self._selected_indices.clear()
            self._last_clicked_index = None
            self._render_current_page()

    def _on_next_page(self):
        # 焦点切换前提交红框拖拽修改
        self._commit_pending_red_box_resize()
        slices = self.char_slices.get(self._current_char_text, [])
        total_pages = max(1, (len(slices) + self._current_page_size - 1) // self._current_page_size)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._selected_indices.clear()
            self._last_clicked_index = None
            self._render_current_page()

    def _on_prev_step(self):
        """处理"上一步"按钮点击事件。

        第一字符(row==0):发射 back_signal 返回导入阶段。
        非第一字符:先 flush 当前字符组挂起修改,再切换到上一个字符。
        """
        try:
            # 焦点切换前提交红框拖拽修改
            self._commit_pending_red_box_resize()
            current_row = self.label_list.currentRow()
            if current_row <= 0:
                # 第一字符:返回导入阶段
                self.back_signal.emit()
                return
            # 先 flush 当前字符组的挂起修改
            self._flush_pending_modifications()
            self.label_list.blockSignals(True)
            target_row = max(0, current_row - 1)
            self.label_list.setCurrentRow(target_row)
            self.label_list.blockSignals(False)
            new_item = self.label_list.currentItem()
            if new_item:
                char_text = new_item.data(Qt.UserRole)
                self._clear_line_preview()
                self._selected_indices.clear()
                self._last_clicked_index = None
                self._current_preview_index = None
                self._update_slice_display(char_text, reset_page=True)
        except Exception:
            self.label_list.blockSignals(False)
            traceback.print_exc()

    def _goto_prev_char(self):
        """Ctrl+↑: 跳转到上一个字符集合(不触发返回导入)。"""
        current_row = self.label_list.currentRow()
        if current_row > 0:
            # 提交红框拖拽修改,避免丢失
            self._commit_pending_red_box_resize()
            self._flush_pending_modifications()
            self.label_list.blockSignals(True)
            self.label_list.setCurrentRow(current_row - 1)
            self.label_list.blockSignals(False)
            new_item = self.label_list.currentItem()
            if new_item:
                char_text = new_item.data(Qt.UserRole)
                self._clear_line_preview()
                self._selected_indices.clear()
                self._last_clicked_index = None
                self._current_preview_index = None
                self._update_slice_display(char_text, reset_page=True)

    def _goto_next_char(self):
        """Ctrl+↓: 跳转到下一个字符集合(不触发进入横校)。"""
        current_row = self.label_list.currentRow()
        if current_row < self.label_list.count() - 1:
            # 提交红框拖拽修改,避免丢失
            self._commit_pending_red_box_resize()
            self._flush_pending_modifications()
            self.label_list.blockSignals(True)
            self.label_list.setCurrentRow(current_row + 1)
            self.label_list.blockSignals(False)
            new_item = self.label_list.currentItem()
            if new_item:
                char_text = new_item.data(Qt.UserRole)
                self._clear_line_preview()
                self._selected_indices.clear()
                self._last_clicked_index = None
                self._current_preview_index = None
                self._update_slice_display(char_text, reset_page=True)

    def _update_nav_button_texts(self):
        """根据当前字符位置更新导航按钮文字。

        prev_step_btn:第一字符显示"返回导入",否则"上一步"。
        next_button:最后字符显示"进入横校",否则"下一步"。
        """
        current_row = self.label_list.currentRow()
        count = self.label_list.count()
        if current_row <= 0:
            self.prev_step_btn.setText("返回导入")
        else:
            self.prev_step_btn.setText("上一步")
        if count > 0 and current_row >= count - 1:
            self.next_button.setText("进入横校")
        else:
            self.next_button.setText("下一步")

    def _on_jump_char(self):
        """处理字符跳转:跳转到输入字符的集合,找不到则弹窗提示。"""
        try:
            text = self.jump_edit.text().strip()
            if not text:
                return
            if text in self.char_slices:
                for i in range(self.label_list.count()):
                    item = self.label_list.item(i)
                    if item.data(Qt.UserRole) == text:
                        self.label_list.setCurrentItem(item)
                        break
            else:
                QMessageBox.warning(
                    self, "未找到", f"没有找到字符: {text}"
                )
        except Exception:
            traceback.print_exc()
