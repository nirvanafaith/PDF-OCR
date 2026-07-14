from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsPixmapItem,
    QToolBar,
    QPushButton,
    QLabel,
    QLineEdit,
    QFileDialog,
    QMessageBox,
    QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QRectF, QTimer
from PyQt6.QtGui import QPixmap, QImage, QPen, QBrush, QPainter, QMouseEvent, QWheelEvent

import os
import subprocess
import sys
import threading

from pdf_processor import PDFProcessor
from pdf_processor.pdf_loader import LazyPageLoader
from ui.styles import get_stylesheet
from ui.zoom_utils import calculate_wheel_zoom, ZOOM_MIN, ZOOM_MAX


def _try_native():
    """尝试加载本地 native 加速模块。

    成功返回 (pixmap_bytes_to_qpixmap_buffer, optimize_char_boxes, batch_crop_qimage)；
    失败返回 (None, None, None)。所有 import 在函数内部完成，不影响模块加载。
    """
    try:
        from native import has_native as _has_native
        if not _has_native():
            return None, None, None
        from native import (
            pixmap_bytes_to_qpixmap_buffer,
            optimize_char_boxes,
            batch_crop_qimage,
        )
        return pixmap_bytes_to_qpixmap_buffer, optimize_char_boxes, batch_crop_qimage
    except Exception:
        return None, None, None


class DrawBoxWindow(QWidget):
    """画框步骤窗口，用于加载PDF并在每页上绘制矩形框标记需要识别的文本区域。

    该窗口是软件的首页，用户在此加载PDF文件后，可在每页上通过鼠标拖拽
    绘制矩形框来标记需要OCR识别的文本区域。支持翻页浏览、缩放控制、
    右键删除框等交互操作，完成后将框坐标信息通过信号传递给下一阶段。

    信号:
        finished_signal(str, dict): 画框完成时发射，参数为 (pdf_path, regions)，
            regions 是 dict[int, list[list[float]]]，键为页码，值为该页的框
            坐标列表 [x1, y1, x2, y2]，坐标为相对于页面图像的像素坐标。

    依赖:
        - PyQt6: QWidget, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
          QGraphicsPixmapItem, QToolBar, QPushButton, QLabel, QFileDialog,
          QMessageBox, QMenu, Qt, pyqtSignal, QPointF, QRectF, QTimer,
          QPixmap, QImage, QPen, QBrush, QPainter, QMouseEvent
        - pdf_processor.PDFProcessor: PDF文档处理，提供 convert_to_images 方法
        - ui.styles.get_stylesheet: 全局样式表
    """

    EXPAND_BBOX_PIXELS = 2.0
    TEXT_BLOCK_TYPES = {"text", "title", "interline_equation", "footer"}
    TEXT_SUB_BLOCK_TYPES = {"image_caption", "image_footnote", "table_caption", "table_footnote", "text", "ref_text"}

    finished_signal = pyqtSignal(str, dict)
    mineru_finished_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        """初始化画框步骤窗口。

        参数:
            parent: 父组件，默认为 None。
        """
        super().__init__(parent)
        self.pdf_path = ""
        self._lazy_loader = None
        self._page_count = 0
        self.current_page = 0
        self._selected_box_index = -1
        self.boxes = {}
        self._drawing = False
        self._start_pos = QPointF()
        self._current_rect = None
        self._zoom = 1.0
        self._first_render = True
        self._pixmap_item = None
        self._pdf_processor = PDFProcessor()
        self._scroll_timer = QTimer()
        self._scroll_timer.setInterval(16)
        self._scroll_timer.timeout.connect(self._on_scroll_tick)
        self._scroll_dx = 0
        self._scroll_dy = 0
        self._edge_zone = 50
        self._max_scroll_speed = 30
        self._init_ui()
        self.mineru_finished_signal.connect(self._on_mineru_finished)

    def _init_ui(self):
        """初始化用户界面，构建工具栏和图形视图。

        创建并配置以下 UI 组件：
        - 顶部工具栏：包含选择PDF、翻页、缩放和完成按钮
        - 中央图形视图：用于展示PDF页面图像并支持鼠标绘制矩形框

        依赖:
            - ui.styles.get_stylesheet: 获取全局样式表
        """
        self.setStyleSheet(get_stylesheet())
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setStyleSheet("QToolBar { spacing: 6px; padding: 4px; }")

        self.browse_btn = QPushButton("选择PDF")
        self.browse_btn.clicked.connect(self._on_browse_pdf)
        toolbar.addWidget(self.browse_btn)

        self.import_json_btn = QPushButton("导入JSON")
        self.import_json_btn.clicked.connect(self._on_import_json)
        toolbar.addWidget(self.import_json_btn)

        self.mineru_btn = QPushButton("模型识别")
        self.mineru_btn.clicked.connect(self._on_mineru_recognize)
        toolbar.addWidget(self.mineru_btn)

        toolbar.addSeparator()

        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self._on_prev_page)
        toolbar.addWidget(self.prev_btn)

        self.page_input = QLineEdit("1")
        self.page_input.setFixedWidth(40)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_input.returnPressed.connect(self._on_page_input)
        toolbar.addWidget(self.page_input)
        self.page_total_label = QLabel("/0")
        toolbar.addWidget(self.page_total_label)

        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self._on_next_page)
        toolbar.addWidget(self.next_btn)

        toolbar.addSeparator()

        self.zoom_in_btn = QPushButton("放大")
        self.zoom_in_btn.clicked.connect(self._on_zoom_in)
        toolbar.addWidget(self.zoom_in_btn)

        self.zoom_input = QLineEdit("100%")
        self.zoom_input.setFixedWidth(55)
        self.zoom_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_input.returnPressed.connect(self._on_zoom_input)
        toolbar.addWidget(self.zoom_input)

        self.zoom_out_btn = QPushButton("缩小")
        self.zoom_out_btn.clicked.connect(self._on_zoom_out)
        toolbar.addWidget(self.zoom_out_btn)

        self.fit_width_btn = QPushButton("适合宽度")
        self.fit_width_btn.clicked.connect(self._on_fit_width)
        toolbar.addWidget(self.fit_width_btn)

        self.fit_height_btn = QPushButton("适合高度")
        self.fit_height_btn.clicked.connect(self._on_fit_height)
        toolbar.addWidget(self.fit_height_btn)

        toolbar.addSeparator()

        self.finish_btn = QPushButton("完成")
        self.finish_btn.setStyleSheet(
            "QPushButton { background-color: #198754; color: white; "
            "border: 1px solid #157347; border-radius: 4px; "
            "padding: 4px 12px; font-size: 12px; min-height: 28px; }"
            "QPushButton:hover { background-color: #157347; }"
            "QPushButton:pressed { background-color: #146c43; }"
        )
        self.finish_btn.clicked.connect(self._on_finish)
        toolbar.addWidget(self.finish_btn)

        main_layout.addWidget(toolbar)

        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(Qt.GlobalColor.white)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.view.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.SmartViewportUpdate
        )
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        self.view.setMouseTracking(True)
        self.view.viewport().installEventFilter(self)
        main_layout.addWidget(self.view, 1)

    def _on_browse_pdf(self):
        """选择PDF文件并使用懒加载器加载。

        使用 QFileDialog 让用户选择PDF文件，通过 PDFProcessor.get_lazy_loader
        创建懒加载器实例（仅打开文档不加载页面），初始化页码和框数据，显示第一页。

        依赖:
            - pdf_processor.PDFProcessor.get_lazy_loader: 创建懒加载页面加载器
            - pdf_processor.pdf_loader.LazyPageLoader: 按需加载单页图像
            - PyQt6.QFileDialog: 提供文件选择对话框
            - PyQt6.QMessageBox: 提供错误提示对话框
        """
        pdf_path, _ = QFileDialog.getOpenFileName(
            self, "选择PDF文件", "", "PDF文件 (*.pdf)"
        )
        if not pdf_path:
            return
        try:
            if self._lazy_loader is not None:
                self._lazy_loader.close()
            self._lazy_loader = self._pdf_processor.get_lazy_loader(pdf_path, dpi=300)
            self._page_count = self._lazy_loader.page_count
        except RuntimeError as e:
            QMessageBox.critical(self, "加载失败", str(e))
            return
        self.pdf_path = pdf_path
        self.current_page = 0
        self.boxes = {}
        self._zoom = 1.0
        self._first_render = True
        self._render_page()

    def _on_mineru_recognize(self):
        """点击模型识别按钮，运行MinerU解析当前PDF。"""
        if self._lazy_loader is None:
            QMessageBox.warning(self, "提示", "请先选择PDF文件")
            return
        self.mineru_btn.setEnabled(False)

        pdf_path = self.pdf_path
        main_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        output_dir = os.path.join(main_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        def run_mineru():
            try:
                # 打包环境调用独立的 mineru_cli.exe（与 hengxiao_tool1.exe 同级），
                # 开发环境使用系统 mineru 命令。
                # 注意：不能用 sys.executable -m mineru.cli，因为 PyInstaller exe
                # 不是 Python 解释器，-m 参数不会被解释。
                if getattr(sys, "frozen", False):
                    # 打包环境：_internal/models_cache/ 下存放模型缓存
                    _base = sys._MEIPASS
                    models_cache_dir = os.path.join(_base, "models_cache")
                    # mineru_cli.exe 位于 onedir 根目录（与 hengxiao_tool1.exe 同级）
                    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
                    mineru_exe = os.path.join(_exe_dir, "mineru_cli.exe")
                    cmd = [
                        mineru_exe,
                        "-p", pdf_path,
                        "-o", output_dir,
                        "-b", "hybrid-auto-engine",
                        "--method", "ocr",
                        "--lang", "ch",
                    ]
                else:
                    # 开发环境：使用系统 mineru 命令
                    models_cache_dir = None
                    cmd = [
                        "mineru",
                        "-p", pdf_path,
                        "-o", output_dir,
                        "-b", "hybrid-auto-engine",
                        "--method", "ocr",
                        "--lang", "ch",
                    ]

                # 构建 MinerU 子进程环境变量
                mineru_env = os.environ.copy()
                # 优先使用 ModelScope（国内镜像，避免 HuggingFace SSL/网络问题）
                mineru_env["MINERU_MODEL_SOURCE"] = "modelscope"
                # 打包环境：设置 MODELSCOPE_CACHE 指向打包内模型缓存
                if models_cache_dir and os.path.isdir(models_cache_dir):
                    mineru_env["MODELSCOPE_CACHE"] = models_cache_dir
                # 设置 CUDA DLL 路径：MinerU 子进程需要找到 CUDA DLLs（cublas、cudnn 等）
                if getattr(sys, "frozen", False):
                    # 打包环境：torch/lib 位于 _internal/torch/lib/，直接添加到 PATH
                    _torch_lib = os.path.join(sys._MEIPASS, "torch", "lib")
                    if os.path.isdir(_torch_lib):
                        mineru_env["PATH"] = _torch_lib + os.pathsep + mineru_env.get("PATH", "")
                    # CUDA_PATH：lmdeploy turbomind 后端需要 CUDA_PATH/bin/ 包含 DLLs
                    # 打包环境中不创建 junction，不设置 CUDA_PATH，MinerU 会回退到 PyTorch 后端
                else:
                    # 开发环境：通过 junction 指向 torch 捆绑的 CUDA DLL
                    cuda_link_path = os.environ.get("CUDA_PATH", "")
                    if not cuda_link_path:
                        cuda_link_path = r"E:\cuda_link"
                        if os.path.isdir(os.path.join(cuda_link_path, "bin")):
                            mineru_env["CUDA_PATH"] = cuda_link_path
                        else:
                            cuda_link_path = ""
                    if cuda_link_path:
                        mineru_env["CUDA_PATH"] = cuda_link_path
                # 防御性：设置 CA 证书路径，确保 SSL 验证可用
                try:
                    import certifi
                    ca_bundle = certifi.where()
                    mineru_env["CURL_CA_BUNDLE"] = ca_bundle
                    mineru_env["REQUESTS_CA_BUNDLE"] = ca_bundle
                    mineru_env["SSL_CERT_FILE"] = ca_bundle
                except ImportError:
                    pass

                try:
                    proc = subprocess.Popen(
                        cmd,
                        env=mineru_env,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    proc.wait()
                except FileNotFoundError:
                    # MinerU 可执行文件未找到（打包环境或未安装）
                    self.mineru_finished_signal.emit("__MINERU_NOT_FOUND__")
                    return

                # 根据当前PDF文件名定位对应的输出子目录
                pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
                pdf_output_dir = os.path.join(output_dir, pdf_basename, "hybrid_ocr")
                largest_json = None
                if os.path.isdir(pdf_output_dir):
                    # 优先选择 _middle.json（坐标为PDF点坐标，转换最精确）
                    middle_json = os.path.join(pdf_output_dir, f"{pdf_basename}_middle.json")
                    if os.path.isfile(middle_json):
                        largest_json = middle_json
                    else:
                        # 回退：在该子目录中选择最大的JSON
                        largest_size = 0
                        for f in os.listdir(pdf_output_dir):
                            if f.endswith('.json'):
                                fpath = os.path.join(pdf_output_dir, f)
                                fsize = os.path.getsize(fpath)
                                if fsize > largest_size:
                                    largest_size = fsize
                                    largest_json = fpath

                if largest_json:
                    self.mineru_finished_signal.emit(largest_json)
                else:
                    self.mineru_finished_signal.emit("")
            except Exception as e:
                self.mineru_finished_signal.emit("")

        thread = threading.Thread(target=run_mineru, daemon=True)
        thread.start()

    def _on_mineru_finished(self, json_path):
        """MinerU解析完成后的处理。"""
        self.mineru_btn.setEnabled(True)
        if json_path == "__MINERU_NOT_FOUND__":
            # MinerU 可执行文件未找到（打包环境缺少依赖或未正确安装）
            QMessageBox.warning(
                self, "MinerU 不可用",
                "MinerU 模型识别功能不可用：\n"
                "未找到 MinerU 可执行文件。\n\n"
                "可能原因：\n"
                "1. 打包环境缺少 MinerU 依赖\n"
                "2. MinerU 模型缓存未正确打包\n\n"
                "您仍可使用手动画框功能标注识别区域。"
            )
        elif json_path:
            self._import_json_from_path(json_path)
            QMessageBox.information(self, "模型识别完成", f"已自动导入识别结果")
        else:
            QMessageBox.warning(self, "模型识别失败", "未找到有效的JSON结果文件")

    def _on_import_json(self):
        if self._lazy_loader is None:
            QMessageBox.warning(self, "提示", "请先选择PDF文件")
            return
        json_path, _ = QFileDialog.getOpenFileName(
            self, "选择JSON文件", "", "JSON文件 (*.json)"
        )
        if not json_path:
            return
        self._import_json_from_path(json_path)

    def _import_json_from_path(self, json_path):
        """从指定JSON文件路径导入框数据。

        支持三种MinerU JSON格式：
        1. middle.json: {pdf_info: [{para_blocks: [{bbox, type, lines}]}]}
           bbox为PDF点坐标
        2. content_list_v2.json: [[{type, content, bbox}]]
           bbox为像素坐标（基于约72DPI的渲染尺寸）
        3. model.json: [[{type, bbox, content}]]
           bbox为归一化坐标（0-1）
        """
        try:
            import json as _json
            with open(json_path, 'r', encoding='utf-8') as f:
                data = _json.load(f)

            total_imported = 0

            if isinstance(data, dict) and 'pdf_info' in data:
                # middle.json 格式：bbox为PDF点坐标
                total_imported = self._import_middle_json(data)
            elif isinstance(data, list) and len(data) > 0:
                # 判断是content_list_v2还是model.json
                first_page = data[0]
                if isinstance(first_page, list) and len(first_page) > 0:
                    first_block = first_page[0]
                    bbox = first_block.get('bbox', [])
                    if len(bbox) == 4 and all(isinstance(v, float) and v <= 1.0 for v in bbox):
                        # model.json: 归一化坐标
                        total_imported = self._import_model_json(data)
                    else:
                        # content_list_v2.json: 像素坐标
                        total_imported = self._import_content_list_json(data)

            if total_imported == 0:
                QMessageBox.warning(self, "提示", "JSON文件中未找到可导入的文本框数据")
                return

            self._render_page()
            QMessageBox.information(self, "导入完成", f"成功导入 {total_imported} 个文本框")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", f"解析JSON文件时出错：{e}")

    def _import_middle_json(self, data):
        """导入middle.json格式，bbox为PDF点坐标，需乘以DPI/72缩放因子。"""
        pdf_info = data.get('pdf_info', [])
        if not pdf_info:
            return 0
        total_imported = 0
        for page_idx, page_data in enumerate(pdf_info):
            if page_idx >= self._page_count:
                break
            pdf_w, pdf_h = self._lazy_loader.get_pdf_page_size(page_idx)
            rendered_w, rendered_h = self._lazy_loader.get_page_size(page_idx)
            scale_x = rendered_w / pdf_w if pdf_w > 0 else 1.0
            scale_y = rendered_h / pdf_h if pdf_h > 0 else 1.0
            # 兼容不同版本 MinerU 的 middle.json：新版用 preproc_blocks，旧版用 para_blocks
            para_blocks = page_data.get('para_blocks', []) or page_data.get('preproc_blocks', [])
            for block in para_blocks:
                block_type = block.get('type', '')
                bboxes_to_add = []
                if block_type in self.TEXT_BLOCK_TYPES:
                    bbox = block.get('bbox', [])
                    if len(bbox) == 4:
                        bboxes_to_add.append(bbox)
                elif block_type in ('list', 'image', 'table'):
                    for sub_block in block.get('blocks', []):
                        if sub_block.get('type', '') not in self.TEXT_SUB_BLOCK_TYPES:
                            continue
                        bbox = sub_block.get('bbox', [])
                        if len(bbox) == 4:
                            bboxes_to_add.append(bbox)
                for bbox in bboxes_to_add:
                    x0, y0, x1, y1 = bbox
                    ix0 = x0 * scale_x - self.EXPAND_BBOX_PIXELS
                    iy0 = y0 * scale_y - self.EXPAND_BBOX_PIXELS
                    ix1 = x1 * scale_x + self.EXPAND_BBOX_PIXELS
                    iy1 = y1 * scale_y + self.EXPAND_BBOX_PIXELS
                    ix0 = max(0, ix0)
                    iy0 = max(0, iy0)
                    if page_idx not in self.boxes:
                        self.boxes[page_idx] = []
                    self.boxes[page_idx].append([ix0, iy0, ix1, iy1])
                    total_imported += 1
        return total_imported

    def _import_model_json(self, data):
        """导入model.json格式，bbox为归一化坐标（0-1），需乘以渲染后像素尺寸。"""
        total_imported = 0
        for page_idx, page_blocks in enumerate(data):
            if page_idx >= self._page_count:
                break
            rendered_w, rendered_h = self._lazy_loader.get_page_size(page_idx)
            for block in page_blocks:
                block_type = block.get('type', '')
                bbox = block.get('bbox', [])
                if len(bbox) != 4:
                    continue
                if block_type not in self.TEXT_BLOCK_TYPES:
                    continue
                x0, y0, x1, y1 = bbox
                ix0 = x0 * rendered_w - self.EXPAND_BBOX_PIXELS
                iy0 = y0 * rendered_h - self.EXPAND_BBOX_PIXELS
                ix1 = x1 * rendered_w + self.EXPAND_BBOX_PIXELS
                iy1 = y1 * rendered_h + self.EXPAND_BBOX_PIXELS
                ix0 = max(0, ix0)
                iy0 = max(0, iy0)
                if page_idx not in self.boxes:
                    self.boxes[page_idx] = []
                self.boxes[page_idx].append([ix0, iy0, ix1, iy1])
                total_imported += 1
        return total_imported

    def _import_content_list_json(self, data):
        """导入content_list_v2.json格式，bbox为像素坐标（基于72DPI渲染尺寸）。

        content_list_v2.json中的bbox坐标是基于PDF页面点坐标空间的像素值，
        需要乘以 (当前渲染DPI / 72) 的缩放因子转换为当前渲染图像的像素坐标。
        """
        total_imported = 0
        for page_idx, page_blocks in enumerate(data):
            if page_idx >= self._page_count:
                break
            pdf_w, pdf_h = self._lazy_loader.get_pdf_page_size(page_idx)
            rendered_w, rendered_h = self._lazy_loader.get_page_size(page_idx)
            scale_x = rendered_w / pdf_w if pdf_w > 0 else 1.0
            scale_y = rendered_h / pdf_h if pdf_h > 0 else 1.0
            for block in page_blocks:
                block_type = block.get('type', '')
                bbox = block.get('bbox', [])
                if len(bbox) != 4:
                    continue
                # 映射类型名
                mapped_type = block_type
                if block_type in ('page_header', 'page_footer'):
                    mapped_type = 'footer'
                elif block_type == 'paragraph':
                    mapped_type = 'text'
                if mapped_type not in self.TEXT_BLOCK_TYPES:
                    continue
                x0, y0, x1, y1 = bbox
                ix0 = x0 * scale_x - self.EXPAND_BBOX_PIXELS
                iy0 = y0 * scale_y - self.EXPAND_BBOX_PIXELS
                ix1 = x1 * scale_x + self.EXPAND_BBOX_PIXELS
                iy1 = y1 * scale_y + self.EXPAND_BBOX_PIXELS
                ix0 = max(0, ix0)
                iy0 = max(0, iy0)
                if page_idx not in self.boxes:
                    self.boxes[page_idx] = []
                self.boxes[page_idx].append([ix0, iy0, ix1, iy1])
                total_imported += 1
        return total_imported

    def _render_page(self):
        """渲染当前页面的图像和已保存的框到图形场景中。

        执行以下操作：
        1. 清空场景并重置图元引用
        2. 从懒加载器获取当前页面图像，转换为QPixmap并添加到场景
        3. 根据缩放级别设置场景矩形大小
        4. 绘制该页所有已保存的框（蓝色边框，透明填充）
        5. 更新页码标签
        6. 首次渲染时延迟调用 _on_fit_width 自适应宽度
        """
        self.scene.clear()
        self._pixmap_item = None
        self._current_rect = None

        if self._lazy_loader is None or self.current_page >= self._page_count:
            self.scene.setSceneRect(QRectF(0, 0, 800, 1000))
            self.page_input.setText("0")
            self.page_total_label.setText("/0")
            return

        img = self._lazy_loader.get_page(self.current_page)
        pixmap = self._pil_to_pixmap(img)
        scaled_w = int(img.width * self._zoom)
        scaled_h = int(img.height * self._zoom)
        if self._zoom != 1.0:
            pixmap = pixmap.scaled(
                scaled_w,
                scaled_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )

        self._pixmap_item = QGraphicsPixmapItem(pixmap)
        self._pixmap_item.setZValue(0)
        self.scene.addItem(self._pixmap_item)

        self.scene.setSceneRect(QRectF(0, 0, scaled_w, scaled_h))

        brush = QBrush(Qt.GlobalColor.transparent)
        for i, box in enumerate(self.boxes.get(self.current_page, [])):
            x1, y1, x2, y2 = box
            rect = QRectF(
                x1 * self._zoom,
                y1 * self._zoom,
                (x2 - x1) * self._zoom,
                (y2 - y1) * self._zoom,
            )
            rect_item = QGraphicsRectItem(rect)
            if i == self._selected_box_index:
                rect_item.setPen(QPen(Qt.GlobalColor.red, 4))
            else:
                rect_item.setPen(QPen(Qt.GlobalColor.blue, 2))
            rect_item.setBrush(brush)
            rect_item.setZValue(1)
            self.scene.addItem(rect_item)

        self.page_input.setText(str(self.current_page + 1))
        self.page_total_label.setText(f"/{self._page_count}")
        self.zoom_input.setText(f"{int(self._zoom * 100)}%")

        if self._first_render:
            self._first_render = False
            QTimer.singleShot(100, self._on_fit_height)

    def eventFilter(self, obj, event):
        """事件过滤器，处理鼠标绘制矩形框的交互。

        监听视口上的鼠标按下、移动和释放事件，实现拖拽绘制矩形框功能。
        绘制时使用场景坐标，完成后将框坐标转换为图像像素坐标保存。

        参数:
            obj: 事件目标对象，仅处理 view.viewport() 的事件。
            event: 事件对象，处理鼠标按下、移动和释放事件。

        返回:
            bool: 鼠标绘制事件返回 True 拦截事件，其他事件返回 False 放行。
        """
        if obj is not self.view.viewport():
            return super().eventFilter(obj, event)

        new_zoom = calculate_wheel_zoom(event, self._zoom)
        if new_zoom is not None:
            self._zoom = new_zoom
            self._render_page()
            return True

        if isinstance(event, QWheelEvent):
            v_bar = self.view.verticalScrollBar()
            delta = event.angleDelta().y()
            if delta > 0 and v_bar.value() == v_bar.minimum():
                if self.current_page > 0:
                    self.current_page -= 1
                    self._render_page()
                    QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                        self.view.verticalScrollBar().maximum()))
                return True
            elif delta < 0 and v_bar.value() == v_bar.maximum():
                if self.current_page < self._page_count - 1:
                    self.current_page += 1
                    self._render_page()
                    QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(
                        self.view.verticalScrollBar().minimum()))
                return True
            return False

        if not isinstance(event, QMouseEvent):
            return False

        if event.type() == QMouseEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                # Check if clicking on an existing box
                scene_pos = self.view.mapToScene(event.position().toPoint())
                page_boxes = self.boxes.get(self.current_page, [])
                clicked_index = -1
                for i, box in enumerate(page_boxes):
                    x1, y1, x2, y2 = box
                    rect = QRectF(
                        x1 * self._zoom,
                        y1 * self._zoom,
                        (x2 - x1) * self._zoom,
                        (y2 - y1) * self._zoom,
                    )
                    if rect.contains(scene_pos):
                        clicked_index = i
                        break
                if clicked_index >= 0:
                    self._selected_box_index = clicked_index
                    self._render_page()
                    return True
                # Click on empty area - deselect and start drawing
                self._selected_box_index = -1
                self._render_page()
                if self._lazy_loader is None:
                    return False
                self._drawing = True
                self._start_pos = self.view.mapToScene(event.pos())
                pen = QPen(Qt.GlobalColor.blue, 2)
                brush = QBrush(Qt.GlobalColor.transparent)
                self._current_rect = QGraphicsRectItem(
                    QRectF(self._start_pos, self._start_pos)
                )
                self._current_rect.setPen(pen)
                self._current_rect.setBrush(brush)
                self._current_rect.setZValue(2)
                self.scene.addItem(self._current_rect)
                return True

        elif event.type() == QMouseEvent.Type.MouseMove:
            if self._drawing and self._current_rect is not None:
                current_pos = self.view.mapToScene(event.pos())
                rect = QRectF(
                    self._start_pos,
                    current_pos,
                ).normalized()
                self._current_rect.setRect(rect)

                vp = self.view.viewport()
                vp_w = vp.width()
                vp_h = vp.height()
                pos = event.pos()
                vx, vy = 0.0, 0.0

                if pos.x() < self._edge_zone:
                    vx = -self._max_scroll_speed * (1 - pos.x() / self._edge_zone)
                elif pos.x() > vp_w - self._edge_zone:
                    vx = self._max_scroll_speed * (1 - (vp_w - pos.x()) / self._edge_zone)

                if pos.y() < self._edge_zone:
                    vy = -self._max_scroll_speed * (1 - pos.y() / self._edge_zone)
                elif pos.y() > vp_h - self._edge_zone:
                    vy = self._max_scroll_speed * (1 - (vp_h - pos.y()) / self._edge_zone)

                self._scroll_dx = int(vx)
                self._scroll_dy = int(vy)

                if vx != 0 or vy != 0:
                    if not self._scroll_timer.isActive():
                        self._scroll_timer.start()
                else:
                    self._scroll_timer.stop()

                return True

        elif event.type() == QMouseEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and self._drawing:
                self._drawing = False
                self._scroll_timer.stop()
                self._scroll_dx = 0
                self._scroll_dy = 0
                if self._current_rect is not None:
                    rect = self._current_rect.rect()
                    if self._zoom > 0 and rect.width() > 2 and rect.height() > 2:
                        x1 = rect.x() / self._zoom
                        y1 = rect.y() / self._zoom
                        x2 = (rect.x() + rect.width()) / self._zoom
                        y2 = (rect.y() + rect.height()) / self._zoom
                        if self.current_page not in self.boxes:
                            self.boxes[self.current_page] = []
                        self.boxes[self.current_page].append(
                            [x1, y1, x2, y2]
                        )
                    else:
                        self.scene.removeItem(self._current_rect)
                    self._current_rect = None
                return True

        return False

    def keyPressEvent(self, event):
        """处理键盘事件，Delete键删除选中框。"""
        if event.key() == Qt.Key.Key_Delete and self._selected_box_index >= 0:
            page_boxes = self.boxes.get(self.current_page, [])
            if 0 <= self._selected_box_index < len(page_boxes):
                page_boxes.pop(self._selected_box_index)
                if not page_boxes:
                    self.boxes.pop(self.current_page, None)
                self._selected_box_index = -1
                self._render_page()
            return
        super().keyPressEvent(event)

    def _on_scroll_tick(self):
        """边缘滚动定时器回调，根据当前滚动方向和速度平移视口。

        当用户在画框过程中将鼠标移至视口边缘区域时，
        该方法由定时器周期性调用，实现视口向对应方向的平滑滚动，
        滚动速度根据鼠标与边缘的距离动态调整。

        调用关系:
            由 _scroll_timer.timeout 信号触发。
        """
        if self._scroll_dx != 0:
            h_bar = self.view.horizontalScrollBar()
            h_bar.setValue(h_bar.value() + self._scroll_dx)
        if self._scroll_dy != 0:
            v_bar = self.view.verticalScrollBar()
            v_bar.setValue(v_bar.value() + self._scroll_dy)

    def _on_context_menu(self, pos):
        """处理右键上下文菜单，提供删除框的操作入口。

        检测右键点击位置是否在某个已保存的框上，若是则弹出"删除"选项。
        删除后从 boxes 字典中移除对应框并重新渲染页面。

        参数:
            pos: 视口坐标系中的右键点击位置，由信号自动传入。
        """
        scene_pos = self.view.mapToScene(pos)
        page_boxes = self.boxes.get(self.current_page, [])
        found_index = -1
        for i, box in enumerate(page_boxes):
            x1, y1, x2, y2 = box
            rect = QRectF(
                x1 * self._zoom,
                y1 * self._zoom,
                (x2 - x1) * self._zoom,
                (y2 - y1) * self._zoom,
            )
            if rect.contains(scene_pos):
                found_index = i
                break

        if found_index < 0:
            return

        menu = QMenu(self)
        delete_action = menu.addAction("删除")
        chosen = menu.exec(self.view.mapToGlobal(pos))
        if chosen == delete_action:
            page_boxes.pop(found_index)
            if not page_boxes:
                self.boxes.pop(self.current_page, None)
            self._render_page()

    def _on_prev_page(self):
        """切换到上一页。

        当当前页非首页时，页码减一并调用 _render_page 重新渲染。
        """
        if self.current_page > 0:
            self._selected_box_index = -1
            self.current_page -= 1
            self._render_page()

    def _on_next_page(self):
        """切换到下一页。

        当当前页非末页时，页码加一并调用 _render_page 重新渲染。
        """
        if self._lazy_loader is not None and self.current_page < self._page_count - 1:
            self._selected_box_index = -1
            self.current_page += 1
            self._render_page()

    def _on_zoom_in(self):
        if self._zoom < ZOOM_MAX:
            self._zoom += 0.25
            self._render_page()

    def _on_zoom_out(self):
        if self._zoom > ZOOM_MIN:
            self._zoom -= 0.25
            self._render_page()

    def _on_fit_width(self):
        """将视图缩放调整为适合视口宽度。

        根据当前页面图像宽度与视口可用宽度的比值计算 _zoom，
        然后调用 _render_page 重新渲染。
        """
        if self._lazy_loader is None or self.current_page >= self._page_count:
            return
        view_width = self.view.viewport().width() - 20
        img = self._lazy_loader.get_page(self.current_page)
        img_width = img.width
        if img_width > 0:
            self._zoom = view_width / img_width
            self._render_page()

    def _on_fit_height(self):
        """将视图缩放调整为适合视口高度。"""
        if self._lazy_loader is None or self.current_page >= self._page_count:
            return
        view_height = self.view.viewport().height() - 20
        img = self._lazy_loader.get_page(self.current_page)
        img_height = img.height
        if img_height > 0:
            self._zoom = view_height / img_height
            self._render_page()

    def resizeEvent(self, event):
        """窗口大小变化时，若最大化则自动适配高度。"""
        super().resizeEvent(event)
        is_maximized = bool(self.windowState() & Qt.WindowState.WindowMaximized)
        if is_maximized and not getattr(self, '_was_maximized', False):
            if self._lazy_loader is not None:
                QTimer.singleShot(50, self._on_fit_height)
        self._was_maximized = is_maximized

    def _on_page_input(self):
        """页码输入框回车处理，跳转到指定页。"""
        text = self.page_input.text().strip()
        try:
            page = int(text)
            if 1 <= page <= self._page_count:
                self.current_page = page - 1
                self._selected_box_index = -1
                self._render_page()
        except ValueError:
            pass
        self.page_input.setText(str(self.current_page + 1))

    def _on_zoom_input(self):
        """缩放输入框回车处理，修改缩放率。"""
        text = self.zoom_input.text().strip().rstrip('%')
        try:
            zoom_pct = int(text)
            if 10 <= zoom_pct <= 1000:
                self._zoom = zoom_pct / 100
                self._render_page()
        except ValueError:
            pass
        self.zoom_input.setText(f"{int(self._zoom * 100)}%")

    def _on_finish(self):
        """完成画框操作，验证并发射完成信号。

        验证至少画了一个框且已加载PDF文件，若验证通过则发射
        finished_signal(pdf_path, boxes) 信号。

        依赖:
            - PyQt6.QMessageBox: 提供警告对话框
        """
        if not self.pdf_path:
            QMessageBox.warning(self, "提示", "请先选择PDF文件")
            return
        if not self.boxes:
            QMessageBox.warning(self, "提示", "请至少画一个框")
            return
        self.finished_signal.emit(self.pdf_path, self.boxes)

    def _pil_to_pixmap(self, pil_image) -> QPixmap:
        """将 PIL Image 对象转换为 QPixmap。

        优先调用 native (H1) 直通路径，跳过 PIL convert + tobytes 的多次拷贝；
        native 不可用时回落到原 PIL→QImage 路径，行为不变。

        参数:
            pil_image: PIL Image 对象，支持任意图像模式。

        返回:
            QPixmap: 转换后的 QPixmap 对象；若输入为 None 则返回空 QPixmap。
        """
        if pil_image is None:
            return QPixmap()
        # H1: native 直通路径
        try:
            pixmap_bytes_to_qpixmap_buffer = _try_native()[0]
            if pixmap_bytes_to_qpixmap_buffer is not None:
                if pil_image.mode == "RGBA":
                    raw = pil_image.tobytes("raw", "RGBA")
                    n = 4
                    fmt = QImage.Format.Format_RGBA8888
                elif pil_image.mode == "RGB":
                    raw = pil_image.tobytes("raw", "RGB")
                    n = 3
                    fmt = QImage.Format.Format_RGB888
                else:
                    pil_image = pil_image.convert("RGBA")
                    raw = pil_image.tobytes("raw", "RGBA")
                    n = 4
                    fmt = QImage.Format.Format_RGBA8888
                buf = pixmap_bytes_to_qpixmap_buffer(
                    raw, pil_image.width, pil_image.height, n, 0
                )
                if buf is not None:
                    qimage = QImage(
                        buf,
                        pil_image.width,
                        pil_image.height,
                        pil_image.width * n,
                        fmt,
                    )
                    # .copy() 确保 QPixmap 持有独立数据，buf 可在 fromImage 后释放
                    return QPixmap.fromImage(qimage.copy())
        except Exception:
            pass
        # Fallback: 原 PIL→QImage 路径
        if pil_image.mode != "RGBA":
            pil_image = pil_image.convert("RGBA")
        data = pil_image.tobytes("raw", "RGBA")
        qimage = QImage(
            data,
            pil_image.width,
            pil_image.height,
            QImage.Format.Format_RGBA8888,
        )
        return QPixmap.fromImage(qimage)

    def cleanup(self):
        """清理资源，关闭懒加载器释放PDF文档句柄和缓存。

        调用关系:
            被 MainWindow 在窗口切换或清理时调用。
        """
        if self._lazy_loader is not None:
            self._lazy_loader.close()
            self._lazy_loader = None
