"""software1 / software2 共享 C++ 热点加速扩展的统一 Python 入口。

本模块负责：
  1. 尝试加载编译产物 ``_hxnative`` (``_hxnative.pyd``)。
  2. 若加载失败（缺 .pyd / 缺运行期 DLL / 非目标平台），所有调用点透明回落
     到现有 Python/numpy/PIL/reportlab 实现，应用功能与外观完全不变。
  3. 提供与 C++ 函数一一对应的 Python 签名封装，方便上层调用。

调用约定：
  - 所有上层代码先调用 ``has_native()`` 判断是否可用，再决定走 native 路径。
  - 缺失时本模块不抛异常；仅在调用具体函数且未启用回退时才会显式返回 ``None`` 或抛
    ``RuntimeError``，由调用方自行决定如何回退。
"""

from __future__ import annotations

import importlib
import sys
import threading
from typing import Any, List

__all__ = [
    "has_native",
    "pixmap_bytes_to_qpixmap_buffer",
    "optimize_char_boxes",
    "batch_crop_qimage",
    "pil_to_qimage_buffer",
    "batch_match_font_grade",
    "find_best_offset",
    "extract_ink_mask_fast",
]

# ---------------------------------------------------------------------------
# 加载 native 模块（延迟 + 容错）
# ---------------------------------------------------------------------------
_native = None
_native_err: str | None = None
_hotspot_printed: set = set()
_print_lock = threading.Lock()


def _print_hotspot_status(name: str, hotspot_id: str, enabled: bool) -> None:
    """首次调用某热点时向 stdout 打印 C++ 加速启用状态。

    同一热点在进程生命周期内仅打印一次，线程安全。

    Args:
        name: 热点函数名（如 "batch_match_font_grade"）。
        hotspot_id: 热点标识（如 "H6"）。
        enabled: True 表示 C++ 加速已启用；False 表示不可用，使用 Python 回退。
    """
    with _print_lock:
        if name in _hotspot_printed:
            return
        _hotspot_printed.add(name)
    status = "C++ acceleration enabled" if enabled else "C++ unavailable, using Python fallback"
    try:
        print(f"[native] {hotspot_id} {name}: {status}", flush=True)
    except Exception:
        pass


def _try_load():
    """尝试加载 _hxnative 扩展。成功返回模块对象，失败返回 None 并记录原因。"""
    global _native, _native_err
    if _native is not None:
        return _native
    try:
        # 优先作为本包的子模块加载（_hxnative.pyd 位于本目录）
        _native = importlib.import_module("._hxnative", __package__)
        return _native
    except Exception as exc:  # noqa: BLE001 - 任何失败都视为不可用
        _native_err = f"{type(exc).__name__}: {exc}"
        _native = None
        return None


def has_native() -> bool:
    """返回 C++ 加速扩展是否可用。"""
    return _try_load() is not None


def native_status() -> str:
    """返回可读的加载状态字符串，用于启动期诊断。"""
    if _try_load() is not None:
        return "native: _hxnative loaded"
    return f"native: unavailable ({_native_err})"


# ---------------------------------------------------------------------------
# 公共 API 封装
# ---------------------------------------------------------------------------

def pixmap_bytes_to_qpixmap_buffer(samples, width: int, height: int,
                                   n: int, stride: int = 0) -> bytes | None:
    """H1: 将 fitz pixmap.samples 转换为 QImage 可直接使用的紧凑像素 bytes。

    返回的 bytes 可在 Python 端用 ``QImage(bytes, width, height, width*n,
    QImage.Format_RGB888 / Format_RGBA8888)`` 零拷贝构造。

    缺失 native 时返回 ``None``，调用方应回落到 PIL 路径。
    """
    mod = _try_load()
    if mod is None:
        _print_hotspot_status("pixmap_bytes_to_qpixmap_buffer", "H1", False)
        return None
    try:
        result = mod.pixmap_bytes_to_qpixmap_buffer(samples, width, height, n, stride)
        _print_hotspot_status("pixmap_bytes_to_qpixmap_buffer", "H1", True)
        return result
    except Exception:  # noqa: BLE001 - 运行期错误降级为不可用
        _print_hotspot_status("pixmap_bytes_to_qpixmap_buffer", "H1", False)
        return None


def optimize_char_boxes(mask, chars: List[Any]) -> List[Any] | None:
    """H2: 整页字符边界框批量优化。

    参数:
      mask:  np.ndarray[uint8, 2D, C-contig], 值 0/1。Python 端应传入
             ``(np.any(img < 200, axis=2)).astype(np.uint8)``。
      chars: list[dict], 每个 dict 含 "box" (4 角点或 [x1,y1,x2,y2])。

    返回: list[dict], 每个含 new_x1/new_y1/new_x2/new_y2/valid/box；
          缺失 native 时返回 None，调用方应回落到 numpy 实现。
    """
    mod = _try_load()
    if mod is None:
        _print_hotspot_status("optimize_char_boxes", "H2", False)
        return None
    try:
        result = mod.optimize_char_boxes(mask, chars)
        _print_hotspot_status("optimize_char_boxes", "H2", True)
        return result
    except Exception:  # noqa: BLE001
        _print_hotspot_status("optimize_char_boxes", "H2", False)
        return None


def batch_crop_qimage(page_rgba, w: int, h: int,
                      bboxes: List[List[int]], padding: int) -> List[bytes] | None:
    """H3: 批量字符裁切。

    参数:
      page_rgba: 整页 RGBA 紧凑像素 (buffer / bytes / memoryview)。
      w, h: 整页像素宽高。
      bboxes: list[[x1, y1, x2, y2], ...], 整数坐标。
      padding: 四周扩展像素。

    返回: list[bytes], 每张切片紧凑 RGBA；缺失 native 时返回 None。
    """
    mod = _try_load()
    if mod is None:
        _print_hotspot_status("batch_crop_qimage", "H3", False)
        return None
    try:
        result = mod.batch_crop_qimage(page_rgba, w, h, bboxes, padding)
        _print_hotspot_status("batch_crop_qimage", "H3", True)
        return result
    except Exception:  # noqa: BLE001
        _print_hotspot_status("batch_crop_qimage", "H3", False)
        return None


def pil_to_qimage_buffer(samples, width: int, height: int,
                          mode: str, stride: int = 0) -> bytes | None:
    """H4: 将 PIL Image 原始像素转换为 QImage 可直接使用的紧凑 RGBA bytes。

    在 C++ 内完成模式转换和行间紧凑化，消除 Python 层的 tobytes/convert 开销。

    参数:
        samples: 原始像素 buffer (bytes / memoryview / bytearray)。
        width: 像素宽。
        height: 像素高。
        mode: 源模式，支持 "RGB" 或 "RGBA"。
              "P"/"L" 等模式请先在 Python 端 convert("RGB") 再传入。
        stride: 每行字节数（若紧凑则 = width*channels）。

    返回:
        紧凑 RGBA bytes，可用 QImage(bytes, width, height, width*4,
        QImage.Format_RGBA8888) 零拷贝构造。
        缺失 native 时返回 None，调用方应回落到 H1 或 PIL 路径。
    """
    mod = _try_load()
    if mod is None:
        _print_hotspot_status("pil_to_qimage_buffer", "H4", False)
        return None
    try:
        result = mod.pil_to_qimage_buffer(samples, width, height, mode, stride)
        _print_hotspot_status("pil_to_qimage_buffer", "H4", True)
        return result
    except Exception:  # noqa: BLE001
        _print_hotspot_status("pil_to_qimage_buffer", "H4", False)
        return None


def batch_match_font_grade(line_heights_pt: List[float]) -> List[int] | None:
    """H6: 批量字号档位匹配。

    对一组行框高度（磅值）批量匹配中文字号档位（1-5）。
    含五号放宽逻辑（< 15.0pt 归五号）。

    参数:
        line_heights_pt: 行框高度列表（磅值）。

    返回:
        档位号列表；缺失 native 时使用 Python fallback，功能一致。
    """
    mod = _try_load()
    if mod is not None:
        try:
            result = mod.batch_match_font_grade(line_heights_pt)
            _print_hotspot_status("batch_match_font_grade", "H6", True)
            return result
        except Exception:  # noqa: BLE001
            pass
    _print_hotspot_status("batch_match_font_grade", "H6", False)
    # Python fallback
    return [_match_font_grade_py(h) for h in line_heights_pt]


def _match_font_grade_py(line_height_pt):
    """H6 Python fallback: 单个字号档位匹配。"""
    if not line_height_pt or line_height_pt <= 0:
        return 5
    if line_height_pt < 15.0:
        return 5
    # 与 data_models.match_font_grade 一致的最近邻匹配
    FONT_SIZE_GRADES = {1: 26, 2: 22, 3: 16, 4: 14, 5: 10.5}
    best_grade = 5
    best_diff = None
    for grade, pt in FONT_SIZE_GRADES.items():
        diff = abs(line_height_pt - pt)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_grade = grade
    return best_grade


def find_best_offset(text_mask, ink_mask, radius: int):
    """H7: 文字掩码与墨迹掩码最佳偏移搜索。

    在 (dx,dy) ∈ [-radius, radius] 范围搜索使 text_mask 与 ink_mask 交集最大的偏移。
    缺失 native 时返回 None，调用方应回落到 numpy 实现。

    参数:
        text_mask: np.ndarray, 2D, bool/uint8, 文字掩码。
        ink_mask: np.ndarray, 2D, bool/uint8, 墨迹掩码（四周已扩展 radius）。
        radius: 搜索半径。

    返回:
        (dx, dy) 元组；缺失 native 时返回 None。
    """
    mod = _try_load()
    if mod is None:
        _print_hotspot_status("find_best_offset", "H7", False)
        return None
    try:
        import numpy as _np
        # 强制 uint8 连续数组（bool 数组会自动转换）
        tm = _np.ascontiguousarray(text_mask, dtype=_np.uint8)
        im = _np.ascontiguousarray(ink_mask, dtype=_np.uint8)
        result = mod.find_best_offset(tm, im, int(radius))
        _print_hotspot_status("find_best_offset", "H7", True)
        return result
    except Exception:  # noqa: BLE001
        _print_hotspot_status("find_best_offset", "H7", False)
        return None


def extract_ink_mask_fast(img, bbox, radius: int):
    """H8: 从图像区域 (bbox 扩展 radius) 提取墨迹掩码。

    在 C++ 内裁切 bbox 扩展 radius 的区域 (裁剪到图像边界内) 并二值化，
    使用 PIL 'L' 模式等价灰度公式 L=(R*19595+G*38470+B*7471)>>16, 阈值 200。
    返回紧凑 uint8 mask (0=白, 1=非白)。

    参数:
        img: np.ndarray[uint8, 3D (H,W,C)], RGB(3) 或 RGBA(4)。
        bbox: list[int] = [x1, y1, x2, y2]。
        radius: 四周扩展半径。

    返回:
        (mask_bytes: bytes, out_w: int, out_h: int)；缺失 native 时返回 None。
        mask_bytes 为紧凑 uint8 数组 (0/1), 形状 (out_h, out_w)。
        注意: 返回的是裁切区域 mask, 不含 padding；调用方需自行补齐。
    """
    mod = _try_load()
    if mod is None:
        _print_hotspot_status("extract_ink_mask_fast", "H8", False)
        return None
    try:
        import numpy as _np
        # 强制 uint8 连续数组
        arr = _np.ascontiguousarray(img, dtype=_np.uint8)
        # bbox 显式转 int：与 Python fallback `int(x1 - radius)` 语义对齐，
        # 避免 pybind11 隐式截断浮点 bbox 后再做 int 减法导致的差 1 像素偏差。
        int_bbox = [int(v) for v in bbox]
        result = mod.extract_ink_mask_fast(arr, int_bbox, int(radius))
        _print_hotspot_status("extract_ink_mask_fast", "H8", True)
        return result
    except Exception:  # noqa: BLE001
        _print_hotspot_status("extract_ink_mask_fast", "H8", False)
        return None
