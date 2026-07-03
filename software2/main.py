from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QHBoxLayout,
    QLabel,
    QWidget,
    QVBoxLayout,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from pdf_processor import PDFProcessor
from ocr_engine import OCREngine
from ui.import_window import ImportWindow
from ui.vertical_check_window import VerticalCheckWindow
from ui.horizontal_check_window import HorizontalCheckWindow
from ui.refine_window import RefineWindow
from ui.styles import get_stylesheet


class StepIndicator(QWidget):
    """步骤指示器组件，用于显示当前所处的处理阶段。"""

    def __init__(self, steps: list, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.current = 0
        self.setFixedHeight(50)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 8)
        layout.setSpacing(0)
        self.labels = []
        for i, step in enumerate(self.steps):
            label = QLabel(step)
            label.setAlignment(Qt.AlignCenter)
            label.setFixedHeight(34)
            font = QFont()
            font.setPointSize(10)
            label.setFont(font)
            if i == 0:
                self._set_active_style(label)
            else:
                self._set_inactive_style(label)
            layout.addWidget(label, 1)
            if i < len(self.steps) - 1:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setFixedWidth(30)
                self._set_arrow_style(arrow)
                layout.addWidget(arrow)
            self.labels.append(label)

    def _set_active_style(self, label):
        label.setStyleSheet(
            "QLabel { background-color: #0D6EFD; color: white; "
            "border-radius: 6px; font-weight: bold; padding: 4px 12px; }"
        )

    def _set_done_style(self, label):
        label.setStyleSheet(
            "QLabel { background-color: #198754; color: white; "
            "border-radius: 6px; font-weight: bold; padding: 4px 12px; }"
        )

    def _set_inactive_style(self, label):
        label.setStyleSheet(
            "QLabel { background-color: #e9ecef; color: #6c757d; "
            "border-radius: 6px; padding: 4px 12px; }"
        )

    def _set_arrow_style(self, label):
        label.setStyleSheet("QLabel { color: #adb5bd; font-size: 16px; }")

    def set_current(self, index: int):
        self.current = index
        for i, label in enumerate(self.labels):
            if i < index:
                self._set_done_style(label)
            elif i == index:
                self._set_active_style(label)
            else:
                self._set_inactive_style(label)


class MainWindow(QMainWindow):
    """应用程序主窗口，管理四阶段处理流程：导入 → 纵校 → 横校 → 精修。"""

    STAGES = ["导入", "纵校", "横校", "精修"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("横校工具")
        self.setMinimumSize(1200, 800)
        self.pdf_processor = PDFProcessor()
        self.ocr_engine = OCREngine()
        self.page_images = []
        self.ocr_results = ([], [])
        self.char_slices = {}
        self.current_stage = 0
        self.setStyleSheet(get_stylesheet())
        self._init_ui()
        self._setup_import_stage()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.step_indicator = StepIndicator(self.STAGES)
        layout.addWidget(self.step_indicator)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

    # ---- Stage 0: 导入 ----

    def _setup_import_stage(self):
        self.import_widget = ImportWindow()
        self.import_widget.finished_signal.connect(self._on_import_finished)
        self.stack.addWidget(self.import_widget)
        self.stack.setCurrentWidget(self.import_widget)
        self.step_indicator.set_current(0)

    def _on_import_finished(self, page_images, ocr_results, char_slices):
        self.page_images = page_images
        self.ocr_results = ocr_results
        self.char_slices = char_slices
        self.current_stage = 1
        self.step_indicator.set_current(1)
        self._setup_vertical_stage()

    # ---- Stage 1: 纵校 ----

    def _setup_vertical_stage(self):
        self.vert_widget = VerticalCheckWindow(
            self.char_slices, self.page_images, self.ocr_results
        )
        self.vert_widget.finished_signal.connect(self._on_vertical_finished)
        self.vert_widget.back_signal.connect(self._on_vertical_back)
        self.stack.addWidget(self.vert_widget)
        self.stack.setCurrentWidget(self.vert_widget)

    def _on_vertical_finished(self, updated_char_slices, updated_ocr_results):
        self.char_slices = updated_char_slices
        self.ocr_results = updated_ocr_results
        self.current_stage = 2
        self.step_indicator.set_current(2)
        self._setup_horizontal_stage()

    def _on_vertical_back(self):
        self.stack.removeWidget(self.vert_widget)
        self.vert_widget.deleteLater()
        self.current_stage = 0
        self.step_indicator.set_current(0)
        self.stack.setCurrentWidget(self.import_widget)

    # ---- Stage 2: 横校 ----

    def _setup_horizontal_stage(self):
        page_lines = self.ocr_engine.build_line_data(
            self.ocr_results, self.page_images, self.char_slices
        )
        self.horiz_widget = HorizontalCheckWindow(
            page_lines, self.page_images
        )
        self.horiz_widget.finished_signal.connect(self._on_horizontal_finished)
        self.horiz_widget.back_signal.connect(self._on_horizontal_back)
        self.stack.addWidget(self.horiz_widget)
        self.stack.setCurrentWidget(self.horiz_widget)

    def _on_horizontal_finished(self, corrected_lines):
        self.current_stage = 3
        self.step_indicator.set_current(3)
        self._setup_refine_stage()

    def _on_horizontal_back(self):
        self.stack.removeWidget(self.horiz_widget)
        self.horiz_widget.deleteLater()
        self.current_stage = 1
        self.step_indicator.set_current(1)
        self.stack.setCurrentWidget(self.vert_widget)

    # ---- Stage 3: 精修 ----

    def _setup_refine_stage(self):
        page_lines = self.horiz_widget.page_lines
        self.refine_widget = RefineWindow(
            page_lines, self.page_images
        )
        self.refine_widget.output_complete_signal.connect(self._on_output_complete)
        self.refine_widget.finished_signal.connect(self._on_refine_finished)
        self.refine_widget.back_signal.connect(self._on_refine_back)
        self.stack.addWidget(self.refine_widget)
        self.stack.setCurrentWidget(self.refine_widget)

    def _on_output_complete(self, red_path, transparent_path):
        QMessageBox.information(
            self,
            "成功",
            f"PDF文件已成功生成！\n\n红色文字版：{red_path}\n透明文字版：{transparent_path}",
        )

    def _on_refine_back(self):
        self.stack.removeWidget(self.refine_widget)
        self.refine_widget.deleteLater()
        self.current_stage = 2
        self.step_indicator.set_current(2)
        self.stack.setCurrentWidget(self.horiz_widget)

    def _on_refine_finished(self):
        self.refine_widget.cleanup()
        while self.stack.count() > 0:
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.page_images = []
        self.ocr_results = ([], [])
        self.char_slices = {}
        self.current_stage = 0
        self._setup_import_stage()


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    app.setStyle("Windows")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
