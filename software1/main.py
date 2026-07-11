import os
import site
import sys

# 启动期诊断：打印 _hxnative C++ 加速扩展的加载状态（缺失不影响运行）
try:
    if getattr(sys, "frozen", False):
        # PyInstaller onedir: native 位于 sys._MEIPASS (_internal/) 下
        _root = sys._MEIPASS  # type: ignore[attr-defined]
        if _root not in sys.path:
            sys.path.insert(0, _root)
    # 仅导入以触发 native/__init__.py 的单次诊断打印
    import native  # noqa: F401
except Exception as _e:
    print(f"native: diagnostic skipped ({_e})", file=sys.stderr)

# 搜索 nvidia CUDA pip 包的 bin 目录（可能在系统或用户 site-packages 中）
_nvidia_search_dirs = [os.path.join(d, 'nvidia') for d in site.getsitepackages()]
_nvidia_search_dirs.append(os.path.join(site.getusersitepackages(), 'nvidia'))
for nvidia_base in _nvidia_search_dirs:
    if os.path.exists(nvidia_base):
        for pkg_name in os.listdir(nvidia_base):
            bin_dir = os.path.join(nvidia_base, pkg_name, 'bin')
            if os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
                os.environ['PATH'] = bin_dir + os.pathsep + os.environ['PATH']

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QHBoxLayout,
    QLabel,
    QWidget,
    QVBoxLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from pdf_processor import PDFProcessor
from ocr_engine import OCREngine
from ui.draw_box_window import DrawBoxWindow
from ui.ocr_prepare_window import OCRPrepareWindow
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
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
    """应用程序主窗口，管理画框+OCR两阶段处理流程。"""

    STAGES = ["画框", "OCR准备"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("画框+OCR")
        self.setMinimumSize(1200, 800)
        self.pdf_processor = PDFProcessor()
        self.ocr_engine = OCREngine()
        self.pdf_path = ""
        self.regions = {}
        self.current_stage = 0
        self.setStyleSheet(get_stylesheet())
        self._init_ui()
        self._setup_draw_box_stage()

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

    def _setup_draw_box_stage(self):
        self.draw_box_widget = DrawBoxWindow()
        self.draw_box_widget.finished_signal.connect(self._on_draw_box_finished)
        self.stack.addWidget(self.draw_box_widget)
        self.stack.setCurrentWidget(self.draw_box_widget)
        self.step_indicator.set_current(0)

    def _on_draw_box_finished(self, pdf_path, regions):
        self.pdf_path = pdf_path
        self.regions = regions
        self.current_stage = 1
        self.step_indicator.set_current(1)
        self._setup_prepare_stage(pdf_path, regions)

    def _setup_prepare_stage(self, pdf_path="", regions=None):
        self.prepare_widget = OCRPrepareWindow(pdf_path, regions)
        self.prepare_widget.finished_signal.connect(self._on_prepare_finished)
        self.prepare_widget.back_signal.connect(self._on_prepare_back)
        self.stack.addWidget(self.prepare_widget)
        self.stack.setCurrentWidget(self.prepare_widget)
        self.step_indicator.set_current(1)

    def _on_prepare_finished(self, page_images, ocr_results, char_slices):
        self.prepare_widget.cleanup()
        QMessageBox.information(
            self,
            "完成",
            "OCR识别完成！结果已保存为chars.json和lines.json",
        )
        self._restart()

    def _on_prepare_back(self):
        self.prepare_widget.cleanup()
        self.stack.removeWidget(self.prepare_widget)
        self.prepare_widget.deleteLater()
        self.current_stage = 0
        self.step_indicator.set_current(0)
        self.stack.setCurrentWidget(self.draw_box_widget)

    def _restart(self):
        while self.stack.count() > 0:
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.pdf_path = ""
        self.regions = {}
        self.current_stage = 0
        self._setup_draw_box_stage()


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    app.setStyle("Windows")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
