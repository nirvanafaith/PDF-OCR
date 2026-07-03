import os

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QGroupBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt5.QtGui import QTextCursor

from pdf_processor import PDFProcessor
from ocr_engine import OCREngine
from ui.styles import get_stylesheet


class ImportWorker(QObject):
    """数据导入工作线程的Worker对象，负责在子线程中加载PDF图像和OCR结果。

    依次执行PDF转图像、加载JSON结果、解析分组三个步骤，
    通过信号将进度、完成结果或错误信息传递回主线程。

    信号:
        finished_signal (pyqtSignal()): 完成信号，结果保存为实例属性。
        error_signal (pyqtSignal(str)): 错误信号，发射异常信息。
        progress_signal (pyqtSignal(str)): 进度信号，发射进度描述文本。
    """

    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str)

    def __init__(self, pdf_path, lines_path, chars_path, ocr_engine, pdf_processor):
        super().__init__()
        self.pdf_path = pdf_path
        self.lines_path = lines_path
        self.chars_path = chars_path
        self.ocr_engine = ocr_engine
        self.pdf_processor = pdf_processor
        self.page_images = None
        self.ocr_results = None
        self.char_slices = None

    def run(self):
        try:
            self.progress_signal.emit("正在加载PDF页面图像...")
            self.page_images = self.pdf_processor.convert_to_images(
                self.pdf_path, dpi=200
            )
            self.progress_signal.emit(f"已加载 {len(self.page_images)} 页图像")

            self.progress_signal.emit("正在加载JSON结果...")
            self.ocr_results = self.ocr_engine.load_results_from_file(
                self.lines_path, self.chars_path
            )
            self.progress_signal.emit("JSON结果加载完成")

            self.progress_signal.emit("正在构建字符切片分组...")
            self.char_slices = self.ocr_engine.parse_and_group(
                self.ocr_results, self.page_images
            )
            total_chars = sum(len(v) for v in self.char_slices.values())
            self.progress_signal.emit(
                f"已分组 {len(self.char_slices)} 种字符，共 {total_chars} 个切片"
            )

            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))


class ImportWindow(QWidget):
    """数据导入窗口，用于导入PDF文件及对应的lines.json和chars.json。

    用户在此窗口选择PDF文件和OCR结果JSON文件，点击加载后
    在子线程中完成数据加载，加载完成后通过finished_signal通知主窗口。

    信号:
        finished_signal (pyqtSignal(list, tuple, dict)): 加载完成信号，
            发射 (page_images, ocr_results, char_slices)。
    """

    finished_signal = pyqtSignal(list, tuple, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pdf_processor = PDFProcessor()
        self.ocr_engine = OCREngine()
        self._worker = None
        self._thread = None
        self.setStyleSheet(get_stylesheet())
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(20, 20, 20, 20)

        title_label = QLabel("数据导入")
        title_label.setStyleSheet(
            "QLabel { font-size: 20px; font-weight: bold; color: #212529; }"
        )
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)

        file_group = QGroupBox("文件选择")
        file_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #dee2e6; "
            "border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }"
        )
        file_layout = QVBoxLayout(file_group)
        file_layout.setSpacing(12)

        # Row 1: PDF文件
        pdf_row = QHBoxLayout()
        pdf_row.setSpacing(8)
        pdf_label = QLabel("PDF文件:")
        pdf_label.setFixedWidth(80)
        pdf_label.setStyleSheet("font-weight: normal;")
        pdf_row.addWidget(pdf_label)
        self.pdf_path_edit = QLineEdit()
        self.pdf_path_edit.setReadOnly(True)
        self.pdf_path_edit.setPlaceholderText("请选择PDF文件")
        self.pdf_path_edit.setMinimumHeight(36)
        pdf_row.addWidget(self.pdf_path_edit, 1)
        self.browse_pdf_btn = QPushButton("浏览...")
        self.browse_pdf_btn.setFixedWidth(80)
        self.browse_pdf_btn.setMinimumHeight(36)
        self.browse_pdf_btn.clicked.connect(self._on_browse_pdf)
        pdf_row.addWidget(self.browse_pdf_btn)
        file_layout.addLayout(pdf_row)

        # Row 2: lines.json
        lines_row = QHBoxLayout()
        lines_row.setSpacing(8)
        lines_label = QLabel("lines.json:")
        lines_label.setFixedWidth(80)
        lines_label.setStyleSheet("font-weight: normal;")
        lines_row.addWidget(lines_label)
        self.lines_path_edit = QLineEdit()
        self.lines_path_edit.setReadOnly(True)
        self.lines_path_edit.setEnabled(False)
        self.lines_path_edit.setPlaceholderText("自动检测")
        self.lines_path_edit.setMinimumHeight(36)
        lines_row.addWidget(self.lines_path_edit, 1)
        self.browse_lines_btn = QPushButton("浏览...")
        self.browse_lines_btn.setFixedWidth(80)
        self.browse_lines_btn.setMinimumHeight(36)
        self.browse_lines_btn.setEnabled(False)
        lines_row.addWidget(self.browse_lines_btn)
        file_layout.addLayout(lines_row)

        # Row 3: chars.json / newchar.json
        chars_row = QHBoxLayout()
        chars_row.setSpacing(8)
        chars_label = QLabel("字符JSON:")
        chars_label.setFixedWidth(80)
        chars_label.setStyleSheet("font-weight: normal;")
        chars_row.addWidget(chars_label)
        self.chars_path_edit = QLineEdit()
        self.chars_path_edit.setReadOnly(True)
        self.chars_path_edit.setEnabled(False)
        self.chars_path_edit.setPlaceholderText("自动检测")
        self.chars_path_edit.setMinimumHeight(36)
        chars_row.addWidget(self.chars_path_edit, 1)
        self.browse_chars_btn = QPushButton("浏览...")
        self.browse_chars_btn.setFixedWidth(80)
        self.browse_chars_btn.setMinimumHeight(36)
        self.browse_chars_btn.setEnabled(False)
        chars_row.addWidget(self.browse_chars_btn)
        file_layout.addLayout(chars_row)

        # 提示标签
        hint_label = QLabel("提示：选择PDF后将自动检测同目录下的 lines.json 与 newchar.json（优先）/chars.json")
        hint_label.setStyleSheet("font-weight: normal; color: #6c757d;")
        file_layout.addWidget(hint_label)

        main_layout.addWidget(file_group)

        # 开始加载按钮
        self.load_btn = QPushButton("开始加载")
        self.load_btn.setEnabled(False)
        self.load_btn.setStyleSheet(
            "QPushButton { background-color: #0D6EFD; color: white; "
            "min-height: 44px; min-width: 160px; padding: 10px 30px; "
            "border: none; border-radius: 6px; font-size: 14px; }"
            "QPushButton:hover { background-color: #0b5ed7; }"
            "QPushButton:disabled { background-color: #6c757d; }"
        )
        self.load_btn.clicked.connect(self._on_load)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.load_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # 状态信息
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px; "
            "border: 1px solid #3c3c3c; border-radius: 4px; padding: 8px; }"
        )
        main_layout.addWidget(self.status_text, 1)

    def _detect_json_files(self, pdf_dir: str):
        """根据PDF所在目录自动检测lines.json与字符JSON文件。

        优先使用newchar.json，不存在时回退到chars.json。

        参数:
            pdf_dir: PDF文件所在目录路径。

        返回:
            tuple: (lines_path, chars_path)，未找到对应文件时为空字符串。
        """
        lines_path = os.path.join(pdf_dir, "lines.json")
        lines_path = lines_path if os.path.exists(lines_path) else ""

        chars_path = ""
        for name in ("newchar.json", "chars.json"):
            candidate = os.path.join(pdf_dir, name)
            if os.path.exists(candidate):
                chars_path = candidate
                break

        return lines_path, chars_path

    def _on_browse_pdf(self):
        pdf_path, _ = QFileDialog.getOpenFileName(
            self, "选择PDF文件", "", "PDF文件 (*.pdf)"
        )
        if pdf_path:
            self.pdf_path_edit.setText(pdf_path)
            pdf_dir = os.path.dirname(pdf_path)
            lines_path, chars_path = self._detect_json_files(pdf_dir)
            self.lines_path_edit.setText(lines_path)
            self.chars_path_edit.setText(chars_path)
            self._check_load_enabled()

    def _check_load_enabled(self):
        """检查是否可以选择PDF并加载。

        由于 lines.json 和字符 JSON 均由系统自动检测，只需确认 PDF 已选择。
        """
        has_pdf = bool(self.pdf_path_edit.text().strip())
        self.load_btn.setEnabled(has_pdf)

    def _append_status(self, text):
        self.status_text.moveCursor(QTextCursor.End)
        self.status_text.insertPlainText(text + "\n")
        self.status_text.ensureCursorVisible()

    def _on_load(self):
        pdf_path = self.pdf_path_edit.text().strip()
        lines_path = self.lines_path_edit.text().strip()
        chars_path = self.chars_path_edit.text().strip()

        if not pdf_path:
            QMessageBox.warning(self, "提示", "请先选择PDF文件")
            return
        if not lines_path or not chars_path:
            QMessageBox.warning(
                self, "提示",
                "未在PDF所在目录检测到 lines.json 与字符JSON文件（newchar.json 或 chars.json）"
            )
            return

        self.load_btn.setEnabled(False)
        self.status_text.clear()
        self._append_status("开始加载数据...")

        self._thread = QThread()
        self._worker = ImportWorker(
            pdf_path, lines_path, chars_path,
            self.ocr_engine, self.pdf_processor
        )
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress_signal.connect(self._append_status)
        self._worker.finished_signal.connect(self._on_load_finished)
        self._worker.error_signal.connect(self._on_load_error)

        self._thread.start()

    def _on_load_finished(self):
        page_images = self._worker.page_images
        ocr_results = self._worker.ocr_results
        char_slices = self._worker.char_slices
        self._cleanup_thread()
        self.load_btn.setEnabled(True)
        self._append_status("数据加载完成！")
        self.finished_signal.emit(page_images, ocr_results, char_slices)

    def _on_load_error(self, error_msg):
        self._cleanup_thread()
        self.load_btn.setEnabled(True)
        self._append_status(f"\n错误: {error_msg}")
        QMessageBox.critical(self, "加载失败", error_msg)

    def _cleanup_thread(self):
        if self._thread is not None:
            if self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(3000)
            self._thread = None
            self._worker = None

    def cleanup(self):
        self._cleanup_thread()
