# -*- coding: utf-8 -*-
"""消歧准确率测试脚本。

验证 software3 Pass 1.5 消歧函数（规则优先 + NCC 兜底）对消歧组字符的
字符准确率 >= 98%。

消歧组字符：，/9、。/O/o/0、、/）、一/-/—、·/./…/•

两种模式：
  --char-dir : 对 char/ 切片目录做孤立切片消歧（无位置特征 height_ratio，
               仅 NCC + 切片自身特征 black_ratio/aspect/cy/cx）
  --pdf      : 对 PDF 跑完整 Pass1 + Pass1.5 流程，输出消歧统计（无 ground
               truth，不计算准确率，仅输出修正数与决策分布供人工核对）

退出码：准确率 >= 98% 返回 0，否则返回 1。
"""

import argparse
import os
import re
import sys
from collections import defaultdict

# 确保 software3 包可导入（tests/ 子目录向上回溯一层）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cuda_dll_setup import setup_cuda_dll_paths
setup_cuda_dll_paths()

from ocr_engine.vector_pdf_ocr import (
    create_ocr_engine,
    recognize_single_char,  # noqa: F401  签名见模块文档；char-dir 模式复刻其识别分支
    _disambiguate_char,
    _DISAMBIG_GROUPS,
    _DISAMBIG_RULES,
    _DISAMBIG_NCC_THRESHOLD,
    _apply_disambig_rules,
    _get_or_render_candidate_template,
    _compute_pixel_similarity,
    OCR_DPI,
)
import cv2
import fitz
import numpy as np

# 左右弯引号（U+201C / U+201D），char 目录子目录名可能以此包裹
_CURVY_QUOTES = '\u201c\u201d'
_ACCURACY_THRESHOLD = 0.98
_MIN_SAMPLES_PER_CLASS = 5

# 消歧组字符列序（用于混淆矩阵列排版）
_GROUP_CHARS = list(_DISAMBIG_GROUPS.keys())


def _strip_curly_quotes(name):
    """去除子目录名首尾的弯引号，返回真实字符标签。"""
    return name.strip(_CURVY_QUOTES)


# 转义目录名：uXXXX（4 位十六进制）或 X_U（_U 后缀表示大写）
# Windows 文件名非法字符（如 / : \ |）无法直接作为目录名，故用 uXXXX 转义；
# 大写字母 X/O 在某些场景需与对应小写区分，用 _U 后缀标记。
_ESCAPE_HEX_RE = re.compile(r'^u([0-9A-Fa-f]{4})$')


def _normalize_dir_name(sub):
    """将子目录名还原为真实字符标签。

    顺序：
      1. 去除首尾弯引号
      2. 若为 uXXXX 格式（4 位十六进制），还原为对应 Unicode 字符
      3. 若以 _U 结尾（如 X_U、O_U），去掉 _U 后缀
      4. 否则保持原样
    """
    label = _strip_curly_quotes(sub)
    m = _ESCAPE_HEX_RE.match(label)
    if m:
        try:
            return chr(int(m.group(1), 16))
        except (ValueError, OverflowError):
            return label
    if label.endswith('_U') and len(label) > 2:
        return label[:-2]
    return label


# 文件名中的尺寸：draw_017_x197_w2.1_h2.1.png / syn_times_10p5pt_w2.6_h7.4.png
_WH_RE = re.compile(r'_w([\d.]+)_h([\d.]+)\.png$', re.IGNORECASE)


def _parse_wh_from_filename(filename):
    """从文件名解析宽高（pt）。

    匹配 `draw_*_w2.1_h2.1.png` 与 `syn_*_w2.6_h7.4.png` 两种命名。
    """
    m = _WH_RE.search(filename)
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None


def _make_throwaway_page(w_pt, h_pt):
    """构造一个临时 fitz.Page + Rect，用于 NCC 候选模板渲染。

    render_red_char_to_pixmap 内部自建临时文档、忽略传入 page 参数，
    仅依赖 rect 的宽高；故此处 page 仅供签名兼容，rect 提供尺寸即可。
    返回 (doc, page, rect)，doc 需由调用方持有生命周期。
    """
    doc = fitz.open()
    pad = 5.0
    page = doc.new_page(
        width=max(w_pt + pad * 2, 1.0),
        height=max(h_pt + pad * 2, 1.0),
    )
    rect = fitz.Rect(pad, pad, pad + w_pt, pad + h_pt)
    return doc, page, rect


def _ocr_image_array(engine, img_bgr, single_char=True):
    """对单字图像数组做 OCR，复刻 recognize_single_char 的识别分支。

    recognize_single_char(engine, page, drawing) 从 drawing 重绘得到 RGB
    图像后调用 `engine(img, use_det=False, use_cls=False, use_rec=True)`；
    char-dir 模式的输入已是渲染好的 PNG，无法提供 page+drawing，故直接
    复刻该识别调用（RGB 输入与原路径一致）。

    Args:
        engine: RapidOCR 引擎实例
        img_bgr: numpy.ndarray (H, W, 3) BGR 或 (H, W) 灰度
        single_char: 是否只取识别结果首字符

    Returns:
        (text, score): 识别字符文本、置信度
    """
    if img_bgr.ndim == 2:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
    # recognize_single_char 内部传入 RGB（来自 fitz.Pixmap.samples）
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    result = engine(img_rgb, use_det=False, use_cls=False, use_rec=True)
    text = result.txts[0] if result.txts else ''
    score = float(result.scores[0]) if result.scores else 0.0
    if single_char and text:
        text = text[0]
    return text, score


def _binarize_image(img_bgr):
    """读取后的 BGR/灰度图 -> 二值化切片（True=黑色像素，Otsu 反色）。

    与 _slice_char_from_page_pixmap 的二值化策略一致。
    """
    if img_bgr.ndim == 3:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_bgr
    _, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    return binary > 0


def _compute_features_from_binary(slice_binary, w_pt, h_pt, score):
    """从二值切片手动计算消歧特征（line_chars=None，height_ratio=None）。

    复刻 _extract_disambig_features 的公式，但跳过 page_pixmap 切片
    （slice_binary 已直接给出）与 height_ratio（孤立切片无同行字符）。
    """
    h_px, w_px = slice_binary.shape
    total_px = slice_binary.size
    black_ys, black_xs = np.where(slice_binary)
    black_count = int(black_ys.size)

    features = {
        'abs_height': h_pt,  # 字符 bbox 绝对高度（pt），来自文件名
        'height_ratio': None,  # 孤立切片无同行字符
        'black_ratio': black_count / total_px if total_px > 0 else 0.0,
        'aspect': (w_pt / h_pt) if h_pt > 0 else 0.0,
        'cy': 0.0,
        'cx': 0.0,
        'slash_slope': 0.0,  # 主轴斜率 dx/dy，用于 / 检测
        'score': score,
        'width_ratio': None,  # 新增：孤立切片无同行字符
        'dot_count': 0,       # 新增：连通组件数
    }
    if black_count > 0:
        if h_px > 1:
            features['cy'] = (float(black_ys.mean()) - h_px / 2.0) / (h_px / 2.0)
        if w_px > 1:
            features['cx'] = (float(black_xs.mean()) - w_px / 2.0) / (w_px / 2.0)

    # 新增：dot_count 计算（连通组件数，排除背景）
    try:
        slice_u8 = slice_binary.astype(np.uint8)
        _, labels = cv2.connectedComponents(slice_u8)
        features['dot_count'] = max(labels.max(), 0)
    except Exception:
        features['dot_count'] = 0

    # 新增：slash_slope 计算（主轴斜率 dx/dy，复刻 _extract_disambig_features）
    # 竖直字符(1/Ⅰ/I)斜率≈0，/字符斜率<0（图像坐标系 y 向下，x 随 y 增大而减小）
    try:
        if black_count >= 10:
            y_dev = black_ys - black_ys.mean()
            x_dev = black_xs - black_xs.mean()
            y_var = (y_dev ** 2).sum()
            if y_var > 1e-6:
                features['slash_slope'] = float((y_dev * x_dev).sum() / y_var)
    except Exception:
        features['slash_slope'] = 0.0

    return features


def _disambiguate_isolated_slice(
    engine, img_bgr, ocr_text, score, w_pt, h_pt, temp_page
):
    """对孤立切片执行消歧：规则强判定优先 + NCC 兜底。

    与 _disambiguate_char 决策流程一致，但：
      - features 手动计算（height_ratio=None，跳过位置规则）
      - slice_binary 直接来自切片图，而非从 page_pixmap 切片
      - NCC 候选模板经 temp_page + rect 渲染（page 被忽略，仅用 rect 尺寸）

    Args:
        engine: RapidOCR 引擎实例（保留以兼容签名，NCC 兜底不直接使用）
        img_bgr: 切片 BGR 图像
        ocr_text: OCR 识别结果（应在 _DISAMBIG_GROUPS 中）
        score: OCR 置信度
        w_pt / h_pt: 字符 bbox 宽高（pt，来自文件名）
        temp_page: 复用的临时 fitz.Page（render_red_char_to_pixmap 忽略它）

    Returns:
        (result_char, decision_type): 消歧后字符、决策类型
            decision_type: 'rule' / 'ncc' / 'no_decision'
    """
    candidates = _DISAMBIG_GROUPS.get(ocr_text)
    if not candidates:
        return ocr_text, 'no_decision'

    slice_binary = _binarize_image(img_bgr)
    if slice_binary.sum() == 0:
        return ocr_text, 'no_decision'

    features = _compute_features_from_binary(slice_binary, w_pt, h_pt, score)

    # 1. 规则强判定
    rules = _DISAMBIG_RULES.get(ocr_text, {}).get('rules', [])
    rule_result = _apply_disambig_rules(features, rules)
    if rule_result is not None:
        return rule_result, 'rule'

    # Qwen2 语义判定组（横线组：一/-/—）在 char-dir 模式下降级：
    # char-dir 模式无行上下文，Qwen2 无法有效判定，直接进入 NCC 兜底。
    # 本函数不调用 _disambiguate_char，故 Qwen2 步骤自然跳过，无需额外代码。

    # 2. NCC 兜底：渲染候选模板并比对
    rect = fitz.Rect(5, 5, 5 + w_pt, 5 + h_pt)
    font_size_pt = max(h_pt, 1.0)
    best_candidate = ocr_text
    best_ncc = -1.0
    for candidate in candidates:
        try:
            template_binary = _get_or_render_candidate_template(
                temp_page, rect, candidate, font_size_pt
            )
            ncc = _compute_pixel_similarity(slice_binary, template_binary)
            if ncc > best_ncc:
                best_ncc = ncc
                best_candidate = candidate
        except Exception:
            continue

    if best_ncc < _DISAMBIG_NCC_THRESHOLD:
        return ocr_text, 'no_decision'

    return best_candidate, 'ncc'


def _collect_char_samples(char_dir, synthetic_dir):
    """收集消歧组字符的样本（char 主目录 + 合成补充）。

    Returns:
        dict: {label: [(img_path, w_pt, h_pt), ...]}
    """
    samples = defaultdict(list)

    # char 主目录
    if char_dir and os.path.isdir(char_dir):
        for sub in os.listdir(char_dir):
            full = os.path.join(char_dir, sub)
            if not os.path.isdir(full):
                continue
            label = _normalize_dir_name(sub)
            if label not in _DISAMBIG_GROUPS:
                continue
            for fn in sorted(os.listdir(full)):
                if not fn.lower().endswith('.png'):
                    continue
                wh = _parse_wh_from_filename(fn)
                if wh is None:
                    continue
                samples[label].append((os.path.join(full, fn), wh[0], wh[1]))

    # 合成样本补充（< 5 个的字符）
    if synthetic_dir and os.path.isdir(synthetic_dir):
        for sub in os.listdir(synthetic_dir):
            full = os.path.join(synthetic_dir, sub)
            if not os.path.isdir(full):
                continue
            label = _normalize_dir_name(sub)
            if label not in _DISAMBIG_GROUPS:
                continue
            need = _MIN_SAMPLES_PER_CLASS - len(samples.get(label, []))
            if need <= 0:
                continue
            added = 0
            for fn in sorted(os.listdir(full)):
                if added >= need:
                    break
                if not fn.lower().endswith('.png'):
                    continue
                wh = _parse_wh_from_filename(fn)
                if wh is None:
                    continue
                samples[label].append((os.path.join(full, fn), wh[0], wh[1]))
                added += 1

    return samples


def _run_char_dir_mode(char_dir, synthetic_dir, engine):
    """char-dir 模式：孤立切片消歧准确率测试。

    Returns:
        bool: 整体准确率 >= 98% 时为 True
    """
    print(f"=== char-dir 消歧准确率测试 ===")
    print(f"char 目录: {char_dir}")
    print(f"合成补充目录: {synthetic_dir}")
    print()

    samples = _collect_char_samples(char_dir, synthetic_dir)
    if not samples:
        print("[WARN] 未找到任何消歧组字符样本")
        return False

    # 复用一个临时 page 供 NCC 候选模板渲染（page 参数被忽略）
    temp_doc, temp_page, _ = _make_throwaway_page(20.0, 20.0)

    # predictions[label] = list of (predicted_char, decision_type)
    predictions = defaultdict(list)
    try:
        for label in sorted(samples.keys()):
            for img_path, w_pt, h_pt in samples[label]:
                img_bgr = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img_bgr is None:
                    print(f"  [WARN] 无法读取图片: {img_path}")
                    continue
                ocr_text, score = _ocr_image_array(engine, img_bgr, single_char=True)
                if ocr_text in _DISAMBIG_GROUPS:
                    result_char, decision = _disambiguate_isolated_slice(
                        engine, img_bgr, ocr_text, score, w_pt, h_pt, temp_page
                    )
                else:
                    # OCR 不在消歧组，保持原结果（不消歧）
                    result_char = ocr_text
                    decision = 'not_in_group'
                predictions[label].append((result_char, decision))
    finally:
        temp_doc.close()

    _print_results(predictions)
    return _compute_verdict(predictions)


def _print_results(predictions):
    """输出混淆矩阵、每类准确率、整体准确率与验收结论。"""
    # ---------- 混淆矩阵 ----------
    # 列：消歧组字符 + 其他
    columns = _GROUP_CHARS + ['其他']

    def _col_index(pred):
        return pred if pred in _GROUP_CHARS else '其他'

    # 构建计数矩阵 actual -> {col: count}
    matrix = {a: defaultdict(int) for a in predictions}
    for actual, preds in predictions.items():
        for pred, _ in preds:
            matrix[actual][_col_index(pred)] += 1

    print("=== 消歧组字符混淆矩阵 ===")
    header = ['实际\\预测'] + columns
    widths = [max(len(str(h)), 6) for h in header]
    for ci, col in enumerate(columns):
        for a in predictions:
            widths[ci + 1] = max(widths[ci + 1], len(str(matrix[a].get(col, 0))))
    # 表头
    print('  '.join(str(h).rjust(widths[i]) for i, h in enumerate(header)))
    # 行
    for a in sorted(predictions.keys()):
        cells = [a] + [str(matrix[a].get(col, 0)) for col in columns]
        print('  '.join(str(c).rjust(widths[i]) for i, c in enumerate(cells)))
    print()

    # ---------- 每类准确率 ----------
    print("=== 准确率统计 ===")
    print(f"{'字符':<6}{'样本数':>8}{'正确数':>8}{'准确率':>12}")
    total_n = 0
    total_ok = 0
    for label in sorted(predictions.keys()):
        preds = predictions[label]
        n = len(preds)
        ok = sum(1 for p, _ in preds if p == label)
        acc = (ok / n * 100) if n > 0 else 0.0
        print(f"{label:<6}{n:>8}{ok:>8}{acc:>11.1f}%")
        total_n += n
        total_ok += ok
    overall_acc = (total_ok / total_n * 100) if total_n > 0 else 0.0
    print(f"{'总计':<6}{total_n:>8}{total_ok:>8}{overall_acc:>11.1f}%")
    print()

    # ---------- 决策分布 ----------
    decision_counts = defaultdict(int)
    for preds in predictions.values():
        for _, decision in preds:
            decision_counts[decision] += 1
    print("=== 决策分布 ===")
    for dec in ('rule', 'ncc', 'no_decision', 'not_in_group'):
        print(f"  {dec:<14}{decision_counts.get(dec, 0):>6}")
    print()

    # ---------- 验收结论 ----------
    ratio = (total_ok / total_n) if total_n > 0 else 0.0
    print(f"消歧组字符整体准确率: {overall_acc:.1f}% ({total_ok}/{total_n})")
    print(f"验收门槛: {_ACCURACY_THRESHOLD * 100:.1f}%")


def _compute_verdict(predictions):
    """根据整体准确率返回是否达标。"""
    total_n = sum(len(p) for p in predictions.values())
    total_ok = sum(1 for a, preds in predictions.items()
                   for p, _ in preds if p == a)
    if total_n == 0:
        return False
    ratio = total_ok / total_n
    if ratio >= _ACCURACY_THRESHOLD:
        print(f"结果: PASS (退出码 0)")
        return True
    else:
        print(f"结果: FAIL (退出码 1)")
        return False


def _run_pdf_mode(pdf_path):
    """pdf 模式：完整 Pass1 + Pass1.5 流程，输出消歧统计（无准确率）。"""
    from ocr_engine.parallel_runner import ParallelOCRRunner

    print(f"=== PDF 消歧统计测试 ===")
    print(f"PDF: {pdf_path}")
    print()

    if not os.path.isfile(pdf_path):
        print(f"[ERROR] PDF 文件不存在: {pdf_path}")
        return

    doc = fitz.open(pdf_path)
    page_indices = list(range(len(doc)))
    print(f"总页数: {len(page_indices)}")
    if not page_indices:
        doc.close()
        return

    elements_dir = os.path.join(
        os.path.dirname(os.path.abspath(pdf_path)) or '.',
        '_disambig_test_elements',
    )

    runner = ParallelOCRRunner(max_workers=min(4, len(page_indices)))
    runner.prepare_engines()

    logs = []

    def log_cb(msg):
        logs.append(msg)

    try:
        print("[Pass 1] 并行 OCR ...")
        all_page_results = runner.run_pass1_parallel(
            doc, page_indices, elements_dir, output_callback=log_cb
        )
        print(f"[Pass 1] 完成，返回 {len(all_page_results)} 页")

        # 快照消歧前 text（run_pass15_parallel 会就地修改 text 字段）
        before = {
            pi: [r.get('text', '') for r in all_page_results[pi]]
            for pi in all_page_results
        }

        print("[Pass 1.5] 并行消歧 ...")
        logs.clear()
        stat = runner.run_pass15_parallel(
            doc, all_page_results, elements_dir, output_callback=log_cb
        )
        print(f"[Pass 1.5] 完成，total_fix={stat.get('total_fix', 0)}, "
              f"elapsed={stat.get('elapsed', 0):.2f}s")

        # 对比消歧前后，统计修正数与决策分布
        fix_count = 0
        decision_counts = defaultdict(int)
        for pi in all_page_results:
            for i, r in enumerate(all_page_results[pi]):
                if before[pi][i] != r.get('text', ''):
                    fix_count += 1
        # 从日志解析决策类型
        for msg in logs:
            # 形如: ... 'X' → 'Y' (rule: name) / (ncc: 0.85) / (no decision)
            if '(' in msg and ')' in msg:
                inner = msg[msg.rfind('(') + 1: msg.rfind(')')]
                if inner.startswith('rule'):
                    decision_counts['rule'] += 1
                elif inner.startswith('ncc'):
                    decision_counts['ncc'] += 1
                elif inner.startswith('no decision'):
                    decision_counts['no_decision'] += 1
                else:
                    decision_counts['other'] += 1

        print()
        print("=== 消歧统计 ===")
        print(f"消歧修正字符数: {fix_count}")
        print(f"runner 报告 total_fix: {stat.get('total_fix', 0)}")
        print("决策分布:")
        for dec in ('rule', 'ncc', 'no_decision', 'other'):
            print(f"  {dec:<14}{decision_counts.get(dec, 0):>6}")
        print()
        print("=== 消歧日志（供人工核对）===")
        for msg in logs:
            if '→' in msg:
                print(msg)
    finally:
        runner.shutdown()
        doc.close()


def main():
    parser = argparse.ArgumentParser(
        description='消歧准确率测试脚本（消歧组字符准确率 >= 98%）'
    )
    parser.add_argument(
        '--char-dir', default=None,
        help='char 切片目录（不含位置特征，仅 NCC + 切片自身特征）'
    )
    parser.add_argument(
        '--pdf', default=None,
        help='PDF 文件路径（含位置特征的完整 Pass1 + Pass1.5 流程）'
    )
    parser.add_argument(
        '--synthetic-dir', default=None,
        help='合成样本目录（默认为 char-dir 同级的 char_synthetic/）'
    )
    args = parser.parse_args()

    if not args.char_dir and not args.pdf:
        parser.error('必须至少指定 --char-dir 或 --pdf 之一')

    # 合成目录默认值：char-dir 同级的 char_synthetic/
    synthetic_dir = args.synthetic_dir
    if synthetic_dir is None and args.char_dir:
        synthetic_dir = os.path.join(
            os.path.dirname(os.path.abspath(args.char_dir)), 'char_synthetic'
        )

    exit_code = 0

    if args.char_dir:
        engine = create_ocr_engine()
        try:
            passed = _run_char_dir_mode(args.char_dir, synthetic_dir, engine)
            if not passed:
                exit_code = 1
        finally:
            del engine

    if args.pdf:
        _run_pdf_mode(args.pdf)
        # PDF 模式无 ground truth，不影响退出码

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
