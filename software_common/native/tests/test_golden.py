"""Golden test for `_hxnative` C++ extension.

本脚本对 H1/H2/H3 三个 C++ 热点做"逐字节 / 逐 dict"等价性验证：
  - 当 `_hxnative.pyd` 缺失时：仅验证 fallback 路径可运行（不比对）。
  - 当 `_hxnative.pyd` 存在时：同时跑 native 与 Python fallback，逐字节比对结果。

运行方式：
    cd d:\\hx
    python -m software_common.native.tests.test_golden

不依赖外部 PDF/OCR 数据，全部用合成数据，保证可重跑。
"""

from __future__ import annotations

import os
import sys
import struct
import unittest

# 确保能 import software_common.native
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from software_common.native import (  # noqa: E402
    has_native,
    pixmap_bytes_to_qpixmap_buffer,
    optimize_char_boxes,
    batch_crop_qimage,
)


def _make_rgb_page(w: int, h: int, seed: int = 0) -> bytes:
    """构造一张合成 RGB 页面像素 (紧凑, w*h*3 bytes)。"""
    out = bytearray(w * h * 3)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 3
            out[i] = (x + seed) & 0xFF
            out[i + 1] = (y + seed) & 0xFF
            out[i + 2] = ((x + y + seed) * 7) & 0xFF
    return bytes(out)


def _make_rgba_page(w: int, h: int, seed: int = 0) -> bytes:
    """构造一张合成 RGBA 页面像素 (紧凑, w*h*4 bytes)。"""
    rgb = _make_rgb_page(w, h, seed)
    out = bytearray(w * h * 4)
    for i in range(w * h):
        out[i * 4] = rgb[i * 3]
        out[i * 4 + 1] = rgb[i * 3 + 1]
        out[i * 4 + 2] = rgb[i * 3 + 2]
        out[i * 4 + 3] = 0xFF
    return bytes(out)


class TestH1PixmapToQPixmapBuffer(unittest.TestCase):
    """H1: fitz pixmap → QImage buffer 直通。"""

    def test_rgb_tight_stride(self):
        w, h, n = 8, 6, 3
        samples = _make_rgb_page(w, h, seed=1)
        # native 路径
        buf = pixmap_bytes_to_qpixmap_buffer(samples, w, h, n, 0)
        if has_native():
            self.assertIsNotNone(buf, "native 应返回非 None")
            self.assertEqual(buf, samples, "stride==w*n 时应零拷贝, bytes 相等")
        else:
            self.assertIsNone(buf, "native 不可用时应返回 None")

    def test_rgb_non_tight_stride(self):
        """stride > w*n 时应做行间紧凑化拷贝。"""
        w, h, n = 4, 3, 3
        tight = _make_rgb_page(w, h, seed=2)
        stride = w * n + 5  # 每行多 5 字节 padding
        padded = bytearray()
        for y in range(h):
            padded.extend(tight[y * w * n:(y + 1) * w * n])
            padded.extend(b"\x00" * 5)
        buf = pixmap_bytes_to_qpixmap_buffer(bytes(padded), w, h, n, stride)
        if has_native():
            self.assertIsNotNone(buf)
            self.assertEqual(buf, tight, "非紧凑 stride 应紧凑化为 tight bytes")
        else:
            self.assertIsNone(buf)

    def test_rgba(self):
        w, h, n = 5, 4, 4
        samples = _make_rgba_page(w, h, seed=3)
        buf = pixmap_bytes_to_qpixmap_buffer(samples, w, h, n, 0)
        if has_native():
            self.assertEqual(buf, samples)
        else:
            self.assertIsNone(buf)

    def test_invalid_args(self):
        if has_native():
            # __init__.py 包装器捕获异常并返回 None (fallback 设计)
            result = pixmap_bytes_to_qpixmap_buffer(b"", 0, 0, 3, 0)
            self.assertIsNone(result, "invalid args 应通过 wrapper 捕获异常并返回 None")


class TestH2OptimizeCharBoxes(unittest.TestCase):
    """H2: 字符边界框批量优化。"""

    def _python_reference(self, mask_u8, w, h, chars):
        """复刻 rapidocr_engine._optimize_edge_x/_y 的逻辑作为参考。"""
        # mask_u08: shape [h, w] uint8, 0/1
        def opt_x(orig_x, y1, y2, edge_len):
            half = edge_len / 2
            ss = max(0, int(orig_x - half))
            se = min(w, int(orig_x + half) + 1)
            if se <= ss or y2 <= y1:
                return orig_x
            col_sums = [sum(mask_u8[y * w + ss + k] for y in range(y1, y2))
                        for k in range(se - ss)]
            oi = int(round(orig_x)) - ss
            oi = max(0, min(oi, len(col_sums) - 1))
            mn = min(col_sums)
            if col_sums[oi] == mn:
                return orig_x
            cands = [k for k, v in enumerate(col_sums) if v == mn]
            best = min(cands, key=lambda k: abs(k - oi))
            return float(ss + best)

        def opt_y(orig_y, x1, x2, edge_len):
            half = edge_len / 2
            ss = max(0, int(orig_y - half))
            se = min(h, int(orig_y + half) + 1)
            if se <= ss or x2 <= x1:
                return orig_y
            row_sums = [sum(mask_u8[(ss + k) * w + x] for x in range(x1, x2))
                        for k in range(se - ss)]
            oi = int(round(orig_y)) - ss
            oi = max(0, min(oi, len(row_sums) - 1))
            mn = min(row_sums)
            if row_sums[oi] == mn:
                return orig_y
            cands = [k for k, v in enumerate(row_sums) if v == mn]
            best = min(cands, key=lambda k: abs(k - oi))
            return float(ss + best)

        out = []
        for c in chars:
            xs = [c["box"][i][0] for i in range(4)] if isinstance(c["box"][0], list) else [c["box"][0], c["box"][2]]
            ys = [c["box"][i][1] for i in range(4)] if isinstance(c["box"][0], list) else [c["box"][1], c["box"][3]]
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
            ww = xmax - xmin
            hh = ymax - ymin
            if ww <= 0 or hh <= 0:
                out.append({"valid": False, "box": c["box"]})
                continue
            x1c = max(0, int(round(xmin)))
            y1c = max(0, int(round(ymin)))
            x2c = min(w, int(round(xmax)))
            y2c = min(h, int(round(ymax)))
            nx1 = opt_x(xmin, y1c, y2c, ww)
            nx2 = opt_x(xmax, y1c, y2c, ww)
            ny1 = opt_y(ymin, x1c, x2c, hh)
            ny2 = opt_y(ymax, x1c, x2c, hh)
            valid = nx1 < nx2 and ny1 < ny2
            out.append({
                "new_x1": nx1, "new_y1": ny1, "new_x2": nx2, "new_y2": ny2,
                "valid": valid,
                "box": [[nx1, ny1], [nx2, ny1], [nx2, ny2], [nx1, ny2]] if valid else c["box"],
            })
        return out

    def test_synthetic_page(self):
        w, h = 40, 30
        # 构造 mask: 左半边全白(0), 右半边有条纹(1)
        mask_u08 = bytearray(w * h)
        for y in range(h):
            for x in range(w):
                mask_u08[y * w + x] = 1 if (x >= 20 and (y % 3 == 0)) else 0
        # 用 numpy 构造 (native 需要 ndarray)
        import numpy as np
        mask_arr = np.array(mask_u08, dtype=np.uint8).reshape(h, w)

        chars = [
            {"box": [[10, 5], [18, 5], [18, 12], [10, 12]]},   # 全白区域
            {"box": [[22, 4], [30, 4], [30, 11], [22, 11]]},   # 条纹区域
            {"box": [[5, 20], [35, 20], [35, 28], [5, 28]]},   # 跨区域
        ]

        ref = self._python_reference(mask_u08, w, h, chars)

        if has_native():
            res = optimize_char_boxes(mask_arr, chars)
            self.assertIsNotNone(res)
            self.assertEqual(len(res), len(ref))
            for i, (r, e) in enumerate(zip(res, ref)):
                self.assertEqual(r["valid"], e["valid"], f"char {i} valid mismatch")
                if e["valid"]:
                    self.assertAlmostEqual(r["new_x1"], e["new_x1"], places=4,
                                           msg=f"char {i} new_x1")
                    self.assertAlmostEqual(r["new_y1"], e["new_y1"], places=4,
                                           msg=f"char {i} new_y1")
                    self.assertAlmostEqual(r["new_x2"], e["new_x2"], places=4,
                                           msg=f"char {i} new_x2")
                    self.assertAlmostEqual(r["new_y2"], e["new_y2"], places=4,
                                           msg=f"char {i} new_y2")
        else:
            # fallback: 仅验证参考实现可运行
            self.assertEqual(len(ref), 3)

    def test_empty_chars(self):
        import numpy as np
        mask = np.zeros((10, 10), dtype=np.uint8)
        if has_native():
            res = optimize_char_boxes(mask, [])
            self.assertEqual(res, [])
        else:
            self.assertIsNone(optimize_char_boxes(mask, []))


class TestH3BatchCropQImage(unittest.TestCase):
    """H3: 批量字符裁切。"""

    def test_basic_crops(self):
        w, h = 20, 15
        page = _make_rgba_page(w, h, seed=5)
        bboxes = [
            [2, 3, 8, 10],
            [10, 5, 18, 12],
            [0, 0, 5, 5],
        ]
        padding = 2

        res = batch_crop_qimage(page, w, h, bboxes, padding)
        if has_native():
            self.assertIsNotNone(res)
            self.assertEqual(len(res), len(bboxes))
            for i, bb in enumerate(bboxes):
                cx1 = max(0, bb[0] - padding)
                cy1 = max(0, bb[1] - padding)
                cx2 = min(w, bb[2] + padding)
                cy2 = min(h, bb[3] + padding)
                cw = cx2 - cx1
                ch = cy2 - cy1
                expected_len = cw * ch * 4
                self.assertEqual(len(res[i]), expected_len,
                                 f"crop {i}: expected {expected_len} bytes, got {len(res[i])}")
                # 验证首像素与页面对应位置一致
                if expected_len > 0:
                    src_off = (cy1 * w + cx1) * 4
                    self.assertEqual(res[i][:4], page[src_off:src_off + 4],
                                     f"crop {i}: 首像素与源页面不符")
        else:
            self.assertIsNone(res)

    def test_padding_clamp(self):
        """padding 超出页面边界应被裁剪。"""
        w, h = 10, 10
        page = _make_rgba_page(w, h, seed=6)
        bboxes = [[0, 0, 3, 3]]  # padding=10 会把左上角扩到 (-10,-10)，应 clamp 到 (0,0)
        res = batch_crop_qimage(page, w, h, bboxes, 10)
        if has_native():
            self.assertIsNotNone(res)
            # clamp 后: cx1=0, cy1=0, cx2=min(10,13)=10, cy2=10 → 10*10*4=400
            self.assertEqual(len(res[0]), 400)
        else:
            self.assertIsNone(res)

    def test_empty_bboxes(self):
        w, h = 5, 5
        page = _make_rgba_page(w, h)
        res = batch_crop_qimage(page, w, h, [], 0)
        if has_native():
            self.assertEqual(res, [])
        else:
            self.assertIsNone(res)


class TestFallbackBehavior(unittest.TestCase):
    """验证 fallback 守卫：native 不可用时所有函数返回 None 且不抛异常。"""

    def test_has_native_returns_bool(self):
        self.assertIsInstance(has_native(), bool)

    def test_all_functions_safe_when_no_native(self):
        if has_native():
            self.skipTest("native 可用, 跳过 fallback 路径测试")
        # native 不可用时, 所有函数应返回 None 而非抛异常
        self.assertIsNone(pixmap_bytes_to_qpixmap_buffer(b"\x00" * 12, 2, 2, 3))
        import numpy as np
        self.assertIsNone(optimize_char_boxes(np.zeros((3, 3), dtype=np.uint8), []))
        self.assertIsNone(batch_crop_qimage(b"\x00" * 48, 2, 2, [], 0))


if __name__ == "__main__":
    print(f"native status: {'available' if has_native() else 'unavailable (fallback only)'}")
    unittest.main(verbosity=2)
