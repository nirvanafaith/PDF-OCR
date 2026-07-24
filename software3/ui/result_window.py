"""第二阶段结果窗口模块：显示嵌入红字后的输出 PDF。

提供 QGraphicsView 渲染 PDF 各页 pixmap，支持滚动、Ctrl+滚轮缩放、
翻页、保存副本、打开所在文件夹、重新开始功能。

依赖：
    - PyMuPDF (fitz): PDF 文档解析与渲染
    - PyQt6: GUI 框架
"""

import os
import shutil

import fitz  # PyMuPDF
from PyQt6.QtCore import Qt, pyqtSignal, QByteArray
from PyQt6.QtGui import QPixmap, QImage, QAction, QWheelEvent, QPainter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolBar, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QLabel, QPushButton,
    QFileDialog, QMessageBox
)


class PDFGraphicsView(QGraphicsView):
    """QGraphicsView 子类，处理 Ctrl+滚轮缩放。

    普通滚轮事件交给 QGraphicsView 默认处理（滚动），
    Ctrl+滚轮事件转发给关联的 ResultWindow 进行缩放。
    """

    def __init__(self, result_window, parent=None):
        """初始化 PDFGraphicsView。

        Args:
            result_window: 关联的 ResultWindow 对象，用于调用缩放逻辑。
            parent: 父组件，默认为 None。
        """
        super().__init__(parent)
        self._result_window = result_window

    def wheelEvent(self, event: QWheelEvent):
        """重写滚轮事件：Ctrl+滚轮缩放，普通滚轮滚动。"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+滚轮缩放：调用 ResultWindow 的缩放逻辑
            delta = event.angleDelta().y()
            if delta > 0:
                self._result_window.zoom_factor = min(
                    self._result_window.zoom_factor * 1.15, 5.0
                )
            else:
                self._result_window.zoom_factor = max(
                    self._result_window.zoom_factor / 1.15, 0.2
                )
            self._result_window._render_current_page()
        else:
            # 普通滚轮：交给 QGraphicsView 默认处理（滚动）
            super().wheelEvent(event)


class ResultWindow(QWidget):
    """第二阶段：显示嵌入红字后的输出 PDF。

    提供 QGraphicsView 渲染 PDF 各页 pixmap，支持滚动、Ctrl+滚轮缩放、
    翻页、保存副本、打开所在文件夹、重新开始功能。
    """

    restart_signal = pyqtSignal()  # 重新开始信号，通知主窗口重置到 Stage 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_path = ""        # 当前加载的 PDF 路径
        self.doc = None           # fitz.Document 对象
        self.current_page = 0     # 当前页索引（0-based）
        self.total_pages = 0
        self.zoom_factor = 1.0    # 缩放因子
        self.render_dpi = 150     # 渲染 DPI（平衡清晰度与内存）
        self._init_ui()

    def _init_ui(self):
        """初始化用户界面。"""
        # 1. QVBoxLayout 主布局
        main_layout = QVBoxLayout(self)

        # 2. 顶部 QToolBar
        self.toolbar = QToolBar()
        # 工具栏样式参考 software1/ui/styles.py 的 QToolBar 样式
        self.toolbar.setStyleSheet("""
            QToolBar {
                background-color: #d4d0c8;
                border-bottom: 1px solid #808080;
                padding: 4px 8px;
                spacing: 6px;
            }
            QToolBar QLabel {
                padding: 0 8px;
                font-size: 12px;
            }
        """)

        # 上一页
        self.prev_action = QAction("上一页", self)
        self.prev_action.triggered.connect(self._on_prev_page)
        self.toolbar.addAction(self.prev_action)

        # 下一页
        self.next_action = QAction("下一页", self)
        self.next_action.triggered.connect(self._on_next_page)
        self.toolbar.addAction(self.next_action)

        # 页码标签
        self.page_label = QLabel("0 / 0")
        self.toolbar.addWidget(self.page_label)

        self.toolbar.addSeparator()

        # 保存副本
        self.save_action = QAction("保存副本", self)
        self.save_action.triggered.connect(self._on_save_copy)
        self.toolbar.addAction(self.save_action)

        # 打开所在文件夹
        self.open_folder_action = QAction("打开所在文件夹", self)
        self.open_folder_action.triggered.connect(self._on_open_folder)
        self.toolbar.addAction(self.open_folder_action)

        self.toolbar.addSeparator()

        # 重新开始（橙色突出）
        self.restart_action = QAction("重新开始", self)
        self.restart_action.triggered.connect(self._on_restart)
        self.toolbar.addAction(self.restart_action)
        # 设置关联按钮的样式为橙色突出
        restart_btn = self.toolbar.widgetForAction(self.restart_action)
        if restart_btn is not None:
            restart_btn.setStyleSheet("""
                QToolButton {
                    background-color: #f0ad4e;
                    color: #ffffff;
                    border: 1px solid #d9531e;
                    padding: 4px 12px;
                    font-weight: bold;
                }
                QToolButton:hover {
                    background-color: #ec971f;
                }
                QToolButton:pressed {
                    background-color: #d9531e;
                }
            """)

        main_layout.addWidget(self.toolbar)

        # 3. 中央 QGraphicsView
        self.view = PDFGraphicsView(self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setStyleSheet(
            "QGraphicsView { border: 1px solid #808080; background-color: #52595f; }"
        )

        # 4. QGraphicsScene
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, 2000, 3000)  # 初始场景大小
        self.view.setScene(self.scene)

        # 5. 将 self.view 添加到主布局（stretch=1）
        main_layout.addWidget(self.view, 1)

    def load_pdf(self, pdf_path: str):
        """加载输出 PDF 并显示第 1 页。

        Args:
            pdf_path: 输出 PDF 文件路径
        """
        self.pdf_path = pdf_path
        if self.doc is not None:
            self.doc.close()
        self.doc = fitz.open(pdf_path)
        self.total_pages = self.doc.page_count
        self.current_page = 0
        self.zoom_factor = 1.0
        self._render_current_page()
        self._update_page_label()

    def _render_current_page(self):
        """渲染当前页到 QGraphicsScene。"""
        if not self.doc or self.current_page >= self.total_pages:
            return
        page = self.doc[self.current_page]
        # 创建变换矩阵实现缩放
        zoom_matrix = fitz.Matrix(self.zoom_factor, self.zoom_factor)
        pix = page.get_pixmap(matrix=zoom_matrix, dpi=self.render_dpi)
        # Pixmap 转 QImage 转 QPixmap
        img_data = pix.tobytes("ppm")
        qimage = QImage()
        qimage.loadFromData(img_data, "PPM")
        pixmap = QPixmap.fromImage(qimage)
        # 清空场景并添加新 pixmap
        self.scene.clear()
        item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(item)
        self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

    def _update_page_label(self):
        """更新页码标签。"""
        self.page_label.setText(f"{self.current_page + 1} / {self.total_pages}")

    def _update_nav_actions(self):
        """根据当前页码更新上一页/下一页 Action 的可用状态。"""
        self.prev_action.setEnabled(self.current_page > 0)
        self.next_action.setEnabled(self.current_page < self.total_pages - 1)

    def _on_prev_page(self):
        """翻到上一页。"""
        if self.current_page > 0:
            self.current_page -= 1
            self._render_current_page()
            self._update_page_label()
            self._update_nav_actions()

    def _on_next_page(self):
        """翻到下一页。"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._render_current_page()
            self._update_page_label()
            self._update_nav_actions()

    def _on_save_copy(self):
        """保存 PDF 副本到用户指定路径。"""
        if not self.pdf_path:
            return
        suggested_name = os.path.basename(self.pdf_path)
        default_path = os.path.join(os.path.expanduser("~"), suggested_name)
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存 PDF 副本", default_path, "PDF文件 (*.pdf)"
        )
        if save_path:
            try:
                shutil.copy2(self.pdf_path, save_path)
                QMessageBox.information(self, "成功", f"已保存到: {save_path}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def _on_open_folder(self):
        """在文件资源管理器中打开 PDF 所在文件夹。"""
        if not self.pdf_path:
            return
        folder = os.path.dirname(os.path.abspath(self.pdf_path))
        try:
            os.startfile(folder)
        except Exception as e:
            QMessageBox.warning(self, "打开文件夹失败", str(e))

    def _on_restart(self):
        """重新开始按钮：发射 restart_signal 通知主窗口重置。"""
        self.restart_signal.emit()

    def wheelEvent(self, event: QWheelEvent):
        """Ctrl+滚轮缩放，普通滚轮滚动。

        注意：由于 QGraphicsView 会消费滚轮事件，此方法在 ResultWindow 上
        不会被调用。实际滚轮处理由 PDFGraphicsView.wheelEvent 完成。
        """
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+滚轮缩放
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_factor = min(self.zoom_factor * 1.15, 5.0)
            else:
                self.zoom_factor = max(self.zoom_factor / 1.15, 0.2)
            self._render_current_page()
        else:
            # 普通滚轮：交给 QGraphicsView 默认处理（滚动）
            super().wheelEvent(event)

    def cleanup(self):
        """清理资源，关闭 fitz.Document。"""
        if self.doc is not None:
            self.doc.close()
            self.doc = None
