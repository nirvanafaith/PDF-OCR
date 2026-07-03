"""测试ImportWindow的跨线程加载流程。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from ui.import_window import ImportWindow

pdf_path = r"c:\Users\E-VR\Documents\trae_projects\横校\软件1\json\金融与生活97871133261660000（1-1）\金融与生活97871133261660000（1-1）.pdf"
lines_path = r"c:\Users\E-VR\Documents\trae_projects\横校\软件1\json\金融与生活97871133261660000（1-1）\lines.json"
chars_path = r"c:\Users\E-VR\Documents\trae_projects\横校\软件1\json\金融与生活97871133261660000（1-1）\chars.json"

app = QApplication(sys.argv)

window = ImportWindow()
window.pdf_path_edit.setText(pdf_path)
window.lines_path_edit.setText(lines_path)
window.chars_path_edit.setText(chars_path)
window._check_load_enabled()

results = {}

def on_finished(page_images, ocr_results, char_slices):
    results["page_images"] = len(page_images)
    results["lines"] = len(ocr_results[0])
    results["chars"] = len(ocr_results[1])
    results["slices"] = sum(len(v) for v in char_slices.values())
    print(f"完成: {results}")
    app.quit()

def on_error(msg):
    print(f"错误: {msg}")
    app.quit()

window.finished_signal.connect(on_finished)
window._worker = None  # 确保 _on_load 创建新 worker

# 延迟点击加载
QTimer.singleShot(100, window._on_load)

# 连接错误信号需要等 worker 创建，这里简化：不连错误信号，看是否崩溃

print("启动事件循环，即将点击加载...")
app.exec()
