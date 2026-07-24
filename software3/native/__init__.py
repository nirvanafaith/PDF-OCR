"""software3 C++ acceleration module.

Provides:
- longest_true_run_batch: batch compute longest True run for 1D bool arrays
- pixmap_to_binary_u8: fitz.Pixmap samples -> binary uint8 array
- compute_iou_batch: batch compute IoU for mask pairs
- batch_compute_iou_with_dilate: batch compute IoU for pixmap pairs
  (with binarization + centered pad + morphological dilation)

若编译产物 _native.*.pyd 不存在或加载失败，所有顶层 API 自动回落到
纯 Python 实现（vector_pdf_ocr.py 内置 fallback），上层调用方无需感知。
"""
import os
import sys

__all__ = [
    "_NATIVE_AVAILABLE",
    "longest_true_run_batch",
    "pixmap_to_binary_u8",
    "compute_iou_batch",
    "batch_compute_iou_with_dilate",
    "compute_iou_with_shifts",
    "has_native",
    "native_status",
]

_NATIVE_AVAILABLE = False
_native_module = None
_native_err = None

try:
    # 尝试加载编译好的 .pyd
    from . import _native
    longest_true_run_batch = _native.longest_true_run_batch
    pixmap_to_binary_u8 = _native.pixmap_to_binary_u8
    compute_iou_batch = _native.compute_iou_batch
    batch_compute_iou_with_dilate = _native.batch_compute_iou_with_dilate
    compute_iou_with_shifts = _native.compute_iou_with_shifts
    _NATIVE_AVAILABLE = True
    print("[Native] C++ acceleration module loaded successfully")
except ImportError as e:
    _native_err = f"{type(e).__name__}: {e}"
    print(f"[Native] C++ module not available, falling back to Python: {e}")
    longest_true_run_batch = None
    pixmap_to_binary_u8 = None
    compute_iou_batch = None
    batch_compute_iou_with_dilate = None
    compute_iou_with_shifts = None
except Exception as e:  # noqa: BLE001 - 任何加载失败都视为不可用
    _native_err = f"{type(e).__name__}: {e}"
    print(f"[Native] C++ module load failed, falling back to Python: {e}")
    longest_true_run_batch = None
    pixmap_to_binary_u8 = None
    compute_iou_batch = None
    batch_compute_iou_with_dilate = None
    compute_iou_with_shifts = None


def has_native() -> bool:
    """返回 C++ 加速扩展是否可用。

    支持通过环境变量 ``HX_NO_NATIVE=1`` 强制禁用 C++ 加速，
    用于隔离 native 崩溃或应急回退到纯 Python 实现。
    """
    if os.environ.get("HX_NO_NATIVE", "").strip() in ("1", "true", "True"):
        return False
    return _NATIVE_AVAILABLE


def native_status() -> str:
    """返回可读的加载状态字符串，用于启动期诊断。"""
    if _NATIVE_AVAILABLE:
        return "native: _native loaded"
    return f"native: unavailable ({_native_err})"
