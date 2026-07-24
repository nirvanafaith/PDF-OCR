# -*- coding: utf-8 -*-
"""software3 入口模块：矢量字形 PDF 整行 OCR + 红字嵌字。

启动 PyQt6 主窗口，编排两阶段流程：
    Stage 1 (导入)：ImportWindow 选择 PDF，触发 OCRTaskWorker
    Stage 2 (结果)：ResultWindow 显示嵌入红字后的输出 PDF

OCRTaskWorker 在独立 QThread 中调用 ParallelOCRRunner：
    Pass 1（页面级并行）→ 提取 drawings、分行、整行 OCR、保存元素图片
    Pass 2（主线程串行）→ 规则消歧、红字嵌字、行审计、IoU 验证
    最后由 worker 负责保存输出 PDF。

依赖：
    - cuda_dll_setup: CUDA DLL 路径设置（必须在 onnxruntime 之前调用）
    - ocr_engine.parallel_runner.ParallelOCRRunner: 页面级并行 OCR 调度器
    - ui.import_window.ImportWindow / ui.progress_dialog.ProgressDialog
    - ui.result_window.ResultWindow / ui.styles.get_stylesheet
"""

import os
import sys
import time

import fitz
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStackedWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtGui import QFont

# 确保能导入 software3 内部包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cuda_dll_setup import setup_cuda_dll_paths
setup_cuda_dll_paths()  # 必须在导入 onnxruntime 之前调用

from ui.import_window import ImportWindow
from ui.progress_dialog import ProgressDialog
from ui.result_window import ResultWindow
from ui.styles import get_stylesheet
from ocr_engine.parallel_runner import ParallelOCRRunner


class StepIndicator(QWidget):
    """步骤指示器组件，水平显示当前所处的处理阶段。

    当前阶段高亮（蓝色 #0D6EFD），已完成阶段绿色（#198754），
    未到阶段灰色（#e9ecef）。阶段间用 "→" 箭头连接。
    """

    def __init__(self, steps: list, parent=None):
        """初始化步骤指示器。

        Args:
            steps: 阶段标签文本列表，如 ["导入", "结果"]。
            parent: 父组件，默认为 None。
        """
        super().__init__(parent)
        self.steps = steps
        self.current = 0
        self.setFixedHeight(50)
        self._init_ui()

    def _init_ui(self):
        """构建指示器界面：横向排列阶段标签与箭头。"""
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

    def set_current_stage(self, stage_idx: int):
        """设置当前所处阶段，更新各阶段标签样式。

        Args:
            stage_idx: 当前阶段索引（0-based）。小于该索引的标记为已完成，
                等于该索引的标记为活动，大于的标记为未到。
        """
        self.current = stage_idx
        for i, label in enumerate(self.labels):
            if i < stage_idx:
                self._set_done_style(label)
            elif i == stage_idx:
                self._set_active_style(label)
            else:
                self._set_inactive_style(label)


class OCRTaskWorker(QObject):
    """OCR 任务 Worker，在 QThread 中执行页面级并行 OCR。

    封装 ParallelOCRRunner 的两阶段调度（Pass 1 并行 + Pass 2 串行），
    通过 Qt 信号向主线程上报进度、日志、完成、错误与 GPU 可用性。

    信号:
        progress_signal(int, int, str): 进度回调，参数为 (current, total, status)。
        log_signal(str): 日志文本，主线程追加到进度对话框与导入窗口输出区。
        finished_signal(str): OCR 完成信号，携带输出 PDF 路径。
        error_signal(str): 错误信号，携带错误描述。
        engine_ready_signal(bool): 引擎就绪信号，True 表示 GPU 可用。

    线程安全说明:
        log_signal.emit 通过 Qt 的跨线程队列连接安全地转发到主线程，
        即使被 Pass 1 的 worker 线程间接调用也无须加锁。
    """

    progress_signal = pyqtSignal(int, int, str)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    engine_ready_signal = pyqtSignal(bool)

    def __init__(self, pdf_path, max_workers=10):
        """初始化 OCR Worker。

        Args:
            pdf_path: 输入 PDF 文件路径。
            max_workers: Pass 1 阶段最大并行 worker 数，实际取
                min(max_workers, total_pages) 由 run() 决定。
                默认 10：12GB 显存 GPU 每实例约 800MB 显存，
                可承载 ~12 个 worker，留余量取 10。
        """
        super().__init__()
        self.pdf_path = pdf_path
        self.max_workers = max_workers
        self.runner = None
        self._cancelled = False
        # 输出 PDF：在原文件名后加 "_红字叠加" 后缀
        base, ext = os.path.splitext(pdf_path)
        self.output_pdf = f"{base}_红字叠加{ext}"
        # 元素图片输出目录：PDF 同目录下 _char_elements_line 子目录
        self.elements_dir = os.path.join(
            os.path.dirname(pdf_path), '_char_elements_line'
        )

    def run(self):
        """执行 OCR 任务（在 QThread 中调用）。

        流程：
            1. 打开 PDF，获取总页数
            2. 创建 ParallelOCRRunner 并准备引擎
            3. Pass 1：页面级并行 OCR
            4. Pass 2：主线程串行后处理（红字嵌字等）
            5. 保存输出 PDF
        异常时发射 error_signal，无论成功与否最终 shutdown runner。
        """
        doc = None
        try:
            self.log_signal.emit("开始处理...")
            t0 = time.time()

            doc = fitz.open(self.pdf_path)
            total_pages = len(doc)
            self.log_signal.emit(f"PDF 共 {total_pages} 页")

            self.runner = ParallelOCRRunner(
                max_workers=min(self.max_workers, total_pages)
            )
            self.runner.prepare_engines()
            engines = self.runner._engines
            cuda_available = bool(
                getattr(engines[0], '_has_cuda', False)
            ) if engines else False
            self.engine_ready_signal.emit(cuda_available)
            self.log_signal.emit(f"已准备 {len(engines)} 个 OCR 引擎")

            # 数值进度回调闭包：
            # Pass 1 (0-50%) → Pass 1.5 (50-65%) → Pass 2+3 (65-100%)
            def _pass1_progress(current, total, status):
                combined_current = int(current * 50 / max(total, 1))
                self.progress_signal.emit(combined_current, 100, status)

            def _pass15_progress(current, total, status):
                combined_current = 50 + int(current * 15 / max(total, 1))
                self.progress_signal.emit(combined_current, 100, status)

            def _pass2_progress(current, total, status):
                combined_current = 65 + int(current * 35 / max(total, 1))
                self.progress_signal.emit(combined_current, 100, status)

            # Pass 1：页面级并行 OCR（0-50%）
            self.progress_signal.emit(0, 100, "准备 Pass 1...")
            page_indices = list(range(total_pages))
            all_page_results = self.runner.run_pass1_parallel(
                doc, page_indices, self.elements_dir,
                output_callback=lambda msg: self.log_signal.emit(msg),
                progress_callback=_pass1_progress,
            )
            self.log_signal.emit(
                f"Pass 1 完成，共 {len(all_page_results)} 页结果"
            )

            # Pass 1.5：全局字符级并行渲染 + C++ 批量特征提取 + 逐页决策（50-65%）
            # 优先使用新方法（C++ 加速 + 并行多发），异常时自动回落到 run_pass15_parallel
            self.progress_signal.emit(50, 100, "准备 Pass 1.5...")
            stat15 = self.runner.run_pass15_global_char_parallel(
                doc, all_page_results, self.elements_dir,
                output_callback=lambda msg: self.log_signal.emit(msg),
                progress_callback=_pass15_progress,
            )
            self.log_signal.emit(
                f"Pass 1.5 完成：修正 {stat15.get('total_fix', 0)} 个误识字符"
            )

            # Pass 2+3：主线程串行写入红字 + 行审计（65-85%）
            self.progress_signal.emit(65, 100, "准备 Pass 2...")
            stat2 = self.runner.run_pass2_write_serial(
                doc, all_page_results, self.elements_dir,
                output_callback=lambda msg: self.log_signal.emit(msg),
                progress_callback=_pass2_progress,
            )
            self.log_signal.emit(
                f"Pass 2 完成：字符 {stat2.get('total_chars', 0)}，"
                f"成功 {stat2.get('total_success', 0)}，"
            )

            self.progress_signal.emit(100, 100, "OCR 完成")

            # 合并 stats（向后兼容旧字段名）
            stats = {
                'total_pages': len(all_page_results),
                'total_chars': stat2.get('total_chars', 0),
                'total_success': stat2.get('total_success', 0),
                'total_fix': stat15.get('total_fix', 0),
                'elapsed': stat15.get('elapsed', 0) + stat2.get('elapsed', 0),
            }

            # 保存输出 PDF
            doc.save(self.output_pdf, garbage=4, deflate=True)
            doc.close()
            doc = None

            self.log_signal.emit(f"输出 PDF: {self.output_pdf}")
            self.log_signal.emit(f"总耗时: {time.time() - t0:.1f}s")
            self.finished_signal.emit(self.output_pdf)
        except Exception as e:
            self.error_signal.emit(str(e))
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
        finally:
            if self.runner:
                self.runner.shutdown()

    def cancel(self):
        """请求取消 OCR 任务。

        设置取消标志，runner 在提交下一页前检查并停止提交新 task，
        已提交的 task 会自然完成。Pass 2 在每页处理前检查并跳过剩余页。
        """
        self._cancelled = True
        if self.runner:
            self.runner.cancel()


class MainWindow(QMainWindow):
    """应用程序主窗口，管理导入→结果两阶段流程。

    Stage 1 (导入)：ImportWindow 选择 PDF 并触发 OCR
    Stage 2 (结果)：ResultWindow 显示嵌入红字后的输出 PDF

    OCR 在独立 QThread 中执行，通过 OCRTaskWorker 上报进度。
    """

    STAGES = ["导入", "结果"]

    def __init__(self):
        """初始化主窗口：构建步骤指示器与堆叠窗口，连接阶段间信号。"""
        super().__init__()
        self.setWindowTitle("software3 - 矢量PDF整行OCR红字嵌字")
        self.resize(1200, 800)
        self.setStyleSheet(get_stylesheet())

        self.worker = None
        self.ocr_thread = None
        self.progress_dialog = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部步骤指示器
        self.step_indicator = StepIndicator(self.STAGES)
        layout.addWidget(self.step_indicator)

        # 堆叠窗口：Stage 1 = ImportWindow, Stage 2 = ResultWindow
        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget, 1)

        self.import_window = ImportWindow()
        self.result_window = ResultWindow()
        self.stacked_widget.addWidget(self.import_window)   # index 0
        self.stacked_widget.addWidget(self.result_window)   # index 1

        # 阶段间信号连接
        self.import_window.start_ocr_signal.connect(self._on_start_ocr)
        self.result_window.restart_signal.connect(self._on_restart)

        self.stacked_widget.setCurrentIndex(0)
        self.step_indicator.set_current_stage(0)

    def _on_start_ocr(self, pdf_path):
        """开始 OCR：校验路径、创建进度对话框与 Worker、启动 QThread。

        Args:
            pdf_path: 从 ImportWindow.start_ocr_signal 传入的路径。
                实际仍以 pdf_path_edit.text() 为准，防止用户手动输入
                后未点浏览导致 self.pdf_path 未更新。
        """
        # 以输入框文本为准，防止用户手动输入后未点浏览
        pdf_path = self.import_window.pdf_path_edit.text().strip()
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(
                self, "提示", "PDF 文件路径为空或不存在，请重新选择。"
            )
            return

        # ProgressDialog 需要 total_pages，此时尚未打开 PDF；传入占位值 1，
        # update_progress 会通过 setRange(0, total) 动态校正实际总页数。
        progress_dialog = ProgressDialog(total_pages=1, parent=self)
        progress_dialog.cancel_signal.connect(self._on_cancel_ocr)

        worker = OCRTaskWorker(pdf_path, max_workers=10)
        ocr_thread = QThread()
        worker.moveToThread(ocr_thread)

        ocr_thread.started.connect(worker.run)
        worker.progress_signal.connect(self._on_ocr_progress)
        worker.log_signal.connect(self._on_ocr_log)
        worker.finished_signal.connect(self._on_ocr_finished)
        worker.error_signal.connect(self._on_ocr_error)
        worker.finished_signal.connect(ocr_thread.quit)
        worker.error_signal.connect(ocr_thread.quit)
        ocr_thread.finished.connect(worker.deleteLater)
        ocr_thread.finished.connect(ocr_thread.deleteLater)
        ocr_thread.finished.connect(self._cleanup_thread_refs)

        self.worker = worker
        self.ocr_thread = ocr_thread
        self.progress_dialog = progress_dialog

        progress_dialog.show()
        ocr_thread.start()

    def _on_ocr_progress(self, current, total, status):
        """转发进度到进度对话框。"""
        if self.progress_dialog:
            self.progress_dialog.update_progress(current, total, status)

    def _on_ocr_log(self, text):
        """转发日志到进度对话框与导入窗口输出区。"""
        if self.progress_dialog:
            self.progress_dialog.append_log(text)
        self.import_window.append_output(text)

    def _on_ocr_finished(self, output_pdf):
        """OCR 完成：关闭进度对话框、切换到结果阶段、加载输出 PDF。

        注意：不在此处清理 worker/thread 引用，避免 QThread Python 引用提前释放
        导致 C++ 析构函数在线程仍运行时被触发（0xC0000409 崩溃）。
        引用清理由 ocr_thread.finished 信号的 _cleanup_thread_refs 回调处理。
        """
        if self.progress_dialog:
            self.progress_dialog.finish()
        self.stacked_widget.setCurrentIndex(1)
        self.step_indicator.set_current_stage(1)
        self.result_window.load_pdf(output_pdf)
        QMessageBox.information(
            self, "完成", f"OCR 完成，输出：\n{output_pdf}"
        )

    def _on_ocr_error(self, msg):
        """OCR 出错：关闭进度对话框并提示错误。

        注意：不在此处清理 worker/thread 引用，原因同 _on_ocr_finished。
        """
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog = None
        QMessageBox.critical(self, "错误", msg)

    def _cleanup_thread_refs(self):
        """安全清理 worker 和 ocr_thread 的 Python 引用。

        由 ocr_thread.finished 信号触发，此时线程已完全停止，
        可以安全释放 Python 引用而不触发 C++ 析构竞态。
        使用 sip.isdeleted 检查避免访问已回收的 C++ 对象。
        """
        from PyQt6 import sip
        # 清理 worker 引用
        if self.worker is not None:
            try:
                if not sip.isdeleted(self.worker):
                    self.worker = None
            except RuntimeError:
                self.worker = None
        # 清理 ocr_thread 引用
        if self.ocr_thread is not None:
            try:
                if not sip.isdeleted(self.ocr_thread):
                    self.ocr_thread = None
            except RuntimeError:
                self.ocr_thread = None

    def _on_cancel_ocr(self):
        """取消 OCR：请求 worker 取消，提示用户等待当前页处理完成。"""
        if self.worker:
            self.worker.cancel()
        QMessageBox.information(
            self, "已取消",
            "OCR 任务已请求取消，正在等待当前页处理完成..."
        )

    def _on_restart(self):
        """重新开始：切换回导入阶段并清空导入窗口输出区。"""
        self.stacked_widget.setCurrentIndex(0)
        self.step_indicator.set_current_stage(0)
        self.import_window.output_text.clear()

    def closeEvent(self, event):
        """关闭窗口：若 OCR 正在运行则确认退出，释放结果窗口资源。"""
        # 防御性检查：ocr_thread 可能已被 deleteLater 回收（_on_ocr_finished/_on_ocr_error 置 None）
        # 但仍可能在事件循环间隙被访问，故用 sip.isdeleted + try/except 双重保护
        from PyQt6 import sip
        thread_alive = False
        if self.ocr_thread is not None:
            try:
                if not sip.isdeleted(self.ocr_thread) and self.ocr_thread.isRunning():
                    thread_alive = True
            except RuntimeError:
                # C++ 对象已被删除，视为不活跃
                thread_alive = False
        if thread_alive:
            reply = QMessageBox.question(
                self, "确认退出",
                "OCR 任务正在运行，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self.worker is not None:
                try:
                    self.worker.cancel()
                except RuntimeError:
                    pass
            try:
                self.ocr_thread.quit()
                self.ocr_thread.wait(5000)
            except RuntimeError:
                pass
        self.result_window.cleanup()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Windows")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
