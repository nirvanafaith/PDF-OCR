"""性能基准对比：native (C++) vs fallback (PIL / numpy / pure Python)。

复刻应用真实 fallback 路径，对照三个热点（H1/H2/H3）：
  - H1 native:   _hxnative.pixmap_bytes_to_qpixmap_buffer (C++ 行间紧凑化)
    H1 fallback: PIL.Image.frombytes(...).tobytes()  (应用 _pil_to_pixmap 走的路径)
  - H2 native:   _hxnative.optimize_char_boxes (C++ 单遍 4 边求和)
    H2 fallback: rapidocr_engine._optimize_edge_x/_y 的 numpy 实现
  - H3 native:   _hxnative.batch_crop_qimage (C++ 一次性逐行 memcpy)
    H3 fallback: PIL.Image.crop(bbox) 逐张调用 (.tobytes())

运行：
    cd d:\\hx
    venv_py38\\\\Scripts\\\\python.exe -m software_common.native.tests.bench_perf

输出格式（可粘贴到 checklist.md）：
    H1 native=4.45ms fallback=XXms speedup=XXx reduction=XX%
    H2 native=2.36ms fallback=XXms speedup=XXx reduction=XX%
    H3 native=0.58ms fallback=XXms speedup=XXx reduction=XX%
"""

from __future__ import annotations

import os
import sys
import time

# 确保能 import software_common.native
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from software_common.native import (  # noqa: E402
    has_native,
    pixmap_bytes_to_qpixmap_buffer,
    optimize_char_boxes,
    batch_crop_qimage,
)


# ============================================================================
# 合成测试数据
# ============================================================================

def make_rgba_page(w: int, h: int, seed: int = 0) -> bytes:
    """构造一张合成 RGBA 页面像素 (紧凑, w*h*4 bytes)。"""
    out = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            out[i] = (x + seed) & 0xFF
            out[i + 1] = (y + seed) & 0xFF
            out[i + 2] = ((x + y + seed) * 7) & 0xFF
            out[i + 3] = 0xFF
    return bytes(out)


def make_mask(w: int, h: int, seed: int = 0) -> np.ndarray:
    """构造一张合成二值 mask (uint8, 0/1)。"""
    rng = np.random.default_rng(seed)
    return (rng.random((h, w)) > 0.5).astype(np.uint8)


def make_char_boxes(n: int, w: int, h: int, seed: int = 0) -> list:
    """随机生成 n 个字符 4 角点 box。"""
    rng = np.random.default_rng(seed)
    boxes = []
    for _ in range(n):
        x0 = int(rng.integers(0, max(1, w - 20)))
        y0 = int(rng.integers(0, max(1, h - 20)))
        bw = int(rng.integers(5, 20))
        bh = int(rng.integers(5, 20))
        # 4 角点 [[x,y],[x,y],[x,y],[x,y]]
        boxes.append({
            "box": [[x0, y0], [x0 + bw, y0], [x0 + bw, y0 + bh], [x0, y0 + bh]]
        })
    return boxes


def make_crop_bboxes(n: int, w: int, h: int, seed: int = 0) -> list:
    """随机生成 n 个 crop bbox [x1,y1,x2,y2]。"""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        x1 = int(rng.integers(0, max(1, w - 30)))
        y1 = int(rng.integers(0, max(1, h - 30)))
        x2 = x1 + int(rng.integers(5, 25))
        y2 = y1 + int(rng.integers(5, 25))
        out.append([x1, y1, x2, y2])
    return out


# ============================================================================
# Fallback 实现（复刻应用真实路径）
# ============================================================================

def h1_fallback_pil(samples: bytes, w: int, h: int, n: int) -> bytes:
    """H1 fallback: PIL.Image.frombytes + tobytes (应用 _pil_to_pixmap 走的路径)。"""
    mode = "RGBA" if n == 4 else "RGB"
    img = Image.frombytes(mode, (w, h), samples)
    return img.tobytes()


def h2_fallback_numpy(mask: np.ndarray, chars: list) -> list:
    """H2 fallback: rapidocr_engine._optimize_edge_x/_y 的 numpy 实现。"""
    H, W = mask.shape
    mask_u8 = mask  # already uint8 0/1

    def opt_x(orig_x, y1, y2, edge_len):
        half = edge_len / 2
        ss = max(0, int(orig_x - half))
        se = min(W, int(orig_x + half) + 1)
        if se <= ss or y2 <= y1:
            return orig_x
        # numpy 切片求和
        sub = mask_u8[y1:y2, ss:se]
        col_sums = sub.sum(axis=0)
        oi = int(round(orig_x)) - ss
        oi = max(0, min(oi, len(col_sums) - 1))
        mn = col_sums.min()
        if col_sums[oi] == mn:
            return orig_x
        cands = np.where(col_sums == mn)[0]
        best = min(cands, key=lambda k: abs(int(k) - oi))
        return float(ss + int(best))

    def opt_y(orig_y, x1, x2, edge_len):
        half = edge_len / 2
        ss = max(0, int(orig_y - half))
        se = min(H, int(orig_y + half) + 1)
        if se <= ss or x2 <= x1:
            return orig_y
        sub = mask_u8[ss:se, x1:x2]
        row_sums = sub.sum(axis=1)
        oi = int(round(orig_y)) - ss
        oi = max(0, min(oi, len(row_sums) - 1))
        mn = row_sums.min()
        if row_sums[oi] == mn:
            return orig_y
        cands = np.where(row_sums == mn)[0]
        best = min(cands, key=lambda k: abs(int(k) - oi))
        return float(ss + int(best))

    out = []
    for c in chars:
        box = c["box"]
        xs = [box[i][0] for i in range(4)]
        ys = [box[i][1] for i in range(4)]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        ww = xmax - xmin
        hh = ymax - ymin
        if ww <= 0 or hh <= 0:
            out.append({"valid": False, "box": box})
            continue
        x1c = max(0, int(round(xmin)))
        y1c = max(0, int(round(ymin)))
        x2c = min(W, int(round(xmax)))
        y2c = min(H, int(round(ymax)))
        nx1 = opt_x(xmin, y1c, y2c, ww)
        nx2 = opt_x(xmax, y1c, y2c, ww)
        ny1 = opt_y(ymin, x1c, x2c, hh)
        ny2 = opt_y(ymax, x1c, x2c, hh)
        valid = nx1 < nx2 and ny1 < ny2
        out.append({
            "new_x1": nx1, "new_y1": ny1, "new_x2": nx2, "new_y2": ny2,
            "valid": valid,
            "box": [[nx1, ny1], [nx2, ny1], [nx2, ny2], [nx1, ny2]] if valid else box,
        })
    return out


def h3_fallback_pil(page_rgba: bytes, w: int, h: int, bboxes: list, padding: int) -> list:
    """H3 fallback: PIL.Image.crop 逐张调用 (.tobytes())。"""
    img = Image.frombytes("RGBA", (w, h), page_rgba)
    out = []
    for bb in bboxes:
        cx1 = max(0, bb[0] - padding)
        cy1 = max(0, bb[1] - padding)
        cx2 = min(w, bb[2] + padding)
        cy2 = min(h, bb[3] + padding)
        if cx2 <= cx1 or cy2 <= cy1:
            out.append(b"")
            continue
        crop = img.crop((cx1, cy1, cx2, cy2))
        out.append(crop.tobytes())
    return out


# ============================================================================
# 计时工具
# ============================================================================

def time_call(fn, *args, repeat: int = 1, **kwargs) -> float:
    """返回平均耗时 (毫秒)。"""
    # warmup
    fn(*args, **kwargs)
    t0 = time.perf_counter()
    for _ in range(repeat):
        fn(*args, **kwargs)
    t1 = time.perf_counter()
    return (t1 - t0) / repeat * 1000.0


# ============================================================================
# 主流程
# ============================================================================

def main():
    if not has_native():
        print("ERROR: native 不可用，无法对比。请先编译 _hxnative.pyd", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("性能基准：native (C++) vs fallback (PIL / numpy)")
    print("=" * 60)

    # ----- H1: 200DPI 单页 pixmap → QImage buffer -----
    # 200DPI A4 ≈ 1700x2200, 4 通道
    H1_W, H1_H, H1_N = 1700, 2200, 4
    h1_samples = make_rgba_page(H1_W, H1_H, seed=42)
    H1_REPEAT = 5

    h1_native_ms = time_call(
        pixmap_bytes_to_qpixmap_buffer,
        h1_samples, H1_W, H1_H, H1_N, 0,
        repeat=H1_REPEAT,
    )
    h1_fallback_ms = time_call(
        h1_fallback_pil,
        h1_samples, H1_W, H1_H, H1_N,
        repeat=H1_REPEAT,
    )
    h1_reduction = (1 - h1_native_ms / h1_fallback_ms) * 100 if h1_fallback_ms > 0 else 0

    # ----- H2: 2000 char 边界框优化 -----
    H2_W, H2_H = 200, 200
    h2_mask = make_mask(H2_W, H2_H, seed=7)
    h2_chars = make_char_boxes(2000, H2_W, H2_H, seed=11)
    H2_REPEAT = 3

    h2_native_ms = time_call(
        optimize_char_boxes,
        h2_mask, h2_chars,
        repeat=H2_REPEAT,
    )
    h2_fallback_ms = time_call(
        h2_fallback_numpy,
        h2_mask, h2_chars,
        repeat=H2_REPEAT,
    )
    h2_reduction = (1 - h2_native_ms / h2_fallback_ms) * 100 if h2_fallback_ms > 0 else 0

    # ----- H3: 1 万字符裁切 -----
    H3_W, H3_H = 1700, 2200
    h3_page = make_rgba_page(H3_W, H3_H, seed=99)
    h3_bboxes = make_crop_bboxes(10000, H3_W, H3_H, seed=23)
    H3_REPEAT = 2

    h3_native_ms = time_call(
        batch_crop_qimage,
        h3_page, H3_W, H3_H, h3_bboxes, 2,
        repeat=H3_REPEAT,
    )
    h3_fallback_ms = time_call(
        h3_fallback_pil,
        h3_page, H3_W, H3_H, h3_bboxes, 2,
        repeat=H3_REPEAT,
    )
    h3_reduction = (1 - h3_native_ms / h3_fallback_ms) * 100 if h3_fallback_ms > 0 else 0

    # ----- 输出 -----
    print(f"\nH1 (200DPI RGBA {H1_W}x{H1_H}, repeat={H1_REPEAT}):")
    print(f"  native   = {h1_native_ms:.2f} ms")
    print(f"  fallback = {h1_fallback_ms:.2f} ms (PIL.Image.frombytes + tobytes)")
    print(f"  speedup  = {h1_fallback_ms / h1_native_ms:.2f}x")
    print(f"  reduction= {h1_reduction:.1f}%  (target >=30%)  {'PASS' if h1_reduction >= 30 else 'FAIL'}")

    print(f"\nH2 (2000 chars on {H2_W}x{H2_H} mask, repeat={H2_REPEAT}):")
    print(f"  native   = {h2_native_ms:.2f} ms")
    print(f"  fallback = {h2_fallback_ms:.2f} ms (numpy 切片求和)")
    print(f"  speedup  = {h2_fallback_ms / h2_native_ms:.2f}x")
    print(f"  reduction= {h2_reduction:.1f}%  (target >=50%)  {'PASS' if h2_reduction >= 50 else 'FAIL'}")

    print(f"\nH3 (10000 crops on {H3_W}x{H3_H} RGBA, repeat={H3_REPEAT}):")
    print(f"  native   = {h3_native_ms:.2f} ms")
    print(f"  fallback = {h3_fallback_ms:.2f} ms (PIL.Image.crop 逐张)")
    print(f"  speedup  = {h3_fallback_ms / h3_native_ms:.2f}x")
    print(f"  reduction= {h3_reduction:.1f}%  (target >=30%)  {'PASS' if h3_reduction >= 30 else 'FAIL'}")

    print("\n" + "=" * 60)
    print("汇总（粘贴到 checklist.md）:")
    print(f"H1 native={h1_native_ms:.2f}ms fallback={h1_fallback_ms:.2f}ms "
          f"speedup={h1_fallback_ms / h1_native_ms:.2f}x reduction={h1_reduction:.1f}%")
    print(f"H2 native={h2_native_ms:.2f}ms fallback={h2_fallback_ms:.2f}ms "
          f"speedup={h2_fallback_ms / h2_native_ms:.2f}x reduction={h2_reduction:.1f}%")
    print(f"H3 native={h3_native_ms:.2f}ms fallback={h3_fallback_ms:.2f}ms "
          f"speedup={h3_fallback_ms / h3_native_ms:.2f}x reduction={h3_reduction:.1f}%")


if __name__ == "__main__":
    main()
