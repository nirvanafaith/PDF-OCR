"""应用程序全局 QSS 样式表模块。

本模块定义了纵校应用程序统一的 PyQt5 QSS 样式常量与获取接口，
确保所有窗口（主窗口、纵校窗口、横校窗口、精修窗口、OCR 准备窗口）
共享一致的视觉风格。样式基于 Bootstrap 5 配色方案，提供简洁、
现代的界面外观。

样式覆盖的控件包括：
    - QMainWindow：主窗口背景
    - QListWidget：列表控件及其子项（含选中、悬停状态）
    - QPushButton：通用按钮（含悬停、按下、禁用状态）
    - QToolBar：工具栏及工具栏内嵌按钮（含选中状态）
    - QScrollArea / QGraphicsView：滚动区域与图形视图
    - QSpinBox / QLineEdit：数值与文本输入控件（含聚焦状态）
    - QDialog / QLabel / QMenu：对话框、标签与右键菜单
"""

"""应用程序全局 QSS 样式表常量。

基于 Bootstrap 5 配色方案，为纵校应用程序所有窗口提供统一的视觉风格。
涵盖主窗口、列表控件、按钮、工具栏、滚动区域、图形视图、输入控件、
对话框、标签及右键菜单等控件的样式定义，包括各交互状态
（悬停、按下、选中、禁用、聚焦）的视觉反馈。

被以下窗口初始化方法调用以加载样式：
    - MainWindow.__init__
    - VerticalCheckWindow._init_ui
    - HorizontalCheckWindow._init_ui
    - RefineWindow._init_ui
    - OCRPrepareWindow.__init__
"""
MAIN_STYLESHEET = """
QMainWindow {
    background-color: #d4d0c8;
}

QListWidget {
    background-color: #ffffff;
    border: 1px solid #808080;
    border-radius: 0px;
    font-size: 14px;
    padding: 4px;
}

QListWidget::item {
    padding: 8px 12px;
    border-bottom: 1px solid #c0c0c0;
}

QListWidget::item:selected {
    background-color: #316ac5;
    color: white;
}

QListWidget::item:hover {
    background-color: #e8e4dc;
}

QListWidget::item:selected:hover {
    background-color: #2a5ab8;
    color: white;
}

QPushButton {
    background-color: #d4d0c8;
    color: #000000;
    border: 2px outset #ffffff;
    border-radius: 0px;
    padding: 8px 16px;
    font-size: 13px;
    min-height: 32px;
}

QPushButton:hover {
    background-color: #e8e4dc;
    border-style: outset;
}

QPushButton:pressed {
    background-color: #c0bcb4;
    border-style: inset;
}

QPushButton:disabled {
    background-color: #c0c0c0;
    color: #808080;
}

QToolBar {
    background-color: #d4d0c8;
    border-bottom: 1px solid #808080;
    padding: 4px 8px;
    spacing: 6px;
}

QToolBar QPushButton {
    background-color: #d4d0c8;
    color: #000000;
    border: 1px solid #808080;
    border-radius: 0px;
    padding: 4px 12px;
    font-size: 12px;
    min-height: 28px;
}

QToolBar QPushButton:hover {
    background-color: #e8e4dc;
    border-color: #404040;
}

QToolBar QPushButton:pressed {
    background-color: #c0bcb4;
    border-style: inset;
}

QToolBar QPushButton:checked {
    background-color: #b0b0b0;
    color: #000000;
    border-color: #404040;
    border-style: inset;
}

QScrollArea {
    border: none;
    background-color: #d4d0c8;
}

QGraphicsView {
    border: 1px solid #808080;
    background-color: #ffffff;
}

QSpinBox {
    border: 1px solid #808080;
    border-radius: 0px;
    padding: 2px 8px;
    font-size: 12px;
    min-height: 28px;
    background-color: #ffffff;
}

QLineEdit {
    border: 1px solid #808080;
    border-radius: 0px;
    padding: 6px 10px;
    font-size: 13px;
    background-color: #ffffff;
}

QLineEdit:focus {
    border-color: #316ac5;
}

QDialog {
    background-color: #d4d0c8;
}

QLabel {
    color: #000000;
    font-size: 13px;
}

QMenu {
    background-color: #d4d0c8;
    border: 1px solid #808080;
    border-radius: 0px;
    padding: 4px 0px;
}

QMenu::item {
    padding: 6px 24px;
}

QMenu::item:selected {
    background-color: #316ac5;
    color: white;
}

QProgressDialog {
    background-color: #d4d0c8;
}

QProgressDialog QLabel {
    color: #000000;
    font-size: 13px;
}

QProgressBar {
    border: 1px solid #808080;
    border-radius: 0px;
    text-align: center;
    background-color: #c0c0c0;
    min-height: 20px;
}

QProgressBar::chunk {
    background-color: #316ac5;
    border-radius: 0px;
}

QGroupBox {
    font-weight: bold;
    border: 1px solid #808080;
    border-radius: 0px;
    margin-top: 12px;
    padding-top: 8px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
}

QTextEdit {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 12px;
    border: 1px solid #808080;
    border-radius: 0px;
    padding: 8px;
}

/* SliceItemWidget 状态样式 */
SliceItemWidget[state="normal"] {
    border: 1px solid #dee2e6;
    border-radius: 4px;
    background-color: #ffffff;
}
SliceItemWidget[state="normal"]:hover {
    border: 2px solid #0D6EFD;
    background-color: #e7f1ff;
}
SliceItemWidget[state="selected"] {
    border: 2px solid #0D6EFD;
    border-radius: 4px;
    background-color: #cfe2ff;
}
SliceItemWidget[state="selected"]:hover {
    border: 2px solid #0b5ed7;
    background-color: #b6d4fe;
}
SliceItemWidget[state="warn"] {
    border: 1px solid #ffc107;
    border-radius: 4px;
    background-color: #fff3cd;
}
SliceItemWidget[state="warn"]:hover {
    border: 2px solid #0D6EFD;
    background-color: #e7f1ff;
}
"""


def get_stylesheet():
    """获取应用程序全局 QSS 样式表。

    返回 MAIN_STYLESHEET 常量中定义的完整样式表字符串，
    用于通过 QWidget.setStyleSheet() 方法应用到窗口或控件上。

    Returns:
        str: 应用程序全局 QSS 样式表字符串。

    示例::

        stylesheet = get_stylesheet()
        window.setStyleSheet(stylesheet)
    """
    return MAIN_STYLESHEET