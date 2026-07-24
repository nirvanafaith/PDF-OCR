# -*- coding: utf-8 -*-
"""诊断脚本：检查问题样本的图像特征。"""
import os
import sys
import re
import cv2
import fitz
import numpy as np

sys.path.insert(0, r'd:\hx\software3')
from cuda_dll_setup import setup_cuda_dll_paths
setup_cuda_dll_paths()

from ocr_engine.vector_pdf_ocr import _pixmap_to_binary, _get_relative_height

REAL_CHAR_DIR = r'D:\hx\software3\char'
SYNTHETIC_CHAR_DIR = r'D:\hx\software3\char_synthetic'

QUOTE_CHARS = frozenset({'\u201c', '\u201d', '"'})

def parse_dir_name(dirname):
    if len(dirname) == 5 and dirname[0] == 'u' and dirname[1:].isalnum():
        try:
            return chr(int(dirname[1:], 16))
        except ValueError:
            pass
    if len(dirname) >= 2 and dirname[0] in QUOTE_CHARS and dirname[-1] in QUOTE_CHARS:
        inner = dirname[1:-1]
    else:
        inner = dirname
    if inner.endswith('_U'):
        return inner[:-2]
    return inner

def parse_bbox(filename):
    match = re.search(r'_w([\d.]+)_h([\d.]+)\.png$', filename)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))

def parse_fontsize(filename):
    match = re.search(r'_(\d+)p(\d+)pt_', filename)
    if not match:
        return None
    return float(match.group(1)) + float(match.group(2)) / 10.0

def load_pix(png_path):
    pix = fitz.Pixmap(png_path)
    if pix.n >= 5:
        pix = fitz.Pixmap(fitz.csRGB, pix)
    return pix

def compute_features(rect, pix, row_fontsizes):
    w_pt = rect.x1 - rect.x0
    h_pt = rect.y1 - rect.y0
    ar = w_pt / max(h_pt, 1e-6)
    rel_h = _get_relative_height(rect, row_fontsizes)

    result = {
        'w_pt': w_pt, 'h_pt': h_pt, 'ar': round(ar, 2),
        'rel_h': round(rel_h, 4),
        'ar_rel_h': round(ar * rel_h, 4) if rel_h > 0 else 0,
        'pix_w': pix.width, 'pix_h': pix.height,
    }

    if pix.width < 3 or pix.height < 3:
        result['skip'] = True
        return result

    binary = _pixmap_to_binary(pix)
    h, w = binary.shape
    if h < 3 or w < 3:
        result['skip'] = True
        return result

    binary_u8 = (binary.astype(np.uint8)) * 255

    # bottom_ratio
    bottom_start = int(h * 0.75)
    bottom_region = binary[bottom_start:, :]
    bottom_ratio = float(int(bottom_region.sum())) / float(bottom_region.size) if bottom_region.size > 0 else 0.0

    # cy_rel, cx_rel
    cy_rel = 0.5
    cx_rel = 0.5
    total_black = int(binary.sum())
    if total_black > 0:
        try:
            m = cv2.moments(binary_u8)
            m00 = m['m00']
            if m00 > 1e-6:
                cx_rel = float(m['m10'] / m00) / max(float(w - 1), 1.0)
                cy_rel = float(m['m01'] / m00) / max(float(h - 1), 1.0)
        except Exception:
            pass

    # inner_black_ratio
    y0_50 = int(h * 0.25)
    y1_50 = int(h * 0.75)
    x0_50 = int(w * 0.25)
    x1_50 = int(w * 0.75)
    inner_black_ratio = 0.0
    if y1_50 > y0_50 and x1_50 > x0_50:
        center_50 = binary[y0_50:y1_50, x0_50:x1_50]
        if center_50.size > 0:
            inner_black_ratio = float(int(center_50.sum())) / float(center_50.size)

    # outer_aspect + contours
    outer_aspect = 1.0
    num_inner_contours = 0
    num_top_contours = 0
    try:
        contours, hierarchy = cv2.findContours(
            binary_u8, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        if contours:
            outer_idx = max(range(len(contours)),
                            key=lambda i: cv2.contourArea(contours[i]))
            outer_contour = contours[outer_idx]
            if len(outer_contour) >= 5:
                try:
                    (_, _), (axis_w, axis_h), _ = cv2.fitEllipse(outer_contour)
                    major = max(axis_w, axis_h)
                    minor = min(axis_w, axis_h)
                    outer_aspect = major / max(minor, 1e-6)
                except Exception:
                    pass
            if hierarchy is not None:
                hierarchy_arr = hierarchy[0]
                for i, h_row in enumerate(hierarchy_arr):
                    if h_row[3] == -1:
                        num_top_contours += 1
                    if i == outer_idx:
                        continue
                    if h_row[3] != -1:
                        area = cv2.contourArea(contours[i])
                        if area > 2.0:
                            num_inner_contours += 1
    except Exception:
        pass

    # num_segments
    num_segments = 0
    if ar > 3.0 and w_pt > 5.0:
        col_nonzero = binary.any(axis=0)
        if col_nonzero.sum() > 0:
            transitions = np.diff(col_nonzero.astype(np.int8))
            num_segments = int((transitions == 1).sum()) + (1 if col_nonzero[0] else 0)

    # stroke_slope, y_std
    stroke_slope = 0.0
    y_std = 0.0
    y_indices, x_indices = np.where(binary)
    if len(y_indices) >= 10:
        y_mean = y_indices.mean()
        x_mean = x_indices.mean()
        y_dev = y_indices - y_mean
        y_var = (y_dev ** 2).sum()
        if y_var > 1e-6:
            a_slope = (y_dev * (x_indices - x_mean)).sum() / y_var
            stroke_slope = float(a_slope)
    if len(y_indices) > 0:
        y_std = float(y_indices.std()) / max(float(h - 1), 1.0)

    result.update({
        'skip': False,
        'bottom_ratio': round(bottom_ratio, 4),
        'cy_rel': round(cy_rel, 4),
        'cx_rel': round(cx_rel, 4),
        'inner_black_ratio': round(inner_black_ratio, 4),
        'outer_aspect': round(outer_aspect, 4),
        'num_inner_contours': num_inner_contours,
        'num_top_contours': num_top_contours,
        'num_segments': num_segments,
        'stroke_slope': round(stroke_slope, 4),
        'y_std': round(y_std, 4),
    })
    return result


def check_samples(target_chars, max_per_char=5):
    """检查指定字符的样本特征。"""
    for char_dir, label in [(REAL_CHAR_DIR, 'real'), (SYNTHETIC_CHAR_DIR, 'synthetic')]:
        for dirname in os.listdir(char_dir):
            dirpath = os.path.join(char_dir, dirname)
            if not os.path.isdir(dirpath):
                continue
            expected = parse_dir_name(dirname)
            if expected not in target_chars:
                continue
            count = 0
            for filename in sorted(os.listdir(dirpath)):
                if not filename.endswith('.png') or count >= max_per_char:
                    continue
                bbox = parse_bbox(filename)
                if bbox is None:
                    continue
                w_pt, h_pt = bbox
                filepath = os.path.join(dirpath, filename)
                try:
                    pix = load_pix(filepath)
                except Exception:
                    continue
                rect = fitz.Rect(0, 0, w_pt, h_pt)
                row_fontsizes = None
                if label == 'synthetic':
                    fontsize = parse_fontsize(filename)
                    if fontsize is not None:
                        yc = h_pt / 2.0
                        row_key = round(yc / 2.0) * 2.0
                        row_fontsizes = {row_key: fontsize * 0.9}
                feats = compute_features(rect, pix, row_fontsizes)
                print(f"  [{label}] '{expected}' {filename}")
                print(f"    {feats}")
                count += 1


if __name__ == '__main__':
    print("=== ~ all samples ===")
    check_samples({'~'}, max_per_char=20)
    print("\n=== — all samples ===")
    check_samples({'—'}, max_per_char=20)
