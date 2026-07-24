# -*- coding: utf-8 -*-
"""快速分析 char/ 目录切片的特征分布，辅助设计消歧规则。

不依赖 OCR 引擎，仅计算切片的内在特征：
  - w_pt, h_pt（来自文件名）
  - black_ratio（黑色像素占比）
  - aspect（w/h）
  - cy, cx（黑色像素重心偏移，归一化 [-1,1]）
"""

import os
import re
import sys
from collections import defaultdict

import cv2
import numpy as np

_CURVY_QUOTES = '\u201c\u201d'
_WH_RE = re.compile(r'_w([\d.]+)_h([\d.]+)\.png$', re.IGNORECASE)


def _strip_curly_quotes(name):
    return name.strip(_CURVY_QUOTES)


def _parse_wh(filename):
    m = _WH_RE.search(filename)
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None


def _features(img_path, w_pt, h_pt):
    # cv2.imread 不支持 Unicode 路径（含中文/弯引号），用 imdecode + fromfile 替代
    img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mask = binary > 0
    h_px, w_px = mask.shape
    total = mask.size
    black_ys, black_xs = np.where(mask)
    black_count = int(black_ys.size)
    feat = {
        'w_pt': w_pt, 'h_pt': h_pt,
        'black_ratio': black_count / total if total > 0 else 0,
        'aspect': w_pt / h_pt if h_pt > 0 else 0,
        'cy': 0.0, 'cx': 0.0,
    }
    if black_count > 0:
        if h_px > 1:
            feat['cy'] = (float(black_ys.mean()) - h_px / 2) / (h_px / 2)
        if w_px > 1:
            feat['cx'] = (float(black_xs.mean()) - w_px / 2) / (w_px / 2)
    return feat


def main(char_dir):
    print(f"分析目录: {char_dir}\n")
    groups = defaultdict(list)
    for sub in os.listdir(char_dir):
        full = os.path.join(char_dir, sub)
        if not os.path.isdir(full):
            continue
        label = _strip_curly_quotes(sub)
        for fn in sorted(os.listdir(full)):
            if not fn.lower().endswith('.png'):
                continue
            wh = _parse_wh(fn)
            if wh is None:
                continue
            feat = _features(os.path.join(full, fn), wh[0], wh[1])
            if feat:
                groups[label].append(feat)

    # 输出每类特征统计
    print(f"{'字符':<6}{'样本':>5}{'w_pt':>10}{'h_pt':>10}{'black_r':>10}{'aspect':>10}{'cy':>10}{'cx':>10}")
    for label in sorted(groups.keys()):
        feats = groups[label]
        n = len(feats)
        if n == 0:
            continue
        avg = lambda k: sum(f[k] for f in feats) / n
        mn = lambda k: min(f[k] for f in feats)
        mx = lambda k: max(f[k] for f in feats)
        print(f"{label:<6}{n:>5}"
              f"{avg('w_pt'):>10.2f}{avg('h_pt'):>10.2f}"
              f"{avg('black_ratio'):>10.3f}{avg('aspect'):>10.3f}"
              f"{avg('cy'):>10.3f}{avg('cx'):>10.3f}")
        # 范围
        print(f"{'':>11}"
              f"[{mn('w_pt'):.1f},{mx('w_pt'):.1f}]"
              f"[{mn('h_pt'):.1f},{mx('h_pt'):.1f}]"
              f"[{mn('black_ratio'):.3f},{mx('black_ratio'):.3f}]"
              f"[{mn('aspect'):.3f},{mx('aspect'):.3f}]"
              f"[{mn('cy'):.3f},{mx('cy'):.3f}]"
              f"[{mn('cx'):.3f},{mx('cx'):.3f}]")
    print()

    # 重点输出消歧组的特征详情
    disambig_chars = ['，', '9', '。', 'O', 'o', '0', '.', '、', ')', '）', ',']
    print("=== 消歧相关字符详情 ===")
    for label in disambig_chars:
        if label not in groups:
            continue
        feats = groups[label]
        print(f"\n[{label}] ({len(feats)} samples)")
        for f in feats:
            print(f"  w={f['w_pt']:.2f} h={f['h_pt']:.2f} "
                  f"black={f['black_ratio']:.3f} aspect={f['aspect']:.3f} "
                  f"cy={f['cy']:.3f} cx={f['cx']:.3f}")


if __name__ == '__main__':
    char_dir = sys.argv[1] if len(sys.argv) > 1 else r'd:\hx\software3\char'
    main(char_dir)
