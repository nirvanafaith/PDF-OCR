"""OCR 识别进度对话框模块。

本模块定义 ProgressDialog 类，用于在 OCR 识别过程中显示按页推进的
进度条与详细日志。对话框以应用模态形式弹出，阻止用户操作主窗口，
并通过 cancel_signal 信号支持取消 OCR 任务。

主要由主线程连接 OCR Worker 的进度信号到 update_progress / append_log
槽函数，OCR 完成后通过 finish() 方法延迟关闭对话框。
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QTextEdit,
    QPushButton, QHBoxLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer


class ProgressDialog(QDialog):
    """OCR 识别进度对话框，显示按页推进的进度条与详细日志。

    通过 update_progress / append_log 方法由主线程接收 OCR Worker 的进度信号，
    在 OCR 完成后通过 finish() 方法延迟关闭对话框。
    """

    cancel_signal = pyqtSignal()  # 取消信号，主线程连接后可中断 OCR 任务

    def __init__(self, total_pages: int, parent=None):
        super().__init__(parent)
        self.total_pages = total_pages
        self._finished = False  # 防止 finish() 重复调用
        self.setWindowTitle("OCR 识别进度")
        self.setFixedWidth(600)
        self.setMinimumHeight(400)
        # 设置为应用模态，防止用户操作主窗口
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # 阻止按 X 按钮关闭（强制走取消按钮）
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        self._init_ui()

    def _init_ui(self):
        """初始化对话框界面布局与控件。"""
        # 主垂直布局
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 顶部状态标签
        self.status_label = QLabel("准备开始 OCR 识别...")
        self.status_label.setStyleSheet(
            "font-size: 14px; font-weight: bold;"
        )
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total_pages)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(24)
        layout.addWidget(self.progress_bar)

        # 日志文本框（深色背景）
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
            "font-family: Consolas, 'Courier New', monospace; font-size: 12px; "
            "border: 1px solid #3c3c3c; border-radius: 4px; padding: 8px; }"
        )
        layout.addWidget(self.log_text)

        # 底部按钮区域（右对齐）
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setStyleSheet(
            "QPushButton { background-color: #6c757d; color: white; "
            "min-height: 32px; min-width: 100px; padding: 6px 20px; "
            "border: none; border-radius: 4px; font-size: 13px; }"
            "QPushButton:hover { background-color: #5a6268; }"
            "QPushButton:disabled { background-color: #adb5bd; }"
        )
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def update_progress(self, current: int, total: int, status: str):
        """更新进度条与状态文本（主线程槽函数调用）。"""
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.status_label.setText(status)

    def append_log(self, text: str):
        """追加一行日志到 QTextEdit（主线程槽函数调用）。"""
        self.log_text.append(text)

    def finish(self):
        """OCR 完成，延迟 1 秒后自动关闭对话框。

        延迟目的是让用户看到最后一条日志与 100% 进度。
        防止重复调用（self._finished 标志）。
        """
        if self._finished:
            return
        self._finished = True
        self.cancel_btn.setText("完成")
        self.cancel_btn.setEnabled(True)
        # 1 秒后自动关闭
        QTimer.singleShot(1000, self.accept)

    def _on_cancel(self):
        """取消按钮点击：禁用按钮防重复点击，发射 cancel_signal。"""
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("取消中...")
        self.cancel_signal.emit()
