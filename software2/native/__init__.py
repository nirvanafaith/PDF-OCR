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
from typing import Any, List

__all__ = [
    "has_native",
    "pixmap_bytes_to_qpixmap_buffer",
    "optimize_char_boxes",
    "batch_crop_qimage",
    "pil_to_qimage_buffer",
]

# ---------------------------------------------------------------------------
# 加载 native 模块（延迟 + 容错）
# ---------------------------------------------------------------------------
_native = None
_native_err: str | None = None


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
        return None
    try:
        return mod.pixmap_bytes_to_qpixmap_buffer(samples, width, height, n, stride)
    except Exception:  # noqa: BLE001 - 运行期错误降级为不可用
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
        return None
    try:
        return mod.optimize_char_boxes(mask, chars)
    except Exception:  # noqa: BLE001
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
        return None
    try:
        return mod.batch_crop_qimage(page_rgba, w, h, bboxes, padding)
    except Exception:  # noqa: BLE001
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
        return None
    try:
        return mod.pil_to_qimage_buffer(samples, width, height, mode, stride)
    except Exception:  # noqa: BLE001
        return None


# 启动期在 stderr 打印一次状态（便于诊断；不影响运行）
if hasattr(sys, "stderr") and sys.stderr is not None:
    try:
        print(native_status(), file=sys.stderr)
    except Exception:  # noqa: BLE001 - 诊断打印绝不影响主流程
        pass
