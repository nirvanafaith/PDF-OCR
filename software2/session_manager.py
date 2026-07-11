"""工程会话管理器。

保存/加载完整工程状态到固定路径：
    %USERPROFILE%/Documents/hengxiao_tool2_projects/<PDF名>_<时间戳>/

工程文件夹结构：
    project.json       - 断点状态（阶段、源PDF、保存时间）
    ocr_results.json   - OCR 识别结果（lines + chars）
    char_slices.json   - 纵校字符切片 {char_text: [slice_dict, ...]}
    page_lines.json    - 横校行数据 {page_num_str: [line_dict, ...]}
    refine_items.json  - 精修文字项 {page_num_str: [item_dict, ...]}

数据序列化由 models.data_models 中各数据类的 to_dict/from_dict 负责，
SessionManager 仅做 JSON 读写与文件夹管理。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


@dataclass
class ProjectData:
    """工程数据容器，封装完整工程状态。

    Attributes:
        stage: 当前阶段 ("vertical"/"horizontal"/"refine")。
        source_pdf_path: 源 PDF 文件绝对路径。
        source_pdf_name: 源 PDF 文件名（不含扩展名）。
        breakpoints: 各阶段断点状态，结构为
            {"vertical": {...}, "horizontal": {...}, "refine": {...}}，
            每个阶段含页码/缩放/选中项等。
        saved_at: 保存时间（ISO 格式字符串）。
        ocr_results: OCR 识别结果字典，含 lines 与 chars。
        char_slices: 纵校字符切片字典 {char_text: [slice_dict, ...]}。
        page_lines: 横校行数据字典 {page_num_str: [line_dict, ...]}。
        refine_items: 精修文字项字典 {page_num_str: [item_dict, ...]}。
    """

    stage: str = "vertical"
    source_pdf_path: str = ""
    source_pdf_name: str = ""
    breakpoints: dict = field(default_factory=lambda: {
        "vertical": {}, "horizontal": {}, "refine": {}
    })
    saved_at: str = ""
    ocr_results: dict = field(default_factory=dict)
    char_slices: dict = field(default_factory=dict)
    page_lines: dict = field(default_factory=dict)
    refine_items: dict = field(default_factory=dict)


class SessionManager(QObject):
    """工程会话管理器：保存/加载完整工程状态到固定路径。"""

    project_saved = pyqtSignal(str)  # 发射保存路径

    PROJECTS_DIR = Path.home() / "Documents" / "hengxiao_tool2_projects"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.timeout.connect(self._auto_save)
        self._auto_save_timer.setInterval(60000)  # 60 秒
        self._current_project_dir = None
        self._project_name = None
        # 自动保存所需当前状态，由 save/load/set_current_project 维护
        self._current_project_data = None
        self._current_source_pdf_path = None

    # ---- 保存 ----

    def save(self, project_data, source_pdf_path, project_name=None):
        """保存工程到固定路径下妥善命名的文件夹。

        首次保存时若 project_name 为 None，自动生成 '<PDF名>_<时间戳>'。
        后续保存覆盖同一文件夹。

        参数:
            project_data: ProjectData 对象（也兼容等价字典）。
            source_pdf_path: 源 PDF 文件路径。
            project_name: 工程名称，首次保存可省略自动生成。

        返回:
            str: 工程文件夹路径。
        """
        # 确保根目录存在
        self.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

        # 首次保存：生成工程文件夹名
        if self._current_project_dir is None:
            if not project_name:
                pdf_name = self._derive_pdf_name(source_pdf_path, project_data)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                project_name = f"{pdf_name}_{timestamp}"
            self._project_name = project_name
            self._current_project_dir = self.PROJECTS_DIR / project_name
        # 已有工程文件夹则覆盖

        self._current_project_dir.mkdir(parents=True, exist_ok=True)

        saved_at = datetime.now().isoformat(timespec="seconds")

        # 统一抽取字段（兼容 ProjectData 与字典）
        if isinstance(project_data, ProjectData):
            project_data.saved_at = saved_at
            stage = project_data.stage
            source_pdf_name = project_data.source_pdf_name or self._derive_pdf_name(
                source_pdf_path, project_data
            )
            breakpoints = project_data.breakpoints
            ocr_results = project_data.ocr_results
            char_slices = project_data.char_slices
            page_lines = project_data.page_lines
            refine_items = project_data.refine_items
        else:
            project_data["saved_at"] = saved_at
            stage = project_data.get("stage", "vertical")
            source_pdf_name = project_data.get(
                "source_pdf_name", self._derive_pdf_name(source_pdf_path, project_data)
            )
            breakpoints = project_data.get("breakpoints", {})
            ocr_results = project_data.get("ocr_results", {})
            char_slices = project_data.get("char_slices", {})
            page_lines = project_data.get("page_lines", {})
            refine_items = project_data.get("refine_items", {})

        # 写入 project.json（断点状态）
        project_meta = {
            "stage": stage,
            "source_pdf_path": source_pdf_path,
            "source_pdf_name": source_pdf_name,
            "breakpoints": self._normalize_breakpoints(breakpoints),
            "saved_at": saved_at,
            "project_name": self._project_name,
        }
        self._write_json(self._current_project_dir / "project.json", project_meta)
        self._write_json(self._current_project_dir / "ocr_results.json", ocr_results)
        self._write_json(self._current_project_dir / "char_slices.json", char_slices)
        self._write_json(self._current_project_dir / "page_lines.json", page_lines)
        self._write_json(self._current_project_dir / "refine_items.json", refine_items)

        # 记录当前数据，供自动保存使用
        self._current_project_data = project_data
        self._current_source_pdf_path = source_pdf_path

        saved_path = str(self._current_project_dir)
        self.project_saved.emit(saved_path)
        return saved_path

    # ---- 加载 ----

    def load(self, project_path):
        """加载工程，返回 ProjectData 对象。

        参数:
            project_path: 工程文件夹路径。

        返回:
            ProjectData: 加载的工程数据。
        """
        project_dir = Path(project_path)
        project_meta = self._read_json(project_dir / "project.json")
        ocr_results = self._read_json(project_dir / "ocr_results.json")
        char_slices = self._read_json(project_dir / "char_slices.json")
        page_lines = self._read_json(project_dir / "page_lines.json")
        refine_items = self._read_json(project_dir / "refine_items.json")

        data = ProjectData(
            stage=project_meta.get("stage", "vertical"),
            source_pdf_path=project_meta.get("source_pdf_path", ""),
            source_pdf_name=project_meta.get("source_pdf_name", ""),
            breakpoints=self._normalize_breakpoints(
                project_meta.get("breakpoints", {})
            ),
            saved_at=project_meta.get("saved_at", ""),
            ocr_results=ocr_results if isinstance(ocr_results, dict) else {},
            char_slices=char_slices if isinstance(char_slices, dict) else {},
            page_lines=page_lines if isinstance(page_lines, dict) else {},
            refine_items=refine_items if isinstance(refine_items, dict) else {},
        )

        # 记录当前工程，供自动保存使用
        self._current_project_dir = project_dir
        self._project_name = project_meta.get("project_name", project_dir.name)
        self._current_project_data = data
        self._current_source_pdf_path = data.source_pdf_path
        return data

    # ---- 列表 ----

    def list_projects(self):
        """扫描固定路径下所有工程文件夹，返回 [(name, path, saved_at), ...]。

        按保存时间倒序排列（最新在前）。
        """
        results = []
        if not self.PROJECTS_DIR.exists():
            return results
        for sub in self.PROJECTS_DIR.iterdir():
            if not sub.is_dir():
                continue
            meta_file = sub / "project.json"
            if not meta_file.exists():
                continue
            try:
                meta = self._read_json(meta_file)
            except Exception:
                continue
            name = meta.get("project_name", sub.name)
            saved_at = meta.get("saved_at", "")
            results.append((name, str(sub), saved_at))
        # 按保存时间倒序
        results.sort(key=lambda x: x[2], reverse=True)
        return results

    # ---- 自动保存 ----

    def start_auto_save(self):
        """启动 60 秒自动保存定时器。"""
        self._auto_save_timer.start()

    def stop_auto_save(self):
        """停止自动保存定时器。"""
        self._auto_save_timer.stop()

    def set_current_project(self, project_data, source_pdf_path):
        """设置当前工程数据，供自动保存使用。

        参数:
            project_data: ProjectData 对象。
            source_pdf_path: 源 PDF 文件路径。
        """
        self._current_project_data = project_data
        self._current_source_pdf_path = source_pdf_path

    def _auto_save(self):
        """定时器触发时自动保存（不弹窗）。

        依赖外部通过 set_current_project 或 save 设置当前 project_data。
        静默失败，避免干扰用户。
        """
        if self._current_project_dir is not None and self._current_project_data is not None:
            try:
                self.save(
                    self._current_project_data, self._current_source_pdf_path
                )
            except Exception:
                pass  # 静默失败，避免干扰用户

    # ---- 辅助方法 ----

    @staticmethod
    def _derive_pdf_name(source_pdf_path, project_data):
        """从 PDF 路径或 project_data 推导 PDF 名（不含扩展名）。"""
        if isinstance(project_data, ProjectData) and project_data.source_pdf_name:
            return project_data.source_pdf_name
        if isinstance(project_data, dict) and project_data.get("source_pdf_name"):
            return project_data["source_pdf_name"]
        if source_pdf_path:
            return Path(source_pdf_path).stem
        return "project"

    @staticmethod
    def _normalize_breakpoints(breakpoints):
        """规整断点字典为 {vertical, horizontal, refine} 三段结构。"""
        if not isinstance(breakpoints, dict):
            return {"vertical": {}, "horizontal": {}, "refine": {}}
        return {
            "vertical": breakpoints.get("vertical", {}),
            "horizontal": breakpoints.get("horizontal", {}),
            "refine": breakpoints.get("refine", {}),
        }

    @staticmethod
    def _write_json(path, data):
        """写入 JSON 文件（UTF-8，缩进 2，保留中文）。"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _read_json(path):
        """读取 JSON 文件，返回字典。文件不存在返回空字典。"""
        if not Path(path).exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
