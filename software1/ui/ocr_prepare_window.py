from PyQt6.QtWidgets import (
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
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QTextCursor
import sys

from pdf_processor import PDFProcessor
from ocr_engine import OCREngine
from ui.styles import get_stylesheet


class OCRWorker(QObject):
    """OCR识别工作线程的Worker对象，负责在子线程中执行OCR识别任务。

    该对象通过 moveToThread 移入 QThread 中运行，避免阻塞主线程UI。
    执行过程中通过信号将输出日志、完成结果或错误信息传递回主线程。

    信号:
        output_signal (pyqtSignal(str)): 输出日志信号，发射OCR执行过程中的文本输出。
        finished_signal (pyqtSignal(tuple, str)): 完成信号，发射OCR识别结果元组和输出目录路径。
        error_signal (pyqtSignal(str)): 错误信号，发射OCR执行过程中的异常信息。

    依赖:
        ocr_engine.OCREngine: OCR识别引擎，提供 run_ocr 方法。

    调用关系:
        __init__: 被 OCRPrepareWindow._on_run_ocr 中创建实例。
        run: 由 ocr_thread.started 信号触发，在子线程中执行OCR。
    """

    output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(tuple, str)
    error_signal = pyqtSignal(str)

    def __init__(self, pdf_path, output_dir, ocr_engine, regions=None):
        """初始化OCR工作线程的Worker对象。

        Args:
            pdf_path (str): 待识别的PDF文件路径。
            output_dir (str): OCR识别结果的输出目录路径。
            ocr_engine (OCREngine): OCR识别引擎实例，用于执行实际的OCR识别操作。
            regions (dict, optional): 区域信息字典，指定OCR识别的区域范围，默认为None。
        """
        super().__init__()
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.ocr_engine = ocr_engine
        self.regions = regions

    def run(self):
        """在子线程中执行OCR识别操作。

        调用 ocr_engine.run_ocr 方法对PDF文件进行OCR识别，执行过程中
        通过 output_signal 实时发射日志输出，识别完成后通过 finished_signal
        发射结果，发生异常时通过 error_signal 发射错误信息。

        Returns:
            None: 结果通过信号传递，无直接返回值。

        Emits:
            output_signal(str): OCR执行过程中的每一行日志输出。
            finished_signal(tuple, str): OCR识别结果和输出目录路径。
            error_signal(str): 执行过程中发生的异常信息。

        依赖:
            ocr_engine.OCREngine.run_ocr: 执行OCR识别的核心方法。
        """
        try:
            results = self.ocr_engine.run_ocr(
                self.pdf_path,
                self.output_dir,
                output_callback=lambda line: self.output_signal.emit(line),
                regions=self.regions
            )
            self.finished_signal.emit(results, self.output_dir)
        except Exception as e:
            self.error_signal.emit(str(e))


class DataLoadWorker(QObject):
    """数据加载工作线程的Worker对象，负责在子线程中加载PDF页面图像和OCR识别结果。

    该对象通过 moveToThread 移入 QThread 中运行，避免加载大量数据时阻塞主线程UI。
    加载过程中通过 progress_signal 实时报告进度，加载完成后通过 finished_signal
    传递页面图像、OCR结果和字符切片分组数据。

    信号:
        finished_signal (pyqtSignal(list, tuple, dict)): 完成信号，发射页面图像列表、
            OCR结果元组和字符切片分组字典。
        error_signal (pyqtSignal(str)): 错误信号，发射数据加载过程中的异常信息。
        progress_signal (pyqtSignal(str)): 进度信号，发射数据加载过程中的进度描述文本。

    依赖:
        pdf_processor.PDFProcessor: PDF文档处理，提供 convert_to_images 方法。
        ocr_engine.OCREngine: OCR识别引擎，提供结果加载和解析分组方法。

    调用关系:
        __init__: 被 OCRPrepareWindow._on_next 中创建实例。
        run: 由 _data_thread.started 信号触发，在子线程中加载PDF和OCR数据。
    """

    finished_signal = pyqtSignal(list, tuple, dict)
    error_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str)

    def __init__(self, pdf_path, lines_path, chars_path, ocr_engine, pdf_processor):
        """初始化数据加载工作线程的Worker对象。

        Args:
            pdf_path (str): PDF文件路径，用于加载页面图像。
            lines_path (str): Lines JSON文件路径，包含行级OCR识别结果。
            chars_path (str): Chars JSON文件路径，包含字符级OCR识别结果。
            ocr_engine (OCREngine): OCR识别引擎实例，用于加载和解析OCR结果。
            pdf_processor (PDFProcessor): PDF处理器实例，用于将PDF转换为页面图像。
        """
        super().__init__()
        self.pdf_path = pdf_path
        self.lines_path = lines_path
        self.chars_path = chars_path
        self.ocr_engine = ocr_engine
        self.pdf_processor = pdf_processor

    def run(self):
        """在子线程中执行PDF页面图像加载和OCR结果解析。

        依次执行以下步骤：
        1. 将PDF文件转换为页面图像列表；
        2. 加载OCR识别结果（优先使用已缓存的结果，否则从JSON文件加载）；
        3. 对OCR结果进行字符切片分组。

        执行过程中通过 progress_signal 实时报告进度，完成后通过
        finished_signal 发射结果数据，发生异常时通过 error_signal 发射错误信息。

        Returns:
            None: 结果通过信号传递，无直接返回值。

        Emits:
            progress_signal(str): 各步骤的进度描述文本。
            finished_signal(list, tuple, dict): 页面图像列表、OCR结果元组、
                字符切片分组字典。
            error_signal(str): 执行过程中发生的异常信息。

        依赖:
            pdf_processor.PDFProcessor.convert_to_images: 将PDF转换为页面图像。
            ocr_engine.OCREngine.load_results_from_file: 从JSON文件加载OCR结果。
            ocr_engine.OCREngine.parse_and_group: 解析OCR结果并按字符分组。
        """
        try:
            self.progress_signal.emit("正在加载PDF页面图像...")
            page_images = self.pdf_processor.convert_to_images(self.pdf_path, dpi=300)
            self.progress_signal.emit(f"已加载 {len(page_images)} 页图像")
            self.progress_signal.emit("正在解析JSON结果...")
            if self.ocr_engine.results is not None:
                results = self.ocr_engine.results
            else:
                results = self.ocr_engine.load_results_from_file(self.lines_path, self.chars_path)
            self.progress_signal.emit("正在构建字符切片分组...")
            char_slices = self.ocr_engine.parse_and_group(results, page_images)
            total_chars = sum(len(v) for v in char_slices.values())
            self.progress_signal.emit(f"已分组 {len(char_slices)} 种字符，共 {total_chars} 个切片")
            self.finished_signal.emit(page_images, results, char_slices)
        except Exception as e:
            self.error_signal.emit(str(e))


class OCRPrepareWindow(QWidget):
    """OCR准备阶段主窗口，提供PDF文件选择、OCR识别执行和数据加载的交互界面。

    该窗口是纵校工具的第一阶段界面，用户在此窗口中配置PDF文件路径和OCR结果文件路径，
    执行OCR识别或手动指定已有的识别结果，然后加载所有必要数据以进入纵校阶段。

    信号:
        finished_signal (pyqtSignal(list, tuple, dict)): 准备完成信号，发射页面图像列表、
            OCR结果元组和字符切片分组字典，通知主窗口进入下一阶段。

    依赖:
        PyQt6: QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
            QTextEdit, QFileDialog, QMessageBox, QGroupBox, Qt, pyqtSignal,
            QThread, QObject, QTextCursor
        pdf_processor.PDFProcessor: PDF文档处理。
        ocr_engine.OCREngine: OCR识别引擎。
        ui.styles.get_stylesheet: 全局样式表。

    调用关系:
        __init__: 被 MainWindow._setup_prepare_stage 中创建实例。
    """

    finished_signal = pyqtSignal(list, tuple, dict)
    back_signal = pyqtSignal()

    def __init__(self, pdf_path: str, regions: dict = None, parent=None):
        """初始化OCR准备阶段主窗口。

        创建PDF处理器和OCR引擎实例，初始化OCR运行状态标志，
        应用全局样式表并构建UI界面。

        Args:
            pdf_path (str): 初始PDF文件路径，由主窗口传入。
            regions (dict, optional): 区域信息字典，由画框步骤传入，
                指定OCR识别的区域范围，默认为None（空字典）。
            parent (QWidget, optional): 父窗口对象，默认为None。

        调用关系:
            被 MainWindow._setup_prepare_stage 中创建实例。
            内部调用 _init_ui 构建界面。
        """
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.regions = regions if regions is not None else {}
        self.pdf_processor = PDFProcessor()
        self.ocr_engine = OCREngine()
        self._ocr_running = False
        self.ocr_thread = None
        self.ocr_worker = None
        self.setStyleSheet(get_stylesheet())
        self._init_ui()

    def _init_ui(self):
        """构建OCR准备窗口的UI界面。

        界面包含以下区域：
        - 文件设置分组：PDF文件路径选择、Lines JSON和Chars JSON文件路径选择；
        - 操作分组：执行OCR识别按钮；
        - CMD输出分组：实时显示OCR执行和数据加载的日志输出；
        - 底部区域：下一步按钮，用于进入纵校阶段。

        调用关系:
            被 __init__ 调用。
        """
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(20, 20, 20, 20)

        file_group = QGroupBox("文件设置")
        file_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #dee2e6; "
            "border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }"
        )
        file_layout = QVBoxLayout(file_group)
        file_layout.setSpacing(12)

        pdf_label = QLabel("PDF文件")
        pdf_label.setStyleSheet("font-weight: normal;")
        file_layout.addWidget(pdf_label)

        pdf_row = QHBoxLayout()
        pdf_row.setSpacing(8)
        self.pdf_path_edit = QLineEdit(self.pdf_path)
        self.pdf_path_edit.setPlaceholderText("请输入或选择PDF文件路径")
        self.pdf_path_edit.textChanged.connect(self._on_pdf_path_changed)
        self.pdf_path_edit.setMinimumHeight(36)
        pdf_row.addWidget(self.pdf_path_edit, 1)
        self.browse_pdf_btn = QPushButton("选择PDF")
        self.browse_pdf_btn.setFixedWidth(100)
        self.browse_pdf_btn.setMinimumHeight(36)
        self.browse_pdf_btn.clicked.connect(self._on_browse_pdf)
        pdf_row.addWidget(self.browse_pdf_btn)
        file_layout.addLayout(pdf_row)

        file_layout.addSpacing(8)

        lines_label = QLabel("Lines JSON文件")
        lines_label.setStyleSheet("font-weight: normal;")
        file_layout.addWidget(lines_label)

        lines_row = QHBoxLayout()
        lines_row.setSpacing(8)
        self.lines_path_edit = QLineEdit()
        self.lines_path_edit.setPlaceholderText("识别后自动填入，或手动输入/选择 lines.json")
        self.lines_path_edit.setMinimumHeight(36)
        lines_row.addWidget(self.lines_path_edit, 1)
        self.browse_lines_btn = QPushButton("选择JSON")
        self.browse_lines_btn.setFixedWidth(100)
        self.browse_lines_btn.setMinimumHeight(36)
        self.browse_lines_btn.clicked.connect(self._on_browse_lines)
        lines_row.addWidget(self.browse_lines_btn)
        file_layout.addLayout(lines_row)

        file_layout.addSpacing(8)

        chars_label = QLabel("Chars JSON文件")
        chars_label.setStyleSheet("font-weight: normal;")
        file_layout.addWidget(chars_label)

        chars_row = QHBoxLayout()
        chars_row.setSpacing(8)
        self.chars_path_edit = QLineEdit()
        self.chars_path_edit.setPlaceholderText("识别后自动填入，或手动输入/选择 chars.json")
        self.chars_path_edit.setMinimumHeight(36)
        chars_row.addWidget(self.chars_path_edit, 1)
        self.browse_chars_btn = QPushButton("选择JSON")
        self.browse_chars_btn.setFixedWidth(100)
        self.browse_chars_btn.setMinimumHeight(36)
        self.browse_chars_btn.clicked.connect(self._on_browse_chars)
        chars_row.addWidget(self.browse_chars_btn)
        file_layout.addLayout(chars_row)

        main_layout.addWidget(file_group)

        action_group = QGroupBox("操作")
        action_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #dee2e6; "
            "border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }"
        )
        action_layout = QHBoxLayout(action_group)
        action_layout.addStretch()
        self.run_ocr_btn = QPushButton("使用本地模型识别")
        self.run_ocr_btn.setStyleSheet(
            "QPushButton { background-color: #0D6EFD; color: white; "
            "min-height: 44px; min-width: 180px; padding: 10px 30px; "
            "border: none; border-radius: 6px; font-size: 14px; }"
            "QPushButton:hover { background-color: #0b5ed7; }"
            "QPushButton:disabled { background-color: #6c757d; }"
        )
        self.run_ocr_btn.clicked.connect(self._on_run_ocr)
        action_layout.addWidget(self.run_ocr_btn)
        action_layout.addStretch()
        main_layout.addWidget(action_group)

        output_group = QGroupBox("CMD输出")
        output_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #dee2e6; "
            "border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }"
        )
        output_layout = QVBoxLayout(output_group)
        output_layout.setContentsMargins(8, 8, 8, 8)
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px; "
            "border: 1px solid #3c3c3c; border-radius: 4px; padding: 8px; }"
        )
        output_layout.addWidget(self.output_text)
        main_layout.addWidget(output_group, 1)

        bottom_layout = QHBoxLayout()
        self.back_btn = QPushButton("← 返回画框")
        self.back_btn.setStyleSheet(
            "QPushButton { background-color: #6c757d; color: white; "
            "min-height: 44px; min-width: 120px; padding: 10px 30px; "
            "border: none; border-radius: 6px; font-size: 14px; }"
            "QPushButton:hover { background-color: #5a6268; }"
            "QPushButton:pressed { background-color: #545b62; }"
        )
        self.back_btn.clicked.connect(self._on_back)
        bottom_layout.addWidget(self.back_btn)
        bottom_layout.addStretch()
        self.next_btn = QPushButton("新书制作")
        self.next_btn.setEnabled(False)
        self.next_btn.setStyleSheet(
            "QPushButton { background-color: #0D6EFD; color: white; "
            "min-height: 44px; min-width: 120px; padding: 10px 30px; "
            "border: none; border-radius: 6px; font-size: 14px; }"
            "QPushButton:hover { background-color: #0b5ed7; }"
            "QPushButton:disabled { background-color: #6c757d; }"
        )
        self.next_btn.clicked.connect(self._on_next)
        bottom_layout.addWidget(self.next_btn)
        main_layout.addLayout(bottom_layout)

    def _on_pdf_path_changed(self, text):
        """PDF文件路径变更时的处理槽函数。

        当用户在PDF路径输入框中修改文本时，同步更新内部保存的PDF路径。

        Args:
            text (str): PDF路径输入框中的当前文本内容。

        调用关系:
            由 pdf_path_edit.textChanged 信号触发。
        """
        self.pdf_path = text.strip()

    def _on_browse_pdf(self):
        """浏览选择PDF文件的槽函数。

        打开文件选择对话框，允许用户选择PDF文件。选择后将路径填入
        PDF路径输入框并更新内部保存的PDF路径。

        调用关系:
            由 browse_pdf_btn.clicked 信号触发。

        依赖:
            PyQt6.QFileDialog: 提供文件选择对话框。
        """
        pdf_path, _ = QFileDialog.getOpenFileName(
            self, "选择PDF文件", "", "PDF文件 (*.pdf)"
        )
        if pdf_path:
            self.pdf_path_edit.setText(pdf_path)
            self.pdf_path = pdf_path

    def _on_browse_lines(self):
        """浏览选择Lines JSON文件的槽函数。

        打开文件选择对话框，允许用户选择Lines JSON文件。选择后将路径填入
        Lines路径输入框，并自动推断同目录下是否存在 chars.json 文件，
        若存在则自动填入Chars路径。最后检查下一步按钮是否可用。

        调用关系:
            由 browse_lines_btn.clicked 信号触发。
            内部调用 _check_next_enabled 检查下一步按钮状态。

        依赖:
            PyQt6.QFileDialog: 提供文件选择对话框。
            os: 用于路径目录推断。
        """
        lines_path, _ = QFileDialog.getOpenFileName(
            self, "选择Lines JSON文件", "", "JSON文件 (*.json)"
        )
        if lines_path:
            self.lines_path_edit.setText(lines_path)
            import os
            dir_path = os.path.dirname(lines_path)
            chars_path = os.path.join(dir_path, "chars.json")
            if os.path.exists(chars_path):
                self.chars_path_edit.setText(chars_path)
            self._check_next_enabled()

    def _on_browse_chars(self):
        """浏览选择Chars JSON文件的槽函数。

        打开文件选择对话框，允许用户选择Chars JSON文件。选择后将路径
        填入Chars路径输入框，并检查下一步按钮是否可用。

        调用关系:
            由 browse_chars_btn.clicked 信号触发。
            内部调用 _check_next_enabled 检查下一步按钮状态。

        依赖:
            PyQt6.QFileDialog: 提供文件选择对话框。
        """
        chars_path, _ = QFileDialog.getOpenFileName(
            self, "选择Chars JSON文件", "", "JSON文件 (*.json)"
        )
        if chars_path:
            self.chars_path_edit.setText(chars_path)
            self._check_next_enabled()

    def _check_next_enabled(self):
        """检查并更新下一步按钮的可用状态。

        当Lines JSON和Chars JSON路径均已填写时启用下一步按钮，
        否则禁用下一步按钮。

        调用关系:
            被 _on_browse_lines、_on_browse_chars、_on_ocr_finished 调用。
        """
        has_lines = bool(self.lines_path_edit.text().strip())
        has_chars = bool(self.chars_path_edit.text().strip())
        self.next_btn.setEnabled(has_lines and has_chars)

    def _on_run_ocr(self):
        """执行OCR识别的槽函数。

        验证PDF路径是否已填写后，创建OCRWorker并将其移入QThread子线程中执行
        OCR识别任务。执行期间禁用OCR按钮，清空输出区域，并连接Worker的输出、
        完成和错误信号到对应的槽函数。若OCR正在运行中则忽略重复触发。

        调用关系:
            由 run_ocr_btn.clicked 信号触发。
            内部创建 OCRWorker 实例并启动 ocr_thread。

        依赖:
            PyQt6.QThread: 提供子线程支持。
            PyQt6.QMessageBox: 提供警告对话框。
            OCRWorker: OCR识别工作线程Worker对象。
            os: 用于推断输出目录。
        """
        if self._ocr_running:
            return
        if not self.pdf_path:
            QMessageBox.warning(self, "提示", "请先输入或选择PDF文件")
            return
        self._ocr_running = True
        self.run_ocr_btn.setEnabled(False)
        self.output_text.clear()
        self._append_output(f"开始执行 RapidOCR 识别: {self.pdf_path}")

        import os
        main_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        output_dir = os.path.join(main_dir, "json")
        os.makedirs(output_dir, exist_ok=True)

        self.ocr_thread = QThread()
        self.ocr_worker = OCRWorker(self.pdf_path, output_dir, self.ocr_engine, self.regions)
        self.ocr_worker.moveToThread(self.ocr_thread)

        self.ocr_worker.output_signal.connect(self._append_output)
        self.ocr_worker.finished_signal.connect(self._on_ocr_finished)
        self.ocr_worker.error_signal.connect(self._on_ocr_error)
        self.ocr_thread.started.connect(self.ocr_worker.run)

        self.ocr_thread.start()

    def _on_ocr_finished(self, results, output_dir):
        """OCR识别完成的处理槽函数。

        恢复OCR运行状态和按钮可用性，根据输出目录和PDF文件名推断
        lines.json 和 chars.json 的路径并自动填入对应的输入框，
        然后检查下一步按钮是否可用。

        Args:
            results (tuple): OCR识别结果元组。
            output_dir (str): OCR识别结果的输出目录路径。

        调用关系:
            由 ocr_worker.finished_signal 信号触发。
            内部调用 _check_next_enabled 检查下一步按钮状态。

        依赖:
            os: 用于推断JSON结果文件路径。
        """
        self._ocr_running = False
        self.run_ocr_btn.setEnabled(True)
        import os
        pdf_basename = os.path.splitext(os.path.basename(self.pdf_path))[0]
        json_dir = os.path.join(output_dir, pdf_basename)
        lines_path = os.path.join(json_dir, "lines.json")
        chars_path = os.path.join(json_dir, "chars.json")
        self.lines_path_edit.setText(lines_path)
        self.chars_path_edit.setText(chars_path)
        self._check_next_enabled()
        self._append_output(f"\nOCR识别完成！结果已保存至: {json_dir}")

    def _on_ocr_error(self, error_msg):
        """OCR识别错误的处理槽函数。

        恢复OCR运行状态和按钮可用性，在输出区域显示错误信息，
        并弹出错误对话框通知用户。

        Args:
            error_msg (str): OCR执行过程中的错误信息。

        调用关系:
            由 ocr_worker.error_signal 信号触发。

        依赖:
            PyQt6.QMessageBox: 提供错误对话框。
        """
        self._ocr_running = False
        self.run_ocr_btn.setEnabled(True)
        self._append_output(f"\n错误: {error_msg}")
        QMessageBox.critical(self, "OCR执行失败", error_msg)

    def _append_output(self, text):
        """向CMD输出区域追加文本的槽函数。

        将文本追加到输出文本框的末尾，并自动滚动到最新输出位置，
        确保用户能够实时查看OCR执行和数据加载的日志信息。

        Args:
            text (str): 待追加的文本内容。

        调用关系:
            由 ocr_worker.output_signal 和 data_worker.progress_signal 信号触发。

        依赖:
            PyQt6.QGui.QTextCursor: 用于移动光标到文本末尾。
        """
        self.output_text.moveCursor(QTextCursor.MoveOperation.End)
        self.output_text.insertPlainText(text + "\n")
        self.output_text.ensureCursorVisible()

    def _on_next(self):
        """进入下一步的槽函数。

        验证Lines JSON、Chars JSON和PDF路径是否均已填写后，创建
        DataLoadWorker并将其移入QThread子线程中执行数据加载任务。
        加载期间禁用下一步和OCR按钮，并连接Worker的进度、完成和错误
        信号到对应的槽函数。

        调用关系:
            由 next_btn.clicked 信号触发。
            内部创建 DataLoadWorker 实例并启动 _data_thread。

        依赖:
            PyQt6.QThread: 提供子线程支持。
            PyQt6.QMessageBox: 提供警告对话框。
            DataLoadWorker: 数据加载工作线程Worker对象。
        """
        lines_path = self.lines_path_edit.text().strip()
        chars_path = self.chars_path_edit.text().strip()
        if not lines_path or not chars_path:
            QMessageBox.warning(self, "提示", "请先选择或生成 lines.json 和 chars.json")
            return
        if not self.pdf_path:
            QMessageBox.warning(self, "提示", "请先输入或选择PDF文件")
            return

        self.next_btn.setEnabled(False)
        self.run_ocr_btn.setEnabled(False)

        self._data_thread = QThread()
        self._data_worker = DataLoadWorker(
            self.pdf_path, lines_path, chars_path,
            self.ocr_engine, self.pdf_processor
        )
        self._data_worker.moveToThread(self._data_thread)
        self._data_thread.started.connect(self._data_worker.run)
        self._data_worker.progress_signal.connect(self._append_output)
        self._data_worker.finished_signal.connect(self._on_data_loaded)
        self._data_worker.error_signal.connect(self._on_data_error)
        self._data_thread.start()

    def _on_data_loaded(self, page_images, results, char_slices):
        """数据加载完成的处理槽函数。

        清理数据加载线程，恢复按钮可用性，在输出区域显示准备信息，
        并通过 finished_signal 将加载的数据传递给主窗口以进入纵校阶段。

        Args:
            page_images (list): PDF页面图像列表。
            results (tuple): OCR识别结果元组。
            char_slices (dict): 字符切片分组字典，键为字符，值为切片列表。

        Emits:
            finished_signal(list, tuple, dict): 发射页面图像列表、OCR结果元组
                和字符切片分组字典，通知主窗口进入纵校阶段。

        调用关系:
            由 data_worker.finished_signal 信号触发。
            内部调用 _cleanup_data_thread 清理数据加载线程。
        """
        self._cleanup_data_thread()
        self.next_btn.setEnabled(True)
        self.run_ocr_btn.setEnabled(True)
        self._append_output("准备进入纵校...")
        self.finished_signal.emit(page_images, results, char_slices)

    def _on_data_error(self, error_msg):
        """数据加载错误的处理槽函数。

        清理数据加载线程，恢复按钮可用性，在输出区域显示错误信息，
        并弹出错误对话框通知用户。

        Args:
            error_msg (str): 数据加载过程中的错误信息。

        调用关系:
            由 data_worker.error_signal 信号触发。
            内部调用 _cleanup_data_thread 清理数据加载线程。

        依赖:
            PyQt6.QMessageBox: 提供错误对话框。
        """
        self._cleanup_data_thread()
        self.next_btn.setEnabled(True)
        self.run_ocr_btn.setEnabled(True)
        self._append_output(f"\n错误: {error_msg}")
        QMessageBox.critical(self, "错误", error_msg)

    def _cleanup_data_thread(self):
        """清理数据加载线程和Worker对象。

        若数据加载线程仍在运行，则请求退出并等待最多3秒；
        线程结束后将线程和Worker引用置为None，释放资源。

        调用关系:
            被 _on_data_loaded 和 _on_data_error 调用。
        """
        if hasattr(self, '_data_thread') and self._data_thread is not None:
            if self._data_thread.isRunning():
                self._data_thread.quit()
                self._data_thread.wait(3000)
            self._data_thread = None
            self._data_worker = None

    def _on_back(self):
        """处理返回按钮点击事件，发射返回信号。

        调用关系:
            由 back_btn.clicked 信号触发，发射 back_signal。
        """
        self.back_signal.emit()

    def cleanup(self):
        """清理所有工作线程和Worker对象，释放资源。

        依次清理OCR线程和数据加载线程。若线程仍在运行，则请求退出
        并等待最多3秒；线程结束后将线程和Worker引用置为None。
        该方法应在窗口关闭或阶段切换时调用。

        调用关系:
            被 MainWindow._on_prepare_finished 和
            MainWindow._on_refine_finished 调用。
            内部调用 _cleanup_data_thread 清理数据加载线程。
        """
        if self.ocr_thread is not None:
            if self.ocr_thread.isRunning():
                self.ocr_thread.quit()
                self.ocr_thread.wait(3000)
            self.ocr_thread = None
            self.ocr_worker = None
        self._cleanup_data_thread()
