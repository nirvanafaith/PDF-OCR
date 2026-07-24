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
from PyQt6.QtCore import pyqtSignal

from ui.styles import get_stylesheet


class ImportWindow(QWidget):
    """导入窗口（第一阶段）：选择PDF文件并触发OCR识别。

    该窗口是软件3的第一阶段界面，用户在此选择待识别的PDF文件，
    点击"开始识别"按钮后通过信号通知主窗口执行后续OCR流程。

    信号:
        start_ocr_signal (pyqtSignal(str)): 开始识别信号，携带PDF文件路径。

    依赖:
        ui.styles.get_stylesheet: 全局样式表。
    """

    start_ocr_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        """初始化导入窗口。

        Args:
            parent (QWidget, optional): 父窗口对象，默认为None。

        调用关系:
            内部调用 _init_ui 构建界面。
        """
        super().__init__(parent)
        self.pdf_path = ""
        self.setStyleSheet(get_stylesheet())
        self._init_ui()

    def _init_ui(self):
        """构建导入窗口的UI界面。

        界面包含以下区域：
        - 文件设置分组：PDF文件路径选择；
        - 操作分组：开始识别按钮；
        - CMD输出分组：实时显示日志输出。

        调用关系:
            被 __init__ 调用。
        """
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(16)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 文件设置分组
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
        self.pdf_path_edit.setMinimumHeight(36)
        pdf_row.addWidget(self.pdf_path_edit, 1)
        self.browse_pdf_btn = QPushButton("选择PDF")
        self.browse_pdf_btn.setFixedWidth(100)
        self.browse_pdf_btn.setMinimumHeight(36)
        self.browse_pdf_btn.clicked.connect(self._on_browse_pdf)
        pdf_row.addWidget(self.browse_pdf_btn)
        file_layout.addLayout(pdf_row)

        main_layout.addWidget(file_group)

        # 操作分组
        action_group = QGroupBox("操作")
        action_group.setStyleSheet(
            "QGroupBox { font-weight: bold; border: 1px solid #dee2e6; "
            "border-radius: 6px; margin-top: 12px; padding-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 8px; }"
        )
        action_layout = QVBoxLayout(action_group)

        # 开始识别按钮（居中）
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.start_ocr_btn = QPushButton("开始识别")
        self.start_ocr_btn.setStyleSheet(
            "QPushButton { background-color: #0D6EFD; color: white; "
            "min-height: 44px; min-width: 180px; padding: 10px 30px; "
            "border: none; border-radius: 6px; font-size: 14px; }"
            "QPushButton:hover { background-color: #0b5ed7; }"
            "QPushButton:disabled { background-color: #6c757d; }"
        )
        self.start_ocr_btn.clicked.connect(self._on_start_ocr)
        btn_row.addWidget(self.start_ocr_btn)
        btn_row.addStretch()
        action_layout.addLayout(btn_row)
        main_layout.addWidget(action_group)

        # CMD输出分组
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

    def _on_start_ocr(self):
        """开始识别的槽函数。

        若PDF路径为空则弹出警告提示用户先选择PDF文件，否则通过
        start_ocr_signal 发射PDF路径，通知主窗口执行OCR识别。

        Emits:
            start_ocr_signal(str): 携带PDF文件路径。

        调用关系:
            由 start_ocr_btn.clicked 信号触发。

        依赖:
            PyQt6.QMessageBox: 提供警告对话框。
        """
        if not self.pdf_path:
            QMessageBox.warning(self, "提示", "请先选择 PDF 文件")
            return
        self.start_ocr_signal.emit(self.pdf_path)

    def append_output(self, text: str):
        """向CMD输出区域追加文本。

        使用 QTextEdit.append 方法将文本作为新段落追加，自动换行，
        便于主窗口在OCR执行过程中实时输出日志。

        Args:
            text (str): 待追加的文本内容。
        """
        self.output_text.append(text)
