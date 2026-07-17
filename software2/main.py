import os
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
    # 在主线程强制加载 _hxnative.pyd，避免在QThread中首次加载触发
    # STATUS_DLL_INIT_FAILED (0xC0000142) 导致静默崩溃
    # 失败时 has_native() 返回 False，parse_and_group 自动回退到 Python fallback
    native.has_native()
except Exception as _e:
    print(f"native: diagnostic skipped ({_e})", file=sys.stderr)

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
from PyQt5.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PIL import Image

from pdf_processor import PDFProcessor
from ocr_engine import OCREngine
from ui.import_window import ImportWindow
from ui.vertical_check_window import VerticalCheckWindow
from ui.horizontal_check_window import HorizontalCheckWindow
from ui.refine_window import RefineWindow
from ui.styles import get_stylesheet
from pathlib import Path
from session_manager import SessionManager, ProjectData
from models.data_models import CharSlice, LineSlice, RefineTextItem


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


class BuildLineDataWorker(QObject):
    """在 worker 线程中执行 OCREngine.build_line_data，避免阻塞 UI 主线程。

    进入横校阶段时，构建行级数据可能耗时较长（大文档尤为明显），
    将该操作移入后台线程，主线程仅显示等待光标并保持响应。
    """

    finished = pyqtSignal(object)  # 发射 page_lines
    error = pyqtSignal(str)

    def __init__(self, ocr_engine, results, page_images, char_slices):
        super().__init__()
        self._ocr_engine = ocr_engine
        self._results = results
        self._page_images = page_images
        self._char_slices = char_slices
        self.page_lines = None

    def run(self):
        try:
            self.page_lines = self._ocr_engine.build_line_data(
                self._results, self._page_images, self._char_slices
            )
            self.finished.emit(self.page_lines)
        except Exception as e:
            self.error.emit(str(e))


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
        self.page_lines = {}
        self.current_stage = 0
        self.setStyleSheet(get_stylesheet())
        # 工程会话管理：保存/加载断点与全局数据
        self._source_pdf_path = None
        self._current_project_data = None
        self._session_manager = SessionManager(self)
        self._session_manager.project_saved.connect(self._on_project_saved)
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
        # 状态栏：用于回显子窗口异常与操作提示
        self.status_bar = self.statusBar()

    def show_status_message(self, msg, timeout=5000):
        """在状态栏显示一条临时消息，默认 5 秒后自动清除。"""
        self.status_bar.showMessage(msg, timeout)

    def _on_child_error(self, msg):
        """子窗口 error_occurred 信号的公共槽，将异常回显到状态栏。"""
        self.show_status_message(f"操作失败：{msg}", 5000)

    # ---- Stage 0: 导入 ----

    def _setup_import_stage(self):
        self.import_widget = ImportWindow()
        self.import_widget.finished_signal.connect(self._on_import_finished)
        # 工程加载信号：由 ImportWindow 在用户选择已保存工程后发射，Phase 4 同步添加
        self.import_widget.project_loaded_signal.connect(self._on_project_loaded)
        self.stack.addWidget(self.import_widget)
        self.stack.setCurrentWidget(self.import_widget)
        self.step_indicator.set_current(0)

    def _on_import_finished(self, page_images, ocr_results, char_slices):
        self.page_images = page_images
        self.ocr_results = ocr_results
        self.char_slices = char_slices
        # 记录源 PDF 路径，供工程保存使用
        if self.import_widget is not None:
            self._source_pdf_path = self.import_widget.pdf_path_edit.text().strip()
        # 新工程会话：重置工程数据并重建会话管理器，避免新工程覆盖旧工程文件夹
        self._current_project_data = None
        self.page_lines = {}
        if self._session_manager is not None:
            self._session_manager.stop_auto_save()
            self._session_manager.deleteLater()
        self._session_manager = SessionManager(self)
        self._session_manager.project_saved.connect(self._on_project_saved)
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
        self.vert_widget.error_occurred.connect(self._on_child_error)
        # 连接纵校窗口的保存请求信号，合并全局数据后调用 SessionManager.save
        self.vert_widget.save_requested.connect(
            lambda bp: self._on_save_requested('vertical', bp)
        )
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

    def _setup_horizontal_stage(self, skip_build=False):
        """进入横校阶段。

        参数:
            skip_build: 为 True 时跳过 build_line_data（断点恢复模式），
                直接使用已恢复的 self.page_lines 创建横校窗口。
        """
        if skip_build:
            # 断点恢复模式：直接使用已恢复的 page_lines，跳过 build_line_data
            self._create_horiz_widget(self.page_lines)
            return
        # 设置等待光标，提示用户后台处理中
        QApplication.setOverrideCursor(Qt.WaitCursor)

        # 创建 worker 和线程，将阻塞的 build_line_data 移入 worker 线程
        self._build_worker = BuildLineDataWorker(
            self.ocr_engine, self.ocr_results, self.page_images, self.char_slices
        )
        self._build_thread = QThread()
        self._build_worker.moveToThread(self._build_thread)

        # started -> worker.run；finished/error -> 通知线程退出并继续后续逻辑
        self._build_thread.started.connect(self._build_worker.run)
        self._build_worker.finished.connect(self._on_build_line_data_finished)
        self._build_worker.error.connect(self._on_build_line_data_error)
        # 线程结束后清理 worker 与 thread 对象
        self._build_thread.finished.connect(self._build_worker.deleteLater)
        self._build_thread.finished.connect(self._build_thread.deleteLater)

        self._build_thread.start()

    def _create_horiz_widget(self, page_lines):
        """创建横校窗口并连接信号，同时缓存 page_lines 供工程保存使用。"""
        self.page_lines = page_lines
        self.horiz_widget = HorizontalCheckWindow(page_lines, self.page_images)
        self.horiz_widget.finished_signal.connect(self._on_horizontal_finished)
        self.horiz_widget.back_signal.connect(self._on_horizontal_back)
        self.horiz_widget.error_occurred.connect(self._on_child_error)
        # 连接横校窗口的保存请求信号，合并全局数据后调用 SessionManager.save
        self.horiz_widget.save_requested.connect(
            lambda bp: self._on_save_requested('horizontal', bp)
        )
        self.stack.addWidget(self.horiz_widget)
        self.stack.setCurrentWidget(self.horiz_widget)

    def _on_build_line_data_finished(self, page_lines):
        """build_line_data 完成：恢复光标，继续横校窗口的显示逻辑。"""
        # 恢复光标
        QApplication.restoreOverrideCursor()
        # 通知 worker 线程退出（deleteLater 由 finished 信号触发）
        self._build_thread.quit()
        self._create_horiz_widget(page_lines)

    def _on_build_line_data_error(self, msg):
        """build_line_data 失败：恢复光标，弹窗并回显状态栏。"""
        # 恢复光标
        QApplication.restoreOverrideCursor()
        # 通知 worker 线程退出
        self._build_thread.quit()

        QMessageBox.critical(self, "错误", f"构建行数据失败：{msg}")
        self.show_status_message(f"操作失败：{msg}", 5000)

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

    def _setup_refine_stage(self, page_lines=None):
        """进入精修阶段。

        参数:
            page_lines: 断点恢复模式下传入已恢复的 page_lines；
                为 None 时从横校窗口取（正常流程）。
        """
        if page_lines is None:
            page_lines = self.horiz_widget.page_lines
        self.refine_widget = RefineWindow(
            page_lines, self.page_images, pdf_path=self._source_pdf_path
        )
        self.refine_widget.output_complete_signal.connect(self._on_output_complete)
        self.refine_widget.finished_signal.connect(self._on_refine_finished)
        self.refine_widget.back_signal.connect(self._on_refine_back)
        self.refine_widget.error_occurred.connect(self._on_child_error)
        # 连接精修窗口的保存请求信号，合并全局数据后调用 SessionManager.save
        self.refine_widget.save_requested.connect(
            lambda bp: self._on_save_requested('refine', bp)
        )
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

    # ==================== 工程会话管理（SessionManager 集成） ====================

    def _on_project_saved(self, saved_path):
        """SessionManager.project_saved 信号的槽。

        手动保存的状态栏提示由 _on_save_requested 负责；自动保存静默执行。
        此处保留为扩展点（如刷新标题栏最近保存时间），默认不操作以避免
        在自动保存时打扰用户。

        参数:
            saved_path: 本次保存的工程文件夹路径。
        """
        pass

    def _on_save_requested(self, stage, breakpoints):
        """接收子窗口的保存请求，合并全局数据并调用 SessionManager.save。

        各窗口发射的断点结构不一致，本方法统一规整为
        {"vertical": {...}, "horizontal": {...}, "refine": {...}} 三段结构，
        并保留其他阶段的断点。精修窗口会在 payload 中附带 refine_items，
        此处一并提取。

        参数:
            stage: 当前阶段 ("vertical"/"horizontal"/"refine")。
            breakpoints: 子窗口发射的断点数据（结构因窗口而异）。
        """
        try:
            # 规整各窗口发射的断点为 {stage: {...}} 结构
            stage_bp = {}
            refine_items_received = None
            if stage == 'vertical':
                stage_bp = breakpoints if isinstance(breakpoints, dict) else {}
            elif stage == 'horizontal':
                stage_bp = (breakpoints or {}).get('horizontal', {}) if isinstance(
                    breakpoints, dict
                ) else {}
            elif stage == 'refine':
                full = breakpoints if isinstance(breakpoints, dict) else {}
                stage_bp = full.get('breakpoints', {}).get('refine', {})
                refine_items_received = full.get('refine_items', {})

            # 合并断点：保留其他阶段，更新当前阶段
            if self._current_project_data is not None and isinstance(
                self._current_project_data.breakpoints, dict
            ):
                merged_bp = {
                    'vertical': self._current_project_data.breakpoints.get('vertical', {}),
                    'horizontal': self._current_project_data.breakpoints.get('horizontal', {}),
                    'refine': self._current_project_data.breakpoints.get('refine', {}),
                }
            else:
                merged_bp = {'vertical': {}, 'horizontal': {}, 'refine': {}}
            merged_bp[stage] = stage_bp

            # 收集全局数据，序列化为可 JSON 化的字典
            ocr_results_dict = {
                'lines': list(self.ocr_results[0]) if self.ocr_results else [],
                'chars': list(self.ocr_results[1]) if self.ocr_results else [],
            }
            char_slices_dict = {
                k: [s.to_dict() for s in v] for k, v in self.char_slices.items()
            }
            page_lines_dict = self._collect_page_lines()
            if refine_items_received is not None:
                refine_items_dict = refine_items_received
            else:
                refine_items_dict = self._collect_refine_items()

            # 构造或更新 ProjectData
            source_pdf_path = self._source_pdf_path or ''
            source_pdf_name = Path(source_pdf_path).stem if source_pdf_path else ''
            if self._current_project_data is None:
                self._current_project_data = ProjectData(
                    stage=stage,
                    source_pdf_path=source_pdf_path,
                    source_pdf_name=source_pdf_name,
                    breakpoints=merged_bp,
                    saved_at='',
                    ocr_results=ocr_results_dict,
                    char_slices=char_slices_dict,
                    page_lines=page_lines_dict,
                    refine_items=refine_items_dict,
                )
            else:
                self._current_project_data.stage = stage
                self._current_project_data.source_pdf_path = source_pdf_path
                self._current_project_data.source_pdf_name = (
                    source_pdf_name or self._current_project_data.source_pdf_name
                )
                self._current_project_data.breakpoints = merged_bp
                self._current_project_data.ocr_results = ocr_results_dict
                self._current_project_data.char_slices = char_slices_dict
                self._current_project_data.page_lines = page_lines_dict
                self._current_project_data.refine_items = refine_items_dict

            saved_path = self._session_manager.save(
                self._current_project_data, source_pdf_path
            )
            self._session_manager.set_current_project(
                self._current_project_data, source_pdf_path
            )
            self.show_status_message(f"已保存到 {saved_path}", 5000)
        except Exception as e:
            self.show_status_message(f"保存失败：{e}", 5000)

    def _on_project_loaded(self, project_data):
        """接收 ImportWindow 的工程加载信号，恢复工程状态并跳转到断点阶段。

        依次恢复 PDF 页面图像、OCR 结果、字符切片（重新裁切图像）、行数据，
        关闭导入窗口，启动自动保存，并根据 project_data.stage 跳转到对应
        阶段、恢复断点状态。

        参数:
            project_data: SessionManager.load 返回的 ProjectData 对象。
        """
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._current_project_data = project_data
            self._source_pdf_path = project_data.source_pdf_path

            # 加载 PDF 页面图像
            self.page_images = self.pdf_processor.convert_to_images(
                project_data.source_pdf_path, dpi=300
            )

            # 恢复 ocr_results（lines + chars 均为可 JSON 化字典列表）
            ocr_dict = project_data.ocr_results if isinstance(
                project_data.ocr_results, dict
            ) else {}
            lines = ocr_dict.get('lines', [])
            chars = ocr_dict.get('chars', [])
            self.ocr_results = (lines, chars)
            self.ocr_engine.results = self.ocr_results

            # 恢复 char_slices（image 置 None 后按 bbox 重新裁切）
            self.char_slices = {
                k: [CharSlice.from_dict(d) for d in v]
                for k, v in (project_data.char_slices or {}).items()
            }
            self._recrop_char_slice_images()

            # 恢复 page_lines（JSON 键为 str，需转 int）
            self.page_lines = {
                int(k): [LineSlice.from_dict(d) for d in v]
                for k, v in (project_data.page_lines or {}).items()
            }

            # 关闭导入窗口
            if self.import_widget is not None:
                try:
                    self.import_widget.cleanup()
                except Exception:
                    pass
                self.stack.removeWidget(self.import_widget)
                self.import_widget.deleteLater()
                self.import_widget = None

            # 设置当前工程并启动自动保存
            self._session_manager.set_current_project(
                project_data, project_data.source_pdf_path
            )
            self._session_manager.start_auto_save()

            # 根据 stage 跳转到对应阶段并恢复断点
            stage = project_data.stage or 'vertical'
            breakpoints = project_data.breakpoints or {}

            if stage == 'horizontal':
                self.current_stage = 2
                self.step_indicator.set_current(2)
                self._setup_horizontal_stage(skip_build=True)
                self.horiz_widget._restore_breakpoint_state(breakpoints)
            elif stage == 'refine':
                self.current_stage = 3
                self.step_indicator.set_current(3)
                self._setup_refine_stage(page_lines=self.page_lines)
                # 传原始 refine_items 字典，由精修窗口内部 from_dict 反序列化
                self.refine_widget._restore_breakpoint_state(
                    breakpoints,
                    refine_items=project_data.refine_items,
                )
            else:
                # vertical 或未知阶段默认进入纵校
                self.current_stage = 1
                self.step_indicator.set_current(1)
                self._setup_vertical_stage()
                self.vert_widget._restore_breakpoint_state(
                    breakpoints.get('vertical', {})
                )

            self.show_status_message(
                f"已恢复工程：{project_data.source_pdf_name}", 5000
            )
        except Exception as e:
            self.show_status_message(f"恢复工程失败：{e}", 5000)
        finally:
            QApplication.restoreOverrideCursor()

    def _collect_page_lines(self):
        """收集横校行数据为可 JSON 化的字典 {page_str: [line_dict]}。"""
        page_lines = getattr(self, 'page_lines', None) or {}
        return {
            str(k): [ls.to_dict() if hasattr(ls, 'to_dict') else ls for ls in v]
            for k, v in page_lines.items()
        }

    def _collect_refine_items(self):
        """收集精修文字项为可 JSON 化的字典 {page_str: [item_dict]}。"""
        refine_widget = getattr(self, 'refine_widget', None)
        page_items = getattr(refine_widget, 'page_items', None) if refine_widget is not None else None
        if not page_items:
            return {}
        return {
            str(k): [item.to_dict() if hasattr(item, 'to_dict') else item for item in v]
            for k, v in page_items.items()
        }

    def _recrop_char_slice_images(self):
        """根据 bbox 从 page_images 重新裁切 char_slice 图像。

        工程从 JSON 恢复时 CharSlice.image 为 None，纵校窗口的切片缩略图
        需要图像数据，故按 page_num + bbox 从已加载的页面图像重新裁切。
        """
        if not self.page_images:
            return

        # 尝试加载 native H3 批量裁切
        try:
            from native import has_native as _has_native
            from native import batch_crop_qimage as _batch_crop
            if not _has_native():
                _batch_crop = None
        except Exception:
            _batch_crop = None

        # 收集所有需要裁切的 char_slice
        all_slices = []
        for slices in self.char_slices.values():
            for char_slice in slices:
                page_num = char_slice.page_num
                if page_num < 0 or page_num >= len(self.page_images):
                    continue
                all_slices.append(char_slice)

        if not all_slices:
            return

        if _batch_crop is not None:
            # 按页分组批量裁切
            page_groups = {}
            for char_slice in all_slices:
                page_groups.setdefault(char_slice.page_num, []).append(char_slice)

            for page_num, slices in page_groups.items():
                page_image = self.page_images[page_num]
                img_w, img_h = page_image.size
                bboxes = []
                valid_flags = []
                for cs in slices:
                    try:
                        x1, y1, x2, y2 = cs.bbox
                        x1 = max(0, min(int(round(x1)), img_w))
                        y1 = max(0, min(int(round(y1)), img_h))
                        x2 = max(0, min(int(round(x2)), img_w))
                        y2 = max(0, min(int(round(y2)), img_h))
                        valid = x2 > x1 and y2 > y1
                        bboxes.append([x1, y1, x2, y2])
                        valid_flags.append(valid)
                    except Exception:
                        bboxes.append([0, 0, 0, 0])
                        valid_flags.append(False)

                results_bytes = None
                try:
                    page_rgba = page_image.convert("RGBA").tobytes("raw", "RGBA")
                    results_bytes = _batch_crop(page_rgba, img_w, img_h, bboxes, 0)
                except Exception:
                    results_bytes = None

                if results_bytes is None:
                    # native 调用失败，回退到逐字符 crop
                    for i, cs in enumerate(slices):
                        if not valid_flags[i]:
                            continue
                        try:
                            cs.image = page_image.crop(bboxes[i])
                        except Exception:
                            pass
                else:
                    for i, cs in enumerate(slices):
                        if not valid_flags[i]:
                            continue
                        rgba_bytes = results_bytes[i]
                        if not rgba_bytes:
                            continue
                        x1, y1, x2, y2 = bboxes[i]
                        crop_w = x2 - x1
                        crop_h = y2 - y1
                        try:
                            cs.image = Image.frombytes("RGBA", (crop_w, crop_h), rgba_bytes)
                        except Exception:
                            try:
                                cs.image = page_image.crop(bboxes[i])
                            except Exception:
                                pass
        else:
            # 回退：原有逐字符 crop 逻辑
            for char_slice in all_slices:
                page_num = char_slice.page_num
                page_image = self.page_images[page_num]
                try:
                    x1, y1, x2, y2 = char_slice.bbox
                    img_w, img_h = page_image.size
                    x1 = max(0, min(x1, img_w))
                    y1 = max(0, min(y1, img_h))
                    x2 = max(0, min(x2, img_w))
                    y2 = max(0, min(y2, img_h))
                    if x2 > x1 and y2 > y1:
                        char_slice.image = page_image.crop((x1, y1, x2, y2))
                except Exception:
                    pass


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    app.setStyle("Windows")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
