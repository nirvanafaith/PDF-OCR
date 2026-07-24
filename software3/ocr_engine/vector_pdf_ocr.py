# -*- coding: utf-8 -*-
"""
矢量 PDF 整行 OCR 与重合率嵌字核心模块

用途:
    矢量字形 PDF 整行 OCR 与重合率嵌字核心模块，从原脚本
    vector_pdf_line_ocr_redover.py 迁移而来，供并行调度器
    （ParallelOCRRunner）与 UI 调用。

    处理"文字以贝塞尔曲线绘制的矢量字形填充路径"形式存在的 PDF 文件。
    对每行字符级 drawing 整体渲染为图像，使用 RapidOCR PP-OCRv6 进行整行
    识别，利用上下文提升特殊符号（句号"。"不应被识成"0"、斜杠"/"不应被
    识成"1"）的识别率；长度不匹配时回退到单字识别。然后将识别出的字符
    以红色宋体（中文 SimSun / ASCII Times New Roman）按"软件二重合率
    嵌字算法"（水平居中 + 垂直居中）叠加写入到原矢量字上方，使红字视觉
    中心与原字符 bbox 中心最大化重合。每字独立 TextWriter，支持在 Adobe
    Acrobat 中逐字选中。

模块结构:
    - 模块级常量: OCR_DPI、_FONT_CACHE
    - 字符特征检测函数: is_punctuation、detect_slash_feature 等
    - OCR 引擎创建: create_ocr_engine
    - 整行 OCR 与嵌字: recognize_line、write_red_char_overlap 等
    - 单页处理接口: process_page（Pass 1）、process_page_post（Pass 1.5/2/3/4）

依赖:
    - PyMuPDF (fitz) >= 1.27.2
    - rapidocr (含 PP-OCRv6 模型)
    - onnxruntime
    - numpy
    - cuda_dll_setup (GPU 加速 DLL 路径设置)
"""

import os
import sys
import time
import json
import re
import threading

import cv2
import fitz
import numpy as np
import onnxruntime as ort
from scipy import ndimage
from rapidocr import (EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR)

# C++ 加速模块（可选，失败时回落到纯 Python）
_NATIVE_AVAILABLE = False
try:
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from native import _NATIVE_AVAILABLE as _NATIVE_OK, longest_true_run_batch, pixmap_to_binary_u8, compute_iou_batch, compute_iou_with_shifts
    _NATIVE_AVAILABLE = _NATIVE_OK
except ImportError:
    pass

_native_printed = False
def _native_log():
    global _native_printed
    if not _native_printed and _NATIVE_AVAILABLE:
        print("[Native] C++ acceleration enabled")
        _native_printed = True

# ==================== 模块级常量 ====================
OCR_DPI = 300

# 字体实例缓存（避免重复加载字体文件）
_FONT_CACHE = {}


def is_punctuation(c):
    """判断字符是否为标点符号（含罗马数字）。

    覆盖：
    - Unicode 'P' 类（Po, Pc, Pd, Pe, Pf, Pi, Ps）
    - 中文标点 3000-303F
    - 全角标点 FF00-FFEF
    - 罗马数字 2160-2182（Ⅰ-Ⅻ）

    Args:
        c: 单个字符
    Returns:
        bool
    """
    if not c or len(c) != 1:
        return False
    cp = ord(c)
    # 罗马数字 Ⅰ-Ⅻ U+2160-U+2182
    if 0x2160 <= cp <= 0x2182:
        return True
    # 中文标点 3000-303F
    if 0x3000 <= cp <= 0x303F:
        return True
    # 全角标点 FF00-FFEF
    if 0xFF00 <= cp <= 0xFFEF:
        return True
    # Unicode 'P' 类
    import unicodedata
    try:
        cat = unicodedata.category(c)
        if cat.startswith('P'):
            return True
    except Exception:
        pass
    return False


def _longest_true_run(arr):
    """计算 1D 布尔数组中最长连续 True 的长度。"""
    if _NATIVE_AVAILABLE and hasattr(arr, '__array__'):
        _native_log()
        result = longest_true_run_batch([np.asarray(arr, dtype=bool)])
        return int(result[0])
    # 原 Python 实现
    max_run = 0
    cur = 0
    for v in arr:
        if v:
            cur += 1
            if cur > max_run:
                max_run = cur
        else:
            cur = 0
    return max_run


def _pixmap_to_binary(pix):
    """将 fitz.Pixmap 转为二值化 numpy 数组（True=黑色像素）。"""
    if _NATIVE_AVAILABLE:
        _native_log()
        # 调用 C++ 实现，返回 uint8 数组（255=黑, 0=白）
        binary_u8 = pixmap_to_binary_u8(pix.samples, pix.width, pix.height, pix.n)
        # 转为 bool 数组（255→True, 0→False）
        return binary_u8 > 0
    # 原 numpy 实现
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    gray = arr.mean(axis=2)
    return gray < 128


# Pass 1.5 分组消歧配置（可扩展：新增组/组内新增字符只需追加条目）
# 键=OCR 识别字符，值=候选组列表（含原字符）
# 当 OCR 识别为组内任一字符时，进入渲染比对消歧
# 规则配置从 char_disambig_rules.json 加载；失败时回落到内置默认
_DISAMBIG_RULES = {}
_DISAMBIG_NCC_THRESHOLD = 0.3
try:
    _rules_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'char_disambig_rules.json'
    )
    with open(_rules_path, 'r', encoding='utf-8') as f:
        _rules_cfg = json.load(f)
    _DISAMBIG_RULES = _rules_cfg.get('groups', {})
    _DISAMBIG_NCC_THRESHOLD = _rules_cfg.get('ncc_threshold', 0.3)
except Exception:
    # 回落到内置默认规则（与原 _DISAMBIG_GROUPS 等价的最小配置）
    _DISAMBIG_RULES = {
        '，': {'candidates': ['，', '9'], 'rules': []},
        '9': {'candidates': ['，', '9'], 'rules': []},
        '。': {'candidates': ['。', 'O'], 'rules': []},
        'O': {'candidates': ['。', 'O'], 'rules': []},
        '、': {'candidates': ['、', ')'], 'rules': []},
        ')': {'candidates': ['、', ')'], 'rules': []},
    }

# 从 _DISAMBIG_RULES 派生快速查询字典：char -> candidates 列表
_DISAMBIG_GROUPS = {char: cfg.get('candidates', []) for char, cfg in _DISAMBIG_RULES.items()}


def _slice_char_from_page_pixmap(page_pixmap, rect, dpi=OCR_DPI):
    """从页面渲染位图按字符 rect 切片字符区域。

    Args:
        page_pixmap: fitz.Pixmap，整页渲染位图
        rect: fitz.Rect，字符 bbox（pt 单位）
        dpi: 渲染 DPI，用于 pt→pixel 坐标转换

    Returns:
        numpy.ndarray: 二值化字符切片（True=黑色像素）
    """
    scale = dpi / 72.0
    x1 = max(0, int(rect.x0 * scale))
    y1 = max(0, int(rect.y0 * scale))
    x2 = min(page_pixmap.width, int(rect.x1 * scale))
    y2 = min(page_pixmap.height, int(rect.y1 * scale))
    if x2 <= x1 or y2 <= y1:
        return np.zeros((1, 1), dtype=bool)

    # 从 pixmap.samples 提取像素数据
    arr = np.frombuffer(page_pixmap.samples, dtype=np.uint8).reshape(
        page_pixmap.height, page_pixmap.width, page_pixmap.n
    )
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    slice_arr = arr[y1:y2, x1:x2].copy()
    gray = slice_arr.mean(axis=2)
    # Otsu 二值化
    _, binary = cv2.threshold(gray.astype(np.uint8), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary > 0


def _render_candidate_template(page, rect, candidate_text, font_size_pt):
    """用字体渲染候选字符为二值化模板。

    Args:
        page: fitz.Page 对象（传给 render_red_char_to_pixmap）
        rect: fitz.Rect，字符 bbox
        candidate_text: str，候选字符
        font_size_pt: float，字号

    Returns:
        numpy.ndarray: 二值化模板（True=黑色像素）
    """
    pix = render_red_char_to_pixmap(page, rect, candidate_text, font_size_pt)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    gray = arr.mean(axis=2)
    _, binary = cv2.threshold(gray.astype(np.uint8), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary > 0


def _compute_pixel_similarity(slice_binary, template_binary):
    """计算两个二值图的归一化互相关（NCC）相似度。

    Args:
        slice_binary: numpy.ndarray，原图切片二值图（bool）
        template_binary: numpy.ndarray，候选模板二值图（bool）

    Returns:
        float: NCC 相似度 [-1.0, 1.0]，越高越相似
    """
    # resize 到相同尺寸（取较大者，保持边缘锐利）
    target_h = max(slice_binary.shape[0], template_binary.shape[0])
    target_w = max(slice_binary.shape[1], template_binary.shape[1])
    if slice_binary.shape != (target_h, target_w):
        slice_resized = cv2.resize(
            slice_binary.astype(np.uint8) * 255, (target_w, target_h),
            interpolation=cv2.INTER_NEAREST
        ) > 0
    else:
        slice_resized = slice_binary
    if template_binary.shape != (target_h, target_w):
        template_resized = cv2.resize(
            template_binary.astype(np.uint8) * 255, (target_w, target_h),
            interpolation=cv2.INTER_NEAREST
        ) > 0
    else:
        template_resized = template_binary

    s = slice_resized.astype(np.float64)
    t = template_resized.astype(np.float64)
    s_mean = s.mean()
    t_mean = t.mean()
    s_centered = s - s_mean
    t_centered = t - t_mean

    numerator = float((s_centered * t_centered).sum())
    denominator = float(np.sqrt((s_centered ** 2).sum() * (t_centered ** 2).sum()))

    # 除零保护：全黑或全白图
    if denominator < 1e-10:
        return 0.0
    return numerator / denominator


def _extract_disambig_features(r, page_pixmap, line_chars=None):
    """提取消歧特征。

    Args:
        r: dict，page_results 项（含 text、rect、score 等）
        page_pixmap: fitz.Pixmap，整页渲染位图
        line_chars: 同行其他字符的 dict 列表（不含当前字符）；
                    None 或空时跳过位置特征 height_ratio

    Returns:
        dict: 包含以下特征：
            - abs_height: 字符 bbox 绝对高度（pt 单位），标点<3pt 数字字母>3pt
            - height_ratio: 切片高度 / 同行最大字符高度（无同行字符时为 None）
            - width_ratio: 字符宽度 / 同行最大字符宽度（无同行字符时为 None）
            - black_ratio: 黑色像素占比
            - dot_count: 切片二值图连通组件数（背景除外），用于识别 … (3个点)
            - aspect: 宽高比 (w/h)
            - cy: 黑色像素重心 y 偏移（归一化 [-1, 1]，正=偏下）
            - cx: 黑色像素重心 x 偏移（归一化 [-1, 1]，正=偏右）
            - slash_slope: 主轴斜率 dx/dy（图像坐标系y向下），竖直字符≈0，/字符<0
            - score: OCR score（从 r 获取）
    """
    rect = r.get('rect')
    features = {
        'abs_height': 0.0,
        'height_ratio': None,
        'width_ratio': None,
        'black_ratio': 0.0,
        'dot_count': 0,
        'aspect': 0.0,
        'cy': 0.0,
        'cx': 0.0,
        'slash_slope': 0.0,
        'score': r.get('score', 1.0),
    }

    # abs_height: 字符 bbox 绝对高度（pt），标点(。/，/、) <3pt，数字字母(9/0/O)>3pt
    if rect is not None:
        features['abs_height'] = rect.y1 - rect.y0

    # height_ratio：需要同行其他字符
    if line_chars:
        try:
            other_heights = [
                (other.get('rect').y1 - other.get('rect').y0)
                for other in line_chars
                if other.get('rect') is not None
            ]
            other_heights = [h for h in other_heights if h > 0]
            if other_heights and rect is not None:
                max_other_h = max(other_heights)
                cur_h = rect.y1 - rect.y0
                if max_other_h > 0:
                    features['height_ratio'] = cur_h / max_other_h
        except Exception:
            features['height_ratio'] = None

    # width_ratio：字符宽度 / 同行最大字符宽度
    if line_chars:
        try:
            other_widths = [
                (other.get('rect').x1 - other.get('rect').x0)
                for other in line_chars
                if other.get('rect') is not None
            ]
            other_widths = [w for w in other_widths if w > 0]
            if other_widths and rect is not None:
                max_other_w = max(other_widths)
                cur_w = rect.x1 - rect.x0
                if max_other_w > 0:
                    features['width_ratio'] = cur_w / max_other_w
        except Exception:
            features['width_ratio'] = None

    if rect is None:
        return features

    # 切片二值图计算 black_ratio / aspect / cy / cx
    slice_binary = _slice_char_from_page_pixmap(page_pixmap, rect)
    h_px = slice_binary.shape[0]
    w_px = slice_binary.shape[1]

    # aspect: 宽高比 (pt 单位，rect 更稳定)
    cur_h_pt = rect.y1 - rect.y0
    if cur_h_pt > 0:
        features['aspect'] = (rect.x1 - rect.x0) / cur_h_pt

    total_px = slice_binary.size
    if total_px == 0:
        return features

    black_ys, black_xs = np.where(slice_binary)
    black_count = black_ys.size
    features['black_ratio'] = black_count / total_px if total_px > 0 else 0.0

    # dot_count: 连通组件数（排除背景），用于识别 … (3个点)
    try:
        slice_u8 = slice_binary.astype(np.uint8)
        _, labels = cv2.connectedComponents(slice_u8)
        features['dot_count'] = max(labels.max(), 0)  # labels.max() = 组件数-1（排除背景0）
    except Exception:
        features['dot_count'] = 0

    # slash_slope: 主轴斜率 dx/dy（用于 / 检测）
    # 竖直字符(1/Ⅰ/I)斜率≈0，/字符斜率<0（图像坐标系y向下，x随y增大而减小）
    try:
        if black_count >= 10:
            y_dev = black_ys - black_ys.mean()
            x_dev = black_xs - black_xs.mean()
            y_var = (y_dev ** 2).sum()
            if y_var > 1e-6:
                features['slash_slope'] = float((y_dev * x_dev).sum() / y_var)
    except Exception:
        features['slash_slope'] = 0.0

    if black_count > 0:
        # cy: (black_ys.mean() - h_px/2) / (h_px/2)，正=偏下
        if h_px > 1:
            features['cy'] = (float(black_ys.mean()) - h_px / 2.0) / (h_px / 2.0)
        # cx: (black_xs.mean() - w_px/2) / (w_px/2)，正=偏右
        if w_px > 1:
            features['cx'] = (float(black_xs.mean()) - w_px / 2.0) / (w_px / 2.0)

    return features


def _apply_disambig_rules(features, rules):
    """根据规则强判定返回候选字符，无匹配返回 None。

    Args:
        features: _extract_disambig_features 返回的 dict
        rules: 该消歧组的 rules 列表

    Returns:
        str or None: 匹配的候选字符，或 None

    规则可附带 dependencies 字段（字符串列表，如 'abs_height < 3.2'）：
    主条件匹配后，须全部 dependencies 满足才采纳该规则；任一依赖失败则跳过该规则。
    """
    if not rules:
        return None

    for rule in rules:
        feat_name = rule.get('feature')
        if feat_name is None:
            continue
        feat_val = features.get(feat_name)
        # height_ratio 等位置特征可能为 None（无同行字符），跳过该规则
        if feat_val is None:
            continue

        threshold = rule.get('threshold')
        op = rule.get('op')
        matched = False
        try:
            if op == '<':
                matched = feat_val < threshold
            elif op == '>':
                matched = feat_val > threshold
            elif op == '<=':
                matched = feat_val <= threshold
            elif op == '>=':
                matched = feat_val >= threshold
            elif op == '==':
                matched = (feat_val == threshold)
            elif op == 'between':
                # threshold 为 [min, max] 列表
                if isinstance(threshold, (list, tuple)) and len(threshold) == 2:
                    matched = (threshold[0] <= feat_val <= threshold[1])
            else:
                # 未知操作符，跳过
                continue
        except Exception:
            continue

        if matched:
            # 附加依赖条件（dependencies）：主条件匹配后须全部满足
            deps = rule.get('dependencies')
            if deps:
                if not _check_rule_dependencies(features, deps):
                    continue
            return rule.get('candidate')

    return None


def _check_rule_dependencies(features, dependencies):
    """校验规则的附加依赖条件列表。

    每个依赖为 'feature op value' 字符串（如 'abs_height < 3.2'），
    按 <, <=, >, >=, == 比较 features 中对应特征值与 value（float）。
    特征值为 None 或解析失败视为该依赖失败。

    Args:
        features: _extract_disambig_features 返回的 dict
        dependencies: list[str]，依赖条件列表

    Returns:
        bool: 全部依赖满足返回 True，任一失败返回 False
    """
    if not dependencies:
        return True
    for dep in dependencies:
        try:
            parts = str(dep).split()
            if len(parts) != 3:
                return False
            dep_feat, dep_op, dep_val_str = parts
            dep_val = float(dep_val_str)
            feat_val = features.get(dep_feat)
            if feat_val is None:
                return False
            if dep_op == '<':
                ok = feat_val < dep_val
            elif dep_op == '>':
                ok = feat_val > dep_val
            elif dep_op == '<=':
                ok = feat_val <= dep_val
            elif dep_op == '>=':
                ok = feat_val >= dep_val
            elif dep_op == '==':
                ok = (feat_val == dep_val)
            else:
                return False
            if not ok:
                return False
        except Exception:
            return False
    return True


# Qwen2-1.5B 语言模型（懒加载，用于 一 vs — 语义消歧）
_QWEN2_MODEL = None
_QWEN2_TOKENIZER = None
_QWEN2_LOCK = threading.Lock()
_QWEN2_LOAD_FAILED = False  # 加载失败标记，避免重复尝试


def _get_qwen2_model():
    """懒加载 Qwen2-1.5B 模型（双重检查锁定）。

    Returns:
        (model, tokenizer) 或 (None, None)（不可用时）
    """
    global _QWEN2_MODEL, _QWEN2_TOKENIZER, _QWEN2_LOAD_FAILED
    if _QWEN2_LOAD_FAILED:
        return None, None
    if _QWEN2_MODEL is not None:
        return _QWEN2_MODEL, _QWEN2_TOKENIZER
    with _QWEN2_LOCK:
        if _QWEN2_MODEL is not None:
            return _QWEN2_MODEL, _QWEN2_TOKENIZER
        if _QWEN2_LOAD_FAILED:
            return None, None
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            # 优先使用本地模型目录（避免联网下载，解决 HuggingFace 超时问题）
            # 优先级：环境变量 HX_QWEN2_MODEL > 本地默认路径(若存在) > HF 在线
            local_model_path = os.path.join(
                os.path.dirname(__file__), '..', 'models', 'Qwen2-1.5B'
            )
            if os.path.isdir(local_model_path) and os.listdir(local_model_path):
                model_name = local_model_path
                # 离线加载，避免 transformers 联网检查
                os.environ.setdefault('HF_HUB_OFFLINE', '1')
                os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
                load_kwargs = {'local_files_only': True}
            else:
                model_name = os.environ.get('HX_QWEN2_MODEL', 'Qwen/Qwen2-1.5B')
                load_kwargs = {}
            _QWEN2_TOKENIZER = AutoTokenizer.from_pretrained(model_name, **load_kwargs)
            _QWEN2_MODEL = AutoModelForCausalLM.from_pretrained(
                model_name,
                device_map='auto',
                dtype=torch.float16,
                **load_kwargs,
            )
            _QWEN2_MODEL.eval()
            print(f"[Qwen2] 模型加载成功: {model_name}")
        except Exception as e:
            print(f"[Qwen2] WARN: 模型不可用，一/— 消歧将降级为 NCC: {e}")
            _QWEN2_LOAD_FAILED = True
            return None, None
    return _QWEN2_MODEL, _QWEN2_TOKENIZER


def _build_line_context(page_results, target_idx, window=15):
    """从 page_results 构建目标字符的行上下文文本。

    取目标字符位置之前 window 个字符作为上下文（causal LM 仅需前文）。

    Args:
        page_results: list[dict]，当页所有字符结果（含 text, rect 等）
        target_idx: int，目标字符在 page_results 中的索引
        window: int，上下文窗口大小

    Returns:
        str: 上下文文本
    """
    if not page_results or target_idx < 0 or target_idx >= len(page_results):
        return ''
    start = max(0, target_idx - window)
    chars = []
    for i in range(start, target_idx):
        text = page_results[i].get('text', '')
        if text:
            chars.append(text)
    return ''.join(chars)


def _qwen2_lm_disambig(context_text, candidates_list):
    """用 Qwen2-1.5B 语言模型比较多个候选字符的 logprob，返回最优候选。

    借鉴 pycorrector 的 perplexity 评分架构：
    - 将 context + candidate 送入模型
    - 取候选字符 token 位置的 log_softmax 值
    - 选 logprob 最高者，与次高者差值不足 0.5 时返回 None 触发 NCC 兜底

    Args:
        context_text: str，前文上下文
        candidates_list: list[str]，候选字符列表（2 个或以上）

    Returns:
        tuple: (best_candidate, logprob_diff)
            - best_candidate: str 或 None（不可用/低置信度时为 None）
              返回的是候选字符本身（如 '一'、'—'、'1'、'Ⅰ'、'I'、'x'、'×'）
            - logprob_diff: float，最高与次高 logprob 之差
    """
    import torch
    import torch.nn.functional as F

    model, tokenizer = _get_qwen2_model()
    if model is None or tokenizer is None:
        return None, 0.0

    if not candidates_list or len(candidates_list) < 2:
        return None, 0.0

    try:
        scored = []  # [(candidate, logprob), ...]
        for candidate in candidates_list:
            text = context_text + candidate
            inputs = tokenizer(text, return_tensors='pt')
            # 将输入移到模型所在设备
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = model(**inputs)

            # 取最后一个非pad token位置的logits
            input_len = inputs['input_ids'].shape[1]
            # 候选字符的token位置 = input_len - 1（最后一个token）
            logits = outputs.logits[0, input_len - 1, :]
            log_probs = F.log_softmax(logits, dim=-1)

            # 获取候选字符的token id
            candidate_ids = tokenizer.encode(candidate, add_special_tokens=False)
            if not candidate_ids:
                scored.append((candidate, float('-inf')))
                continue
            # 取候选字符第一个token的logprob
            scored.append((candidate, float(log_probs[candidate_ids[0]].item())))

        # 按 logprob 降序排序
        scored.sort(key=lambda item: item[1], reverse=True)
        top1_candidate, top1_logprob = scored[0]
        top2_logprob = scored[1][1]
        logprob_diff = top1_logprob - top2_logprob

        if logprob_diff < 0.5:
            # 低置信度，返回 None 触发 NCC 兜底
            return None, logprob_diff
        return top1_candidate, logprob_diff
    except Exception as e:
        print(f"[Qwen2] WARN: 推理失败: {e}")
        return None, 0.0


def _disambiguate_char(page, r, page_pixmap, page_idx, line_chars=None,
                       page_results=None, r_idx=None):
    """单字符分组消歧：规则强判定 → Qwen2 语义判定 → NCC 兜底。

    决策流程：
      1. 规则强判定（基于 width_ratio/dot_count/aspect/cy 等特征）
      2. Qwen2 语义判定（仅 semantic:true 组，规则未命中时）
      3. NCC 像素相似度比对（带模板缓存）
      4. NCC 低于阈值时保持原 OCR 结果

    Args:
        page: fitz.Page 对象
        r: dict，page_results 项（含 text、rect、drawing）
        page_pixmap: fitz.Pixmap，整页渲染位图
        page_idx: int，页面索引（用于日志）
        line_chars: 同行其他字符的 dict 列表（不含当前字符）；
                    None 或空时跳过位置特征 height_ratio
        page_results: list[dict]，当页所有字符结果（用于构建 Qwen2 上下文）；
                      None 时 Qwen2 降级为无上下文
        r_idx: int，目标字符在 page_results 中的索引（用于 Qwen2 上下文）

    Returns:
        tuple: (result_char, decision_info)
            - result_char: str，消歧后的字符
            - decision_info: str，决策依据，例如
              "rule: comma_low_height" / "qwen2: logprob_diff=1.23" /
              "ncc: 0.85" / "no decision"
    """
    original_text = r.get('text', '')
    candidates = _DISAMBIG_GROUPS.get(original_text)
    if not candidates:
        return original_text, 'no decision'

    # Ⅰ 跨组路由：OCR 输出 Ⅰ 时，按 aspect 判定圆点/长条
    route_info = None
    if original_text == 'Ⅰ':
        rect = r.get('rect')
        if rect is not None:
            cur_h = rect.y1 - rect.y0
            if cur_h > 0:
                aspect_val = (rect.x1 - rect.x0) / cur_h
            else:
                aspect_val = 0.0
            if aspect_val > 0.7:
                # 圆点 → 路由到点号组 (Group 5)
                route_info = f'route: Ⅰ → dot_group (aspect={aspect_val:.2f})'
                original_text = '.'  # 改写为点号组触发键
                candidates = _DISAMBIG_GROUPS.get(original_text)
                if not candidates:
                    return r.get('text', ''), 'no decision'
            else:
                # 长条 → 进入冒号数字组 (Group 6)，candidates 已正确加载
                route_info = f'route: Ⅰ → colon_group (aspect={aspect_val:.2f})'

    rect = r.get('rect')
    if rect is None:
        return original_text, 'no decision'

    # 提取特征
    features = _extract_disambig_features(r, page_pixmap, line_chars)

    # 规则强判定
    group_cfg = _DISAMBIG_RULES.get(original_text, {})
    rules = group_cfg.get('rules', [])
    rule_result = _apply_disambig_rules(features, rules)
    if rule_result is not None:
        # 找到匹配规则名用于日志
        rule_name = 'unknown_rule'
        for rule in rules:
            if rule.get('candidate') == rule_result:
                feat_val = features.get(rule.get('feature'))
                if feat_val is None:
                    continue
                op = rule.get('op')
                threshold = rule.get('threshold')
                matched = False
                try:
                    if op == '<':
                        matched = feat_val < threshold
                    elif op == '>':
                        matched = feat_val > threshold
                    elif op == '<=':
                        matched = feat_val <= threshold
                    elif op == '>=':
                        matched = feat_val >= threshold
                except Exception:
                    matched = False
                if matched:
                    rule_name = rule.get('name', 'unknown_rule')
                    break
        info = f"rule: {rule_name}"
        if route_info:
            info = f"{route_info}; {info}"
        return rule_result, info

    # Qwen2 语义判定（仅 semantic:true 组）
    if group_cfg.get('semantic', False):
        # 构建 Qwen2 上下文（需要 page_results 和 r_idx）
        context_text = ''
        if page_results is not None and r_idx is not None:
            context_text = _build_line_context(page_results, r_idx, window=15)

        # Group 4 (一/-/—/_): 2 candidates
        if original_text in ('一', '—', '-', '_'):
            winner, logprob_diff = _qwen2_lm_disambig(context_text, ['一', '—'])
            if winner is not None:
                info = f"qwen2: logprob_diff={logprob_diff:.2f}"
                if route_info:
                    info = f"{route_info}; {info}"
                return winner, info  # winner is already the candidate char

        # Group 6 (：/1//Ⅰ/I): 3 candidates (rules already filtered out ： and /)
        elif original_text in ('：', ':', '1', '/', 'Ⅰ', 'I'):
            winner, logprob_diff = _qwen2_lm_disambig(context_text, ['1', 'Ⅰ', 'I'])
            if winner is not None:
                info = f"qwen2: logprob_diff={logprob_diff:.2f}"
                if route_info:
                    info = f"{route_info}; {info}"
                return winner, info

        # Group 7 (x/X/×): 2 candidates (rules already filtered out X)
        elif original_text in ('x', 'X', '×'):
            winner, logprob_diff = _qwen2_lm_disambig(context_text, ['x', '×'])
            if winner is not None:
                info = f"qwen2: logprob_diff={logprob_diff:.2f}"
                if route_info:
                    info = f"{route_info}; {info}"
                return winner, info

    # NCC 兜底
    slice_binary = _slice_char_from_page_pixmap(page_pixmap, rect)
    if slice_binary.sum() == 0:
        # 原图切片全白，无法比较
        return original_text, 'no decision'

    font_size_pt = max(rect.y1 - rect.y0, 1.0)
    best_candidate = original_text
    best_ncc = -1.0
    for candidate in candidates:
        try:
            template_binary = _get_or_render_candidate_template(
                page, rect, candidate, font_size_pt
            )
            ncc = _compute_pixel_similarity(slice_binary, template_binary)
            if ncc > best_ncc:
                best_ncc = ncc
                best_candidate = candidate
        except Exception:
            continue

    # 阈值保护
    if best_ncc < _DISAMBIG_NCC_THRESHOLD:
        return original_text, 'no decision'

    return best_candidate, f"ncc: {best_ncc:.3f}"


# DEPRECATED: 原消歧辅助函数，classify_punctuation_by_features 已删除
# 保留函数定义，后续重新实现消歧时可能复用
def detect_slash_feature(pix):
    """检测图像中是否存在 "/" 的斜线特征。

    "/" 是一条从右上到左下的斜线（在图像坐标系中，y 轴向下）。
    旧方法沿 -45° 对角线扫描最长连续黑色像素，但对 1 像素宽的细斜线
    容易失效（斜率非精确 -1 时对角线上黑色像素不连续）。

    新方法用线性回归检测主轴方向：
    - 找到所有黑色像素的位置 (x, y)
    - 用最小二乘法拟合 x = a*y + b
    - 如果斜率 a < -0.5（x 随 y 增加而减少）且拟合优度 R² > 0.8
      （黑色像素沿直线分布），则为 "/"

    判定：
    - 黑色像素数量 >= 10（避免噪点）
    - 线性回归斜率 a < -0.5（负斜率，从右上到左下）
    - 拟合优度 R² > 0.8（黑色像素沿直线分布）
    """
    binary = _pixmap_to_binary(pix)
    h, w = binary.shape

    # 找到所有黑色像素的位置
    y_indices, x_indices = np.where(binary)
    if len(y_indices) < 10:
        return False

    # 线性回归：x = a*y + b
    y_mean = y_indices.mean()
    x_mean = x_indices.mean()
    y_dev = y_indices - y_mean
    x_dev = x_indices - x_mean
    y_var = (y_dev ** 2).sum()
    if y_var < 1e-6:
        return False  # 所有黑色像素在同一行，无法计算斜率
    a = (y_dev * x_dev).sum() / y_var  # 斜率
    b = x_mean - a * y_mean  # 截距

    # 计算拟合优度 R²
    x_pred = a * y_indices + b
    ss_res = ((x_indices - x_pred) ** 2).sum()
    ss_tot = (x_dev ** 2).sum()
    if ss_tot < 1e-6:
        return False  # 所有黑色像素在同一列
    r_squared = 1 - ss_res / ss_tot

    # 判定 1：负斜率 + 高拟合度（主方法）
    if a < -0.5 and r_squared > 0.8:
        return True

    # 判定 2：投影特征法回退（当线性回归 R² 不够时）
    # 适用于弧度较大的 Bezier 斜线，线性回归拟合度不够但仍是斜线
    if r_squared < 0.8 and a < -0.5:
        # 计算每列黑色像素数（水平方向投影）
        col_counts = binary.sum(axis=0)  # shape (w,)
        # 有黑色像素的列数（分布跨度）
        nonzero_cols = int((col_counts > 0).sum())
        # 分布跨度 > 0.7*w：黑色像素水平分布较广
        if nonzero_cols > 0.7 * w:
            # 无明显集中峰值：最大列像素数 < 平均每列像素数 × 1.5
            total_black = int(col_counts.sum())
            avg_per_col = total_black / max(w, 1)
            max_col = int(col_counts.max())
            if max_col < avg_per_col * 1.5:
                return True
    return False


def detect_roman_iv_feature(pix):
    """检测图像中是否含 "Ⅳ" 结构（左 I + 右 V）。

    Ⅳ 与 U 的关键视觉差异：
    - Ⅳ 是 I + V 两个独立字符的组合，V 的右斜边在右半前几列，
      有较长连续黑色像素（≥ 图像高度 0.25 倍）
    - U 是连体字符，右半前几列是底部弧形，连续黑色像素很短

    判定：
    - 左半部分：存在某列竖直连续黑色像素长度 ≥ 图像高度 0.5 倍（I 形）
    - 右半部分：黑色像素总数 > 0（存在 V 形或其他笔画）
    - 右半前 4 列中最大连续黑色像素 ≥ 图像高度 0.25 倍（V 形右斜边）

    注：此函数仅在 OCR 识为 'U'/'V'/'IV'/'Ⅴ' 时被调用，
    用于区分 Ⅳ（有左 I + 右 V 斜边）与 U/V/Ⅴ（无此结构）。
    """
    binary = _pixmap_to_binary(pix)
    h, w = binary.shape
    mid = w // 2
    if mid < 2:
        return False
    left = binary[:, :mid]
    right = binary[:, mid:]

    # 1. 左侧 I 形：列方向最长连续黑色像素
    col_runs = np.zeros(mid)
    for c in range(mid):
        col_runs[c] = _longest_true_run(left[:, c])
    if col_runs.max() < 0.5 * h:
        return False

    # 2. 右侧需有内容（V 形或其他笔画），避免误判纯左侧 I（如 Ⅰ）
    if int(right.sum()) == 0:
        return False

    # 3. 区分 Ⅳ 与 U：右半前 4 列中是否有 V 形右斜边
    # Ⅳ 中 V 的右斜边在右半前几列，连续黑色像素较长（≥ 0.25*h）
    # U 中底部弧形在右半前几列，连续黑色像素很短（< 0.25*h）
    right_w = w - mid
    right_col_runs = np.zeros(right_w)
    for c in range(right_w):
        right_col_runs[c] = _longest_true_run(right[:, c])
    check_cols = min(4, right_w)
    if check_cols < 1:
        return False
    right_front_max = right_col_runs[:check_cols].max()
    if right_front_max < 0.25 * h:
        return False

    return True


# DEPRECATED: 原消歧辅助函数，classify_punctuation_by_features 已删除
def detect_ellipsis_feature(rect):
    """基于 bbox 宽高比判断是否为水平省略号 "…"。

    "…"（U+2026）是三点水平排列，bbox 宽度远大于高度。
    判定：宽 > 高 × 3
    """
    w = rect.x1 - rect.x0
    h = rect.y1 - rect.y0
    if h <= 0:
        return False
    return w > h * 3


# DEPRECATED: 原消歧辅助函数，classify_punctuation_by_features 已删除
# 保留函数定义，后续重新实现消歧时可能复用
def detect_dash_feature(pix, rect):
    """检测图像中是否为 "-"（细长水平线）。

    判定条件：
    - w > h*3（bbox 宽高比，从 rect 计算）
    - 黑色像素在垂直方向的投影（每行黑色像素数）集中在中间 30% 区域
      （即中间 30% 行的黑色像素数 > 总数的 70%）

    Args:
        pix: fitz.Pixmap
        rect: fitz.Rect

    Returns:
        bool
    """
    w = rect.x1 - rect.x0
    h = rect.y1 - rect.y0
    if h <= 0 or w <= 0:
        return False
    # 宽高比条件：w > h*3（细长水平线）
    if w <= h * 3:
        return False
    binary = _pixmap_to_binary(pix)
    h_pix, w_pix = binary.shape
    # 每行黑色像素数（垂直方向投影）
    row_counts = binary.sum(axis=1)  # shape (h_pix,)
    total = int(row_counts.sum())
    if total == 0:
        return False
    # 中间 30% 区域：从 35% 到 65%
    mid_start = int(h_pix * 0.35)
    mid_end = int(h_pix * 0.65)
    mid_sum = int(row_counts[mid_start:mid_end].sum())
    # 中间 30% 区域的黑色像素 > 总数的 70%
    return mid_sum > total * 0.7


def detect_multiplication_x(pix, rect):
    """检测图像中是否为 "×"（乘号）。

    判定条件：
    - bbox 宽高比 0.7-1.3
    - 黑色像素在水平方向和垂直方向都有较长投影
      （最长连续黑色像素跨度 > 0.3*max(w,h)）
    - 交叉特征：从左上到右下（主对角线）和从左下到右上（副对角线）
      都有连续黑色像素（长度 > 0.2*max(w,h)）

    Args:
        pix: fitz.Pixmap
        rect: fitz.Rect

    Returns:
        bool
    """
    w = rect.x1 - rect.x0
    h = rect.y1 - rect.y0
    if h <= 0 or w <= 0:
        return False
    aspect_ratio = w / h
    if not (0.7 <= aspect_ratio <= 1.3):
        return False
    binary = _pixmap_to_binary(pix)
    h_pix, w_pix = binary.shape
    max_dim = max(h_pix, w_pix)

    # 水平方向投影：每行最长连续黑色像素
    h_proj = np.array([_longest_true_run(binary[r, :]) for r in range(h_pix)])
    # 垂直方向投影：每列最长连续黑色像素
    v_proj = np.array([_longest_true_run(binary[:, c]) for c in range(w_pix)])

    threshold = 0.3 * max_dim
    if h_proj.max() < threshold or v_proj.max() < threshold:
        return False

    # 交叉特征：主对角线（左上→右下）和副对角线（左下→右上）连续黑色像素
    diag_main = np.diagonal(binary)
    diag_anti = np.diagonal(np.fliplr(binary))
    main_run = _longest_true_run(diag_main)
    anti_run = _longest_true_run(diag_anti)
    diag_threshold = 0.2 * max_dim
    return main_run > diag_threshold and anti_run > diag_threshold


def detect_case_feature(pix, rect, row_fontsizes):
    """检测孤立大写字母 W/S/C/X 等是否应为小写。

    简化方法：基于 rect 高度与同行中文字符高度比较。
    - 若 rect_h < 同行中文高度 * 0.7（明显小于中文）则为小写候选 → 'lower'
    - 若 rect_h >= 同行中文高度 * 0.85 则为大写 → 'upper'
    - 否则 → 'unknown'

    Args:
        pix: fitz.Pixmap（保留参数以兼容调用方签名，本函数不直接使用）
        rect: fitz.Rect
        row_fontsizes: dict，compute_row_fontsizes 返回的 row_key -> fontsize_pt

    Returns:
        str: 'upper' / 'lower' / 'unknown'
    """
    h_pt = rect.y1 - rect.y0
    yc = (rect.y0 + rect.y1) / 2
    row_key = round(yc / 2.0) * 2.0
    if not row_fontsizes:
        return 'unknown'
    nearest_key = min(row_fontsizes.keys(), key=lambda k: abs(k - row_key))
    if abs(nearest_key - row_key) > 4.0:
        return 'unknown'
    row_cn_height = row_fontsizes[nearest_key]
    if h_pt < row_cn_height * 0.7:
        return 'lower'
    if h_pt >= row_cn_height * 0.85:
        return 'upper'
    return 'unknown'


# DEPRECATED: 原消歧辅助函数，classify_punctuation_by_features 已删除
def detect_dot_feature(pix):
    """检测图像中字符是实心点（`。`）还是圆环（`o`/`0`）。

    基于中心 30%×30% 区域黑色像素占比判定：
    - 占比 > 50%：实心点 `。`（句号在 bbox 中心是实心圆点）→ 返回 'solid'
    - 占比 < 20%：圆环 `o`/`0`（字母/数字在中心是空心圆环）→ 返回 'ring'
    - 中间值（20%-50%）：不确定 → 返回 'unknown'

    算法原理：
    - 中文句号 `。` 在 bbox 中心是一个实心圆点，中心区域几乎全黑
    - 字母 `o` 和数字 `0` 在 bbox 中心是空心圆环，中心区域几乎全白
    - 通过中心区域黑色像素占比可以区分两者

    Args:
        pix: fitz.Pixmap，单字渲染图像

    Returns:
        str: 'solid'（实心点 `。`）、'ring'（圆环 `o`/`0`）、'unknown'（不确定）
    """
    # 异常处理：图像尺寸过小（< 5×5）时无法可靠判定，返回 'unknown'
    if pix.width < 5 or pix.height < 5:
        return 'unknown'
    # 二值化（True = 黑色像素）
    binary = _pixmap_to_binary(pix)
    h, w = binary.shape
    if h < 5 or w < 5:
        return 'unknown'
    # 取中心 30%×30% 区域：[0.35*h:0.65*h, 0.35*w:0.65*w]
    y0 = int(h * 0.35)
    y1 = int(h * 0.65)
    x0 = int(w * 0.35)
    x1 = int(w * 0.65)
    # 边界保护：确保区域有效
    if y1 <= y0 or x1 <= x0:
        return 'unknown'
    center = binary[y0:y1, x0:x1]
    # 计算黑色像素占比
    total = center.size
    if total == 0:
        return 'unknown'
    black_count = int(center.sum())
    ratio = black_count / total
    # 判定逻辑
    if ratio > 0.5:
        return 'solid'
    if ratio < 0.2:
        return 'ring'
    return 'unknown'


# DEPRECATED: 由 classify_punctuation_by_features 替代
def detect_circular_char_feature(pix, rect, row_fontsizes):
    """检测圆形字符 (0/o/O/〇) 的几何特征。

    基于 cv2 轮廓分析提取几何特征，结合 rect 高度与同行中文字符高度比较，
    推断最可能的字符。

    几何判定依据（参考蓝太校对与字体规范）：
    - 0 (数字零): 瘦长椭圆，中等高度
    - o (小写字母): 椭圆，x-height（约为同行中文 0.7 倍以下）
    - O (大写字母): 椭圆，cap height（约为同行中文 0.85 倍以上）
    - 〇 (CJK 零): 标准正圆，内孔占比大且内孔为正圆

    Args:
        pix: fitz.Pixmap，单字渲染图像
        rect: fitz.Rect，字符 bbox
        row_fontsizes: dict，compute_row_fontsizes 返回的 row_key -> cn_height

    Returns:
        dict: {
            'shape': 'ellipse' | 'circle' | 'unknown',
            'aspect_ratio': float,           # 外接椭圆长短轴比
            'hole_area_ratio': float,        # 内孔面积 / bbox 面积
            'hole_aspect_ratio': float,      # 内孔椭圆长短轴比
            'relative_height': float,        # rect.h / row_cn_height
            'is_cap_height': bool,           # cap height (O)
            'is_x_height': bool,             # x-height (o)
            'is_cjk_round': bool,            # CJK 标准正圆 (〇)
            'suggested_char': str,           # 几何推断的字符（空字符串表示无定论）
        }
    """
    result = {
        'shape': 'unknown',
        'aspect_ratio': 0.0,
        'hole_area_ratio': 0.0,
        'hole_aspect_ratio': 0.0,
        'relative_height': 0.0,
        'is_cap_height': False,
        'is_x_height': False,
        'is_cjk_round': False,
        'suggested_char': '',
    }

    if pix.width < 5 or pix.height < 5:
        return result

    binary = _pixmap_to_binary(pix)
    h, w = binary.shape
    if h < 5 or w < 5:
        return result

    # 转 uint8 给 cv2（黑色像素=前景=255，白色背景=0）
    binary_u8 = (binary.astype(np.uint8)) * 255

    # 找轮廓（RETR_CCOMP 获取双层层级：外轮廓 + 内孔）
    contours, hierarchy = cv2.findContours(
        binary_u8, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return result

    # 找最大外轮廓（面积最大）
    outer_idx = max(range(len(contours)), key=lambda i: cv2.contourArea(contours[i]))
    outer_contour = contours[outer_idx]

    # 外接椭圆（需要 >= 5 个点）
    if len(outer_contour) >= 5:
        try:
            (cx, cy), (axis_w, axis_h), angle = cv2.fitEllipse(outer_contour)
            major = max(axis_w, axis_h)
            minor = min(axis_w, axis_h)
            outer_aspect = major / max(minor, 1e-6)
            result['aspect_ratio'] = float(outer_aspect)
            if outer_aspect < 1.1:
                result['shape'] = 'circle'
            else:
                result['shape'] = 'ellipse'
        except Exception:
            pass

    # 找内孔（hierarchy 中 parent != -1 的轮廓）
    # hierarchy 结构: [next, prev, first_child, parent]
    hole_areas = []
    hole_aspects = []
    if hierarchy is not None:
        hierarchy_arr = hierarchy[0]  # shape (N, 4)
        for i, h_row in enumerate(hierarchy_arr):
            if i == outer_idx:
                continue
            if h_row[3] != -1:  # has parent → 是内孔
                area = cv2.contourArea(contours[i])
                if area > 2.0:  # 过滤噪点
                    hole_areas.append(area)
                    if len(contours[i]) >= 5:
                        try:
                            (_, _), (haw, hah), _ = cv2.fitEllipse(contours[i])
                            h_major = max(haw, hah)
                            h_minor = min(haw, hah)
                            hole_aspects.append(h_major / max(h_minor, 1e-6))
                        except Exception:
                            hole_aspects.append(0.0)

    bbox_area = float(h * w)
    if hole_areas:
        max_hole_area = max(hole_areas)
        result['hole_area_ratio'] = float(max_hole_area / max(bbox_area, 1.0))
        if hole_aspects:
            max_hole_idx = hole_areas.index(max_hole_area)
            if max_hole_idx < len(hole_aspects):
                result['hole_aspect_ratio'] = float(hole_aspects[max_hole_idx])

    # 相对高度
    h_pt = rect.y1 - rect.y0
    yc = (rect.y0 + rect.y1) / 2
    row_key = round(yc / 2.0) * 2.0
    row_cn_height = None
    if row_fontsizes:
        nearest_key = min(row_fontsizes.keys(), key=lambda k: abs(k - row_key))
        if abs(nearest_key - row_key) <= 4.0:
            row_cn_height = row_fontsizes[nearest_key]

    if row_cn_height and row_cn_height > 0:
        result['relative_height'] = float(h_pt / row_cn_height)
        rh = result['relative_height']
        if rh >= 0.85:
            result['is_cap_height'] = True
        elif rh <= 0.7:
            result['is_x_height'] = True

    # CJK 圆形判定：标准正圆 + 内孔为正圆 + 内孔占比大
    if (result['shape'] == 'circle'
            and 0.0 < result['hole_aspect_ratio'] < 1.05
            and result['hole_area_ratio'] >= 0.45):
        result['is_cjk_round'] = True

    # 推断字符
    if result['is_cjk_round']:
        result['suggested_char'] = '〇'
    elif result['shape'] == 'ellipse' and result['is_cap_height']:
        result['suggested_char'] = 'O'
    elif result['shape'] == 'ellipse' and result['is_x_height']:
        result['suggested_char'] = 'o'
    elif result['shape'] == 'ellipse':
        # 中等高度，可能是 0
        result['suggested_char'] = '0'
    # 兜底：suggested_char 为空字符串，表示无几何推断

    return result


def _get_relative_height(rect, row_fontsizes):
    """计算 rect 高度相对同行中文字符高度的比值。

    通过 rect 中心 y 坐标定位最近的行（row_key），取该行的中文字符高度
    作为基准，返回 rect 高度与基准的比值。无法定位到有效行时返回 0.0。

    Args:
        rect: fitz.Rect，字符 bbox
        row_fontsizes: dict，compute_row_fontsizes 返回的 row_key -> cn_height

    Returns:
        float: rect.h / row_cn_height。无有效行时返回 0.0
    """
    if not row_fontsizes:
        return 0.0
    h_pt = rect.y1 - rect.y0
    yc = (rect.y0 + rect.y1) / 2
    row_key = round(yc / 2.0) * 2.0
    nearest_key = min(row_fontsizes.keys(), key=lambda k: abs(k - row_key))
    if abs(nearest_key - row_key) > 4.0:
        return 0.0
    row_cn_height = row_fontsizes[nearest_key]
    if row_cn_height <= 0:
        return 0.0
    return h_pt / row_cn_height


def get_circular_context(page_results, r_idx, y_tol=2.0):
    """获取圆形字符的上下文信息（用于 0/o/O/〇 消歧）。

    基于同行邻接字符的类型（数字/拉丁字母/CJK 汉字）和国标 GB/T 15835-2011
    场景模式（年份、编号、小数、ISBN）推断最可能的字符。

    国标规则：
    - 年份/编号/房号 → 〇（中文数字场景）
    - 金额大写 → 零（不在此函数处理，由上层规则处理）
    - 计量/科技/ISBN → 0（阿拉伯数字场景）

    Args:
        page_results: list[dict]，同一页所有字符记录
        r_idx: int，当前字符在 page_results 中的索引
        y_tol: float，同行 y 中心容差（pt）

    Returns:
        dict: 含 left_chars/right_chars/各类上下文标志/suggested_char 字段。
              suggested_char 为 '0'/'o'/'O'/'〇'/'o_or_O'/None。
              None 表示无强上下文，应依赖几何特征。
    """
    result = {
        'left_chars': '',
        'right_chars': '',
        'left_is_digit': False,
        'right_is_digit': False,
        'left_is_latin': False,
        'right_is_latin': False,
        'left_is_cjk': False,
        'right_is_cjk': False,
        'in_year_pattern': False,
        'in_num_pattern': False,
        'in_decimal': False,
        'in_isbn': False,
        'suggested_char': None,
    }

    if r_idx < 0 or r_idx >= len(page_results):
        return result

    r = page_results[r_idx]
    rect = r['rect']
    yc = (rect.y0 + rect.y1) / 2

    # 找同行字符（按 x 排序）
    same_line = []
    for rr in page_results:
        if not rr.get('text'):
            continue
        rr_yc = (rr['rect'].y0 + rr['rect'].y1) / 2
        if abs(rr_yc - yc) <= y_tol:
            same_line.append(rr)
    same_line.sort(key=lambda x: x['rect'].x0)

    # 找当前字符在排序后的位置（用对象 id 判断）
    current_pos = -1
    for i, rr in enumerate(same_line):
        if rr is r:
            current_pos = i
            break
    if current_pos < 0:
        return result

    # 取前 3 个和后 3 个字符的 text 首字符
    left_recs = same_line[max(0, current_pos - 3):current_pos]
    right_recs = same_line[current_pos + 1:current_pos + 4]
    left_chars = ''.join(rr['text'][0] if rr['text'] else '' for rr in left_recs)
    right_chars = ''.join(rr['text'][0] if rr['text'] else '' for rr in right_recs)
    result['left_chars'] = left_chars
    result['right_chars'] = right_chars

    # 邻接字符类型判定（取最近的非空字符）
    if left_chars:
        last_left = left_chars[-1]
        if '0' <= last_left <= '9':
            result['left_is_digit'] = True
        elif ('a' <= last_left <= 'z') or ('A' <= last_left <= 'Z'):
            result['left_is_latin'] = True
        elif '\u4e00' <= last_left <= '\u9fff' or last_left == '〇':
            result['left_is_cjk'] = True
    if right_chars:
        first_right = right_chars[0]
        if '0' <= first_right <= '9':
            result['right_is_digit'] = True
        elif ('a' <= first_right <= 'z') or ('A' <= first_right <= 'Z'):
            result['right_is_latin'] = True
        elif '\u4e00' <= first_right <= '\u9fff' or first_right == '〇':
            result['right_is_cjk'] = True

    # 模式匹配（用 ? 占位当前字符位置）
    placeholder = '?'
    full_context = left_chars + placeholder + right_chars

    # 年份模式："二?二?年" 或 "二?年"
    if re.search(r'二[0〇0oO\?]?二[0〇0oO\?]?年', full_context) or \
       re.search(r'二[0〇0oO\?]年', full_context):
        result['in_year_pattern'] = True

    # 编号模式："第?号"
    if re.search(r'第[0〇0oO\?]?号', full_context):
        result['in_num_pattern'] = True

    # 小数模式："\d.? 或 ?.\d"
    if re.search(r'\d[._][0〇oO\?]$', left_chars + placeholder) or \
       re.search(r'^[0〇oO\?][._]\d', placeholder + right_chars):
        result['in_decimal'] = True

    # ISBN 模式：左侧 8 字符内出现 ISBN
    extended_left = ''.join(
        rr['text'][0] if rr.get('text') else ''
        for rr in same_line[:current_pos]
    )
    if re.search(r'ISBN', extended_left[-8:], re.IGNORECASE):
        result['in_isbn'] = True

    # 推断字符（按优先级）
    if result['in_year_pattern'] or result['in_num_pattern']:
        result['suggested_char'] = '〇'
    elif result['in_isbn'] or result['in_decimal']:
        result['suggested_char'] = '0'
    elif result['left_is_digit'] and result['right_is_digit']:
        result['suggested_char'] = '0'
    elif result['left_is_latin'] or result['right_is_latin']:
        # 拉丁上下文，可能是 o 或 O（依赖几何 + 大小写判定）
        result['suggested_char'] = 'o_or_O'
    elif result['left_is_cjk'] and result['right_is_cjk']:
        result['suggested_char'] = '〇'
    elif result['left_is_cjk'] or result['right_is_cjk']:
        # 单侧 CJK，倾向 〇
        result['suggested_char'] = '〇'

    return result


# ==================== 1. PDF 字符 drawing 提取与过滤 ====================
def extract_char_drawings(page):
    """提取页面上的字符级矢量字形 drawing（负向排除策略）。

    仅排除明显非字符 drawing（装饰线、背景矩形、噪点），
    其余全部作为字符候选交由 OCR 判定。

    Args:
        page: fitz.Page 对象

    Returns:
        list[dict]: 字符候选 drawing 列表
    """
    page_rect = page.rect
    page_w = page_rect.width
    page_h = page_rect.height
    draws = page.get_drawings()
    char_draws = []
    for d in draws:
        rect = d.get('rect')
        items = d.get('items', [])
        if not rect or len(items) < 1:
            continue
        w = rect.x1 - rect.x0
        h = rect.y1 - rect.y0
        if w <= 0 or h <= 0:
            continue
        # 排除超长装饰线（水平/垂直）
        if w > page_w * 0.5 and h < 2.0:
            continue
        if h > page_h * 0.5 and w < 2.0:
            continue
        # 排除超大背景矩形
        if w > 100 and h > 100:
            continue
        # 排除极小噪点
        if w < 0.5 and h < 0.5:
            continue
        char_draws.append(d)
    return char_draws


# ==================== 2. RapidOCR PP-OCRv6 引擎创建 ====================
def create_ocr_engine():
    """创建 RapidOCR PP-OCRv6 引擎（含 GPU 加速配置）。

    GPU 真正可用时使用 MEDIUM 模型，否则回退到 SMALL 模型。
    配置 cudnn_conv_algo_search=HEURISTIC 避免 sm_86 EXHAUSTIVE 模式错误。
    """
    # 集中式 CUDA DLL 路径设置（预加载 nvidia pip 包 + torch/lib + CUDA_PATH/bin）
    from cuda_dll_setup import setup_cuda_dll_paths
    setup_cuda_dll_paths()

    ort.set_default_logger_severity(3)

    # 引擎选择：HX_OCR_ENGINE=trt 使用 TensorRT，默认 ort 使用 ONNXRUNTIME CUDA
    engine_choice = os.environ.get('HX_OCR_ENGINE', 'ort').strip().lower()
    use_trt = engine_choice == 'trt'

    has_cuda = 'CUDAExecutionProvider' in ort.get_available_providers()
    if has_cuda and sys.platform == 'win32':
        try:
            import ctypes
            ctypes.WinDLL('cublasLt64_12.dll')
        except OSError:
            has_cuda = False

    model_type = ModelType.MEDIUM if has_cuda else ModelType.SMALL

    if has_cuda:
        print(f"GPU 加速已启用 ({'MEDIUM' if has_cuda else 'SMALL'} 模型)")

    # TRT 可用性检测：导入失败则 fallback 到 ORT CUDA
    trt_available = False
    if use_trt:
        try:
            import tensorrt as _trt  # noqa: F401
            trt_available = True
        except (ImportError, OSError) as e:
            print(f"[OCR] TensorRT unavailable, fallback to ONNXRUNTIME CUDA: {e}")
            use_trt = False

    params = {
        "EngineConfig.onnxruntime.use_cuda": has_cuda,
        # cuDNN 9.10.02 在 sm_86 (RTX 30 系列) 上：
        # - EXHAUSTIVE 触发 HEURISTIC_QUERY_FAILED
        # - DEFAULT 触发 Fallback mode 警告且性能差
        # - HEURISTIC 轻量启发式搜索，避免上述两个问题
        "EngineConfig.onnxruntime.cuda_ep_cfg.cudnn_conv_algo_search": "HEURISTIC",
        # 多 worker 并行下，每 worker 独占 1 个 CPU 线程，避免
        # intra/inter op 线程数随 worker 数指数放大导致 CPU 争用
        # （10 worker × 默认 -1 = 全部 CPU 线程被每个 session 抢占）
        "EngineConfig.onnxruntime.intra_op_num_threads": 1,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "Det.engine_type": EngineType.ONNXRUNTIME,
        "Det.lang_type": LangDet.CH,
        "Det.model_type": model_type,
        "Det.ocr_version": OCRVersion.PPOCRV6,
        # DBNet 检测参数调优（对齐 software1/ocr_engine/rapidocr_engine.py）
        "Det.box_thresh": 0.3,
        "Det.unclip_ratio": 1.5,
        "Det.max_candidates": 3000,
        "Det.use_dilation": True,
        "Det.limit_side_len": 2880,
        "Det.limit_type": "max",
        "Rec.engine_type": EngineType.ONNXRUNTIME,
        "Rec.lang_type": LangRec.CH,
        "Rec.model_type": model_type,
        "Rec.ocr_version": OCRVersion.PPOCRV6,
    }
    # TensorRT 引擎覆盖配置：仅在 TRT 模式且 tensorrt 可用时生效。
    # 下方 ORT 专用配置（cudnn_conv_algo_search、intra_op_num_threads 等）
    # 在 TRT 模式下被 RapidOCR 忽略，但保留在 params 中不影响 ORT fallback。
    if use_trt and trt_available:
        params.update({
            # Det/Rec/Cls 三阶段统一切到 TensorRT
            "Det.engine_type": EngineType.TENSORRT,
            "Rec.engine_type": EngineType.TENSORRT,
            "Cls.engine_type": EngineType.TENSORRT,
            # TRT 全局配置：FP16 推理 + 2GB workspace
            "EngineConfig.tensorrt.use_fp16": True,
            "EngineConfig.tensorrt.workspace_size": 2147483648,  # 2GB
            # engine 缓存目录：跨进程复用，按 {model}_{sm89}_{fp16}.engine 命名
            "EngineConfig.tensorrt.cache_dir": os.path.expanduser("~/.rapidocr_trt_cache"),
            # 检测动态形状 profile：max 对齐 limit_side_len=2880，
            # opt 取 1440（A4 @150dpi 量级）覆盖常见版面
            "EngineConfig.tensorrt.det_profile.min_shape": [1, 3, 32, 32],
            "EngineConfig.tensorrt.det_profile.opt_shape": [1, 3, 1440, 1440],
            "EngineConfig.tensorrt.det_profile.max_shape": [1, 3, 2880, 2880],
            # rec_profile / cls_profile 保留 RapidOCR 默认值
        })
    engine = RapidOCR(params=params)
    # 暴露 _has_cuda 属性供 UI 显示 GPU 状态
    engine._has_cuda = has_cuda
    engine._model_type_name = "MEDIUM" if has_cuda else "SMALL"
    # _engine_type_name 供 UI 显示当前推理后端（TRT / ORT）
    engine._engine_type_name = "TRT" if (use_trt and trt_available) else "ORT"
    return engine


# ==================== 3. 单字隔离重绘（用于元素图片与回退识别） ====================
def render_char_isolated(page, drawing, pad=2):
    """隔离重绘单个字符 drawing，渲染为纯净 pixmap（仅含该字符）。

    新建临时小页面，用 Shape API 按 drawing['items'] 原样重绘路径，
    物理隔离页面上的其他字符与装饰，避免 page.get_pixmap(clip=...) 把
    邻近字符裁进来导致 OCR 误识。

    强制使用 even-odd 填充规则（even_odd=True）：Shape API 重绘时会丢失
    原 PDF 的轮廓方向信息，nonzero 规则下全包围结构（如"国"字）的外框
    与内部子轮廓方向被同向化，winding number 不再抵消，导致内部被整体
    填实成全黑方块。even-odd 规则不依赖轮廓方向，对"外框+内部子路径"
    结构能正确挖空。

    Args:
        page: fitz.Page 对象（保留参数以兼容调用方签名，本函数不直接使用）
        drawing: dict，page.get_drawings() 返回的单个 drawing 结构
            必含字段：items（路径操作列表）、rect（bbox）、fill、fill_opacity
        pad: int/float，临时页面四周保留的边距（pt），避免字形贴边裁切

    Returns:
        (pix, rect): 渲染得到的 fitz.Pixmap、原 drawing 的 fitz.Rect
    """
    rect = drawing['rect']
    # 新建临时小页面，尺寸为 rect + 2*pad 边距
    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(
        width=rect.width + 2 * pad,
        height=rect.height + 2 * pad,
    )
    # 平移向量：将原 rect 左上角移到临时页面 (pad, pad) 位置
    shift = fitz.Point(-rect.x0 + pad, -rect.y0 + pad)

    shape = temp_page.new_shape()
    for item in drawing.get('items', []):
        op = item[0]
        if op == 'l':
            # line: (p1, p2)
            shape.draw_line(item[1] + shift, item[2] + shift)
        elif op == 'c':
            # cubic Bezier: (p1, p2, p3, p4)，起点已显式包含
            shape.draw_bezier(
                item[1] + shift,
                item[2] + shift,
                item[3] + shift,
                item[4] + shift,
            )
        elif op == 're':
            # rectangle: (Rect, fill_flag)，fitz.Rect 无 + Point 运算，手动构造
            r = item[1]
            new_rect = fitz.Rect(
                r.x0 + shift.x, r.y0 + shift.y,
                r.x1 + shift.x, r.y1 + shift.y,
            )
            shape.draw_rect(new_rect)
        else:
            print(f"  [WARN] 未知 drawing op: {op}，跳过")

    shape.finish(
        fill=drawing.get('fill'),
        color=drawing.get('color'),
        fill_opacity=drawing.get('fill_opacity') or 1.0,
        stroke_opacity=drawing.get('stroke_opacity') or 1.0,
        width=drawing.get('width') or 1.0,
        closePath=drawing.get('closePath') or False,
        even_odd=True,
    )
    shape.commit()

    pix = temp_page.get_pixmap(dpi=OCR_DPI)
    temp_doc.close()
    return pix, rect


def recognize_single_char(engine, page, drawing, single_char: bool = True):
    """隔离重绘单字 drawing 并用 OCR 识别。

    调用 render_char_isolated 将该 drawing 单独重绘到临时页面，
    物理隔离其他字符后渲染为图像，再跳过检测和方向分类直接走识别分支
    （输入已是单字小图）。

    CTC 解码器对单字图片可能输出多字符序列（如 "373"、"01"），导致同一
    位置嵌入多字、视觉上呈现"数字重复嵌两遍"。当 single_char=True 且识别
    到非空文本时，仅取首字符作为返回值，避免多字符叠加。

    Args:
        engine: RapidOCR 引擎实例
        page: fitz.Page 对象
        drawing: dict，单个字符 drawing 结构（含 items、rect、fill 等字段）
        single_char: 是否强制只取识别结果的首字符（默认 True），用于规避
            CTC 解码器对单字图片输出多字符序列的问题

    Returns:
        (text, score, pix): 识别字符文本、置信度、渲染用的 fitz.Pixmap
        （pix 一并返回以供 save_element_image 复用，避免重复渲染）
    """
    # 隔离重绘单个 drawing，确保图像 100% 只含该字符
    pix, rect = render_char_isolated(page, drawing)
    # pixmap → numpy ndarray (H, W, 3) RGB
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    # 如果有 alpha 通道去掉
    if img.shape[2] == 4:
        img = img[:, :, :3]

    # 单字识别（不做检测、不做方向分类）
    result = engine(img, use_det=False, use_cls=False, use_rec=True)
    text = result.txts[0] if result.txts else ""
    score = float(result.scores[0]) if result.scores else 0.0

    # CTC 解码器可能输出多字符序列，single_char=True 时仅取首字符
    if single_char and text:
        text = text[0]

    return text, score, pix


def save_element_image(pix, out_dir, idx, rect):
    """将单个 drawing 的渲染 pixmap 保存为 PNG 图片。

    图片渲染参数与 OCR 识别所用参数一致（DPI=300，clip 扩大 2pt 边距），
    确保保存的图片即为 OCR 输入图像，便于人工核对识别结果。

    Args:
        pix: fitz.Pixmap 对象（来自 recognize_single_char 的返回值）
        out_dir: 输出目录路径
        idx: drawing 索引（用于文件名）
        rect: fitz.Rect，字符 drawing 的 bbox（用于文件名记录尺寸）

    Returns:
        str: 保存的图片文件名（不含路径）
    """
    w = rect.x1 - rect.x0
    h = rect.y1 - rect.y0
    img_name = f'draw_{idx:03d}_x{rect.x0:.0f}_w{w:.1f}_h{h:.1f}.png'
    img_path = os.path.join(out_dir, img_name)
    pix.save(img_path)
    return img_name


# ==================== 4. 字体加载（中文 SimSun / ASCII Times New Roman） ====================
def get_font_for_char(text):
    """根据字符内容加载字体。

    中文 → SimSun (simsun.ttc，回退 china-ss)
    ASCII 字母数字 → Times New Roman (times.ttf，回退 Times-Roman)
    ASCII 标点 → 保持中文字体 SimSun

    Args:
        text: 字符文本

    Returns:
        fitz.Font 实例
    """
    if text and len(text) == 1:
        c = text[0]
        if ('0' <= c <= '9') or ('a' <= c <= 'z') or ('A' <= c <= 'Z'):
            return _get_latin_font()
    return _get_cn_font()


def _get_cn_font():
    """获取中文字体 SimSun，带缓存。"""
    if 'cn' in _FONT_CACHE:
        return _FONT_CACHE['cn']
    windir = os.environ.get('WINDIR', 'C:\\Windows')
    font = None
    for name in ['simsun.ttc', 'STSONG.TTF']:
        path = os.path.join(windir, 'Fonts', name)
        if os.path.exists(path):
            try:
                font = fitz.Font(fontfile=path)
                break
            except Exception:
                continue
    if font is None:
        try:
            font = fitz.Font('china-ss')
        except Exception:
            font = fitz.Font('china-s')
    _FONT_CACHE['cn'] = font
    return font


def _get_latin_font():
    """获取 Latin 字体 Times New Roman，带缓存。"""
    if 'latin' in _FONT_CACHE:
        return _FONT_CACHE['latin']
    windir = os.environ.get('WINDIR', 'C:\\Windows')
    path = os.path.join(windir, 'Fonts', 'times.ttf')
    font = None
    if os.path.exists(path):
        try:
            font = fitz.Font(fontfile=path)
        except Exception:
            font = None
    if font is None:
        try:
            font = fitz.Font('Times-Roman')
        except Exception:
            font = fitz.Font('helv')
    _FONT_CACHE['latin'] = font
    return font


# ==================== 5. 行字号计算（用于 ASCII 字母数字字号） ====================
def compute_row_fontsizes(page_results, y_tol=2.0, score_min=0.5):
    """按 y 中心分组计算每行字号（取同行高置信度中文字符 rect 高度的中位数）。

    用于 ASCII 字母数字字号取值：同行中文字符的 rect 高度 ≈ 真实字号
    （SimSun bbox=1em），而数字 rect 高度仅 ≈ 0.743 × 字号，直接用 rect
    高度作字号会导致数字嵌回偏小 34%。

    Args:
        page_results: list[dict]，每项含 rect、text、score 字段
        y_tol: float，y 中心分组容差（pt）
        score_min: float，仅收集置信度 ≥ 此值的中文字符

    Returns:
        dict: row_key -> fontsize_pt（中文字符 rect 高度的中位数）
    """
    row_heights = {}
    for r in page_results:
        text = r.get('text', '')
        score = r.get('score', 0.0)
        if score < score_min or not text:
            continue
        c = text[0]
        # 仅中文字符（CJK 统一表意文字）
        if not ('\u4e00' <= c <= '\u9fff'):
            continue
        rect = r['rect']
        yc = (rect.y0 + rect.y1) / 2
        row_key = round(yc / y_tol) * y_tol
        h = rect.y1 - rect.y0
        row_heights.setdefault(row_key, []).append(h)
    # 每行取中位数作为字号
    return {rk: sorted(hs)[len(hs) // 2] for rk, hs in row_heights.items() if hs}


def get_row_fontsize(rect, row_fontsizes, y_tol=2.0, fallback_coeff=1.0 / 0.743):
    """取字符所在行的字号；无中文参照时用 rect 高度 × fallback_coeff 补偿。

    Args:
        rect: fitz.Rect，字符 bbox
        row_fontsizes: dict，compute_row_fontsizes 返回的 row_key -> fontsize_pt
        y_tol: float，y 中心分组容差（pt）
        fallback_coeff: float，纯 ASCII 行（无中文参照）的字号补偿系数
            默认 1/0.743 ≈ 1.346，对应 Times New Roman 数字墨迹占比 0.684
            和路径包围盒留白合成后的 0.743 系数

    Returns:
        float: 字号（pt）
    """
    yc = (rect.y0 + rect.y1) / 2
    row_key = round(yc / y_tol) * y_tol
    if not row_fontsizes:
        # 全页无中文参照，纯 ASCII 行兜底
        return max((rect.y1 - rect.y0) * fallback_coeff, 1.0)
    # 在 row_fontsizes.keys() 中找最近的 row_key
    nearest_key = min(row_fontsizes.keys(), key=lambda k: abs(k - row_key))
    if abs(nearest_key - row_key) <= y_tol * 2:
        return row_fontsizes[nearest_key]
    # 同行无中文参照，用系数补偿
    return max((rect.y1 - rect.y0) * fallback_coeff, 1.0)


# 标点字号视觉补偿系数表（key = 字符，value = 补偿系数）
# 小尺寸标点 `、。·.`：SimSun 中实际墨迹只占字号的 25-40%，需 2.5-3.0 倍补偿
_PUNCT_COMPENSATION_SMALL = {'、': 2.8, '。': 2.8, '·': 2.8, '.': 2.8}
# 长形标点 `…-—`：横向延展，需 1.3-2.0 倍补偿
_PUNCT_COMPENSATION_LONG = {'…': 1.6, '-': 1.6, '—': 1.6}
# 全角标点 `：；`：墨迹占比约 0.55，需 1.8 倍补偿
_PUNCT_COMPENSATION_FULLWIDTH = {'：': 1.8, '；': 1.8}


def get_punct_compensated_fontsize(c, rect, row_fontsizes, y_tol=2.0):
    """根据标点类型返回带视觉补偿系数的字号。

    标点在 SimSun/Times New Roman 中实际墨迹只占字号的 25-55%，
    若直接使用 rect 高度作字号会导致嵌字标点视觉上远小于原图。
    本函数根据标点类型查表返回补偿字号：
    - 小尺寸标点 `、。·.`：补偿 2.8 倍（rect_h * 2.8）
    - 长形标点 `…-—`：补偿 1.6 倍
    - 全角标点 `：；`：补偿 1.8 倍
    - 罗马数字 Ⅰ-Ⅻ（U+2160-U+2182）：不补偿，使用 get_row_fontsize
    - 其他标点：默认不补偿，使用 get_row_fontsize

    返回 max(rect_h * coefficient, row_fontsize)，确保补偿后字号
    不会小于同行中文字号（避免过度补偿导致标点大于同行中文）。

    Args:
        c: 单个字符
        rect: fitz.Rect，字符 bbox
        row_fontsizes: dict，compute_row_fontsizes 返回的 row_key -> fontsize_pt
        y_tol: float，y 中心分组容差（pt）

    Returns:
        float: 字号（pt）
    """
    if not c or len(c) != 1:
        return get_row_fontsize(rect, row_fontsizes, y_tol)

    cp = ord(c)
    # 罗马数字 Ⅰ-Ⅻ U+2160-U+2182 不补偿
    if 0x2160 <= cp <= 0x2182:
        return get_row_fontsize(rect, row_fontsizes, y_tol)

    rect_h = rect.y1 - rect.y0
    row_fs = get_row_fontsize(rect, row_fontsizes, y_tol)

    # 查表取补偿系数
    coefficient = None
    if c in _PUNCT_COMPENSATION_SMALL:
        coefficient = _PUNCT_COMPENSATION_SMALL[c]
    elif c in _PUNCT_COMPENSATION_LONG:
        coefficient = _PUNCT_COMPENSATION_LONG[c]
    elif c in _PUNCT_COMPENSATION_FULLWIDTH:
        coefficient = _PUNCT_COMPENSATION_FULLWIDTH[c]

    if coefficient is None:
        # 其他标点默认不补偿
        return row_fs

    return max(rect_h * coefficient, row_fs)


# ==================== 6. 行分组（Task 2） ====================
def group_drawings_by_line(char_draws, y_tol=2.0):
    """按 y 中心聚类 char_draws 成行，容差 y_tol pt。

    Args:
        char_draws: list[dict]，extract_char_drawings 返回的 drawing 列表
        y_tol: float，y 中心分组容差（pt）

    Returns:
        list[list[dict]]：每个元素为一行 drawing 列表，行内按 rect.x0 升序，
        行列表按 row_key 升序（自上而下）
    """
    groups = {}
    for d in char_draws:
        rect = d['rect']
        yc = (rect.y0 + rect.y1) / 2
        row_key = round(yc / y_tol) * y_tol
        groups.setdefault(row_key, []).append(d)
    # 行内按 x0 升序
    for k in groups:
        groups[k].sort(key=lambda d: d['rect'].x0)
    # 行列表按 row_key 升序（自上而下）
    return [groups[k] for k in sorted(groups.keys())]


# ==================== 7. 整行渲染隔离（Task 3） ====================
def render_line_image(page, line_draws, pad=4):
    """渲染整行 drawing 列表为 pixmap（隔离其他行）。

    新建临时大页面，按原 x 坐标依次重绘所有 drawing items，强制 even_odd=True
    继承自前序 spec 的填充规则修复。用于整行 OCR 输入。

    Args:
        page: fitz.Page 对象（保留参数以兼容调用方签名）
        line_draws: list[dict]，同一行的 drawing 列表
        pad: int/float，临时页面四周保留的边距（pt）

    Returns:
        (pix, line_rect): 整行 pixmap、行内所有 drawing rect 的并集
    """
    # 计算行内所有 drawing rect 的并集
    x0 = min(d['rect'].x0 for d in line_draws)
    y0 = min(d['rect'].y0 for d in line_draws)
    x1 = max(d['rect'].x1 for d in line_draws)
    y1 = max(d['rect'].y1 for d in line_draws)
    line_rect = fitz.Rect(x0, y0, x1, y1)

    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(
        width=line_rect.width + 2 * pad,
        height=line_rect.height + 2 * pad,
    )
    shift = fitz.Point(-line_rect.x0 + pad, -line_rect.y0 + pad)

    shape = temp_page.new_shape()
    for drawing in line_draws:
        for item in drawing.get('items', []):
            op = item[0]
            if op == 'l':
                shape.draw_line(item[1] + shift, item[2] + shift)
            elif op == 'c':
                shape.draw_bezier(
                    item[1] + shift, item[2] + shift,
                    item[3] + shift, item[4] + shift,
                )
            elif op == 're':
                r = item[1]
                new_rect = fitz.Rect(
                    r.x0 + shift.x, r.y0 + shift.y,
                    r.x1 + shift.x, r.y1 + shift.y,
                )
                shape.draw_rect(new_rect)
            else:
                print(f"  [WARN] 未知 drawing op: {op}，跳过")
        # 每个 drawing 单独 finish（保留各自的 fill/color 等属性）
        shape.finish(
            fill=drawing.get('fill'),
            color=drawing.get('color'),
            fill_opacity=drawing.get('fill_opacity') or 1.0,
            stroke_opacity=drawing.get('stroke_opacity') or 1.0,
            width=drawing.get('width') or 1.0,
            closePath=drawing.get('closePath') or False,
            even_odd=True,  # 强制 even-odd，继承前序 spec 修复
        )
    shape.commit()

    pix = temp_page.get_pixmap(dpi=OCR_DPI)
    temp_doc.close()
    return pix, line_rect


# ==================== 8. 整行 OCR 识别（Task 4） ====================
def recognize_line(engine, page, line_draws, single_char_fallback=True):
    """整行 OCR 识别，长度不匹配时回退到单字识别。

    渲染整行图像后调用 PP-OCRv6 Rec 模型识别，利用上下文提升特殊符号
    （句号、斜杠等）识别率。OCR 输出字符数与行内 drawing 数量一致时
    按序一一对应；不一致时回退到逐字 recognize_single_char。

    Args:
        engine: RapidOCR 引擎实例
        page: fitz.Page 对象
        line_draws: list[dict]，同一行的 drawing 列表（已按 x0 升序）
        single_char_fallback: 长度不匹配时是否回退到单字识别

    Returns:
        list[tuple[str, float, fitz.Pixmap]]：每字 (text, score, pix)，
        pix 为该字的单字渲染图（用 render_char_isolated 生成，用于保存元素图片）
    """
    pix_line, _ = render_line_image(page, line_draws)
    img = np.frombuffer(pix_line.samples, dtype=np.uint8).reshape(
        pix_line.height, pix_line.width, pix_line.n
    )
    if img.shape[2] == 4:
        img = img[:, :, :3]

    result = engine(img, use_det=False, use_cls=False, use_rec=True)
    ocr_text = result.txts[0] if result.txts else ""
    ocr_score = float(result.scores[0]) if result.scores else 0.0

    if len(ocr_text) == len(line_draws):
        # 长度一致：按序一一对应
        results = []
        for i, d in enumerate(line_draws):
            char_text = ocr_text[i]
            # 单字渲染 pix 用于保存元素图片
            char_pix, _ = render_char_isolated(page, d)
            results.append((char_text, ocr_score, char_pix))
        return results
    else:
        # 长度不一致
        if single_char_fallback:
            print(f"  [WARN] 整行 OCR 长度不匹配: OCR={len(ocr_text)}字, "
                  f"drawing={len(line_draws)}个, OCR文本={ocr_text!r}, 回退单字识别")
            results = []
            for d in line_draws:
                text, score, pix = recognize_single_char(engine, page, d)
                results.append((text, score, pix))
            return results
        else:
            raise ValueError(
                f"整行 OCR 长度不匹配: OCR={len(ocr_text)}, drawing={len(line_draws)}"
            )


# ==================== 9. 重合率嵌字算法（Task 5） ====================
def write_red_char_overlap(page, rect, char_text, font_size_pt):
    """用软件二重合率算法写入红色字符（水平居中+垂直居中）。

    移植自 software2/pdf_processor/pdf_output.py 第 132-174 行。
    通过水平居中（pos_x = rect.x0 + (bbox_w - char_w)/2）和垂直居中
    （pos_y = rect.y0 + bbox_h/2 + (ascender+descender)/2*fs）让红字
    视觉中心与原字符 bbox 中心最大化重合。

    每字独立 TextWriter，支持在 Adobe Acrobat 中逐字选中。

    Args:
        page: fitz.Page 对象
        rect: fitz.Rect，原字符 drawing 的 bbox
        char_text: 要写入的字符文本
        font_size_pt: 字号（pt）
    """
    font = get_font_for_char(char_text)
    # 计算字符宽度（pt）
    try:
        char_w_pt = font.text_length(char_text, font_size_pt)
    except Exception:
        char_w_pt = 0.0
    bbox_w_pt = rect.x1 - rect.x0
    bbox_h_pt = rect.y1 - rect.y0
    # 水平居中
    pos_x = rect.x0 + (bbox_w_pt - char_w_pt) / 2
    # 垂直居中：基线 = bbox中心 + (ascender+descender)/2 * fs
    pos_y = rect.y0 + bbox_h_pt / 2 + (font.ascender + font.descender) / 2 * font_size_pt

    tw = fitz.TextWriter(page.rect)
    try:
        tw.append((pos_x, pos_y), char_text, font=font, fontsize=font_size_pt)
        tw.write_text(page, render_mode=0, color=(1, 0, 0))
    except Exception as e:
        print(f"  [WARN] 写入失败: char={char_text!r}, rect={rect}, err={e}")


def _write_punct_with_overlap_legacy(page, rect, char_text, font_size_pt, drawing):
    """标点覆盖率嵌字算法（原实现，作为 C++ 加速版的回落）。

    标点的视觉中心与 bbox 几何中心不一致：
    - `。` 实际在 bbox 下半（顶部留白）
    - `、` 在 bbox 左下
    - `…` 在中部偏下
    - `-` 在中部
    单纯几何居中会导致标点红字与原矢量字形重合率偏低。
    本函数先用预设偏移表写入并计算 IoU；若 IoU < 0.5，再在 ±1pt 范围内
    以 1pt 步长网格搜索 9 个候选偏移，选择 IoU 最大的位置作为最终嵌字位置。

    算法流程：
    1. 预设偏移表（基于标点类型）：
       - `。` → y_offset = +0.3 × font_size_pt（向下偏移，因句号在 bbox 下半）
       - `、` → x_offset = -0.2 × font_size_pt, y_offset = +0.3 × font_size_pt（左下偏移）
       - `…` → y_offset = +0.1 × font_size_pt（略向下）
       - `-` → y_offset = 0（居中）
       - `—` → y_offset = 0（居中）
       - 其他标点 → x_offset = 0, y_offset = 0
    2. 用预设偏移位置构造 adjusted_rect，调用 compute_char_iou 计算 IoU
    3. 若预设偏移 IoU ≥ 0.5，直接用 adjusted_rect 调用 write_red_char_overlap
    4. 若预设偏移 IoU < 0.5，网格搜索 9 个候选位置
       （x_offset ∈ {-1, 0, +1}pt × y_offset ∈ {-1, 0, +1}pt）
    5. 选择 IoU 最大的位置（含预设偏移位置作为初始最佳）调用 write_red_char_overlap

    性能说明：简单实现直接调用 compute_char_iou 最多 10 次（1 预设 + 9 网格），
    每页标点约 50-100 个，10 页总额外耗时约 90 秒，可接受。

    Args:
        page: fitz.Page 对象
        rect: fitz.Rect，原字符 drawing 的 bbox
        char_text: 要写入的标点字符文本
        font_size_pt: 字号（pt）
        drawing: 原矢量字形 drawing（用于 IoU 计算时渲染原字形），可为 None
    """
    # 1. 预设偏移表（基于标点类型）
    x_offset = 0.0
    y_offset = 0.0
    if char_text == '。':
        # 句号在 bbox 下半，向下偏移 0.3×fs
        y_offset = 0.3 * font_size_pt
    elif char_text == '、':
        # 顿号在 bbox 左下，左偏 0.2×fs，下偏 0.3×fs
        x_offset = -0.2 * font_size_pt
        y_offset = 0.3 * font_size_pt
    elif char_text == '…':
        # 省略号略向下偏移 0.1×fs
        y_offset = 0.1 * font_size_pt
    elif char_text in ('-', '—'):
        # 短横线/破折号居中，不偏移
        y_offset = 0.0
    # 其他标点保持 x_offset=0, y_offset=0

    # 2. 用预设偏移构造 adjusted_rect
    preset_rect = fitz.Rect(
        rect.x0 + x_offset, rect.y0 + y_offset,
        rect.x1 + x_offset, rect.y1 + y_offset,
    )

    # 3. 计算预设偏移位置的 IoU
    best_iou = compute_char_iou(page, preset_rect, char_text, font_size_pt, drawing)
    best_rect = preset_rect

    # 4. 若预设偏移 IoU ≥ 0.5，直接用预设偏移位置写入
    if best_iou < 0.5:
        # 5. 预设偏移 IoU < 0.5，网格搜索 9 个候选位置
        # x_offset ∈ {-1, 0, +1}pt × y_offset ∈ {-1, 0, +1}pt
        for dx in (-1.0, 0.0, 1.0):
            for dy in (-1.0, 0.0, 1.0):
                cand_rect = fitz.Rect(
                    rect.x0 + dx, rect.y0 + dy,
                    rect.x1 + dx, rect.y1 + dy,
                )
                cand_iou = compute_char_iou(
                    page, cand_rect, char_text, font_size_pt, drawing
                )
                # 选择 IoU 最大的位置（> 保持第一个最大值）
                if cand_iou > best_iou:
                    best_iou = cand_iou
                    best_rect = cand_rect

    # 6. 用最佳位置调用 write_red_char_overlap 写入红字
    write_red_char_overlap(page, best_rect, char_text, font_size_pt)


# ==================== Pass 1.5 候选模板缓存（消歧 NCC 比对辅助，LRU + 线程安全） ====================
# 使用 OrderedDict 实现 LRU：命中时 move_to_end，满时 popitem(last=False) 淘汰最旧
from collections import OrderedDict as _OrderedDict
_CANDIDATE_TEMPLATE_CACHE = _OrderedDict()
_CANDIDATE_TEMPLATE_CACHE_MAX = 500
_CANDIDATE_TEMPLATE_CACHE_LOCK = threading.Lock()


def _get_or_render_candidate_template(page, rect, candidate_text, font_size_pt):
    """获取候选字符模板（带 LRU 缓存，线程安全）。

    利用平移等价性：候选模板只依赖 bbox 宽高和字号，与 rect 位置无关。
    相同 (candidate_text, font_size_pt, bbox_w, bbox_h) 的模板完全相同。
    跨页跨 worker 共享（模板与页无关），LRU 淘汰避免内存无限增长。

    Args:
        page: fitz.Page 对象
        rect: fitz.Rect，原字符 bbox
        candidate_text: str，候选字符
        font_size_pt: float，字号

    Returns:
        numpy.ndarray: 二值化模板（True=黑色像素）
    """
    bbox_w = round(rect.x1 - rect.x0, 1)
    bbox_h = round(rect.y1 - rect.y0, 1)
    fs_rounded = round(font_size_pt, 1)
    key = (candidate_text, fs_rounded, bbox_w, bbox_h)

    with _CANDIDATE_TEMPLATE_CACHE_LOCK:
        if key in _CANDIDATE_TEMPLATE_CACHE:
            # LRU 命中：移到末尾标记为最近使用
            _CANDIDATE_TEMPLATE_CACHE.move_to_end(key)
            return _CANDIDATE_TEMPLATE_CACHE[key]

    # 渲染模板（不在锁内执行，避免阻塞其他 worker）
    template = _render_candidate_template(page, rect, candidate_text, font_size_pt)

    with _CANDIDATE_TEMPLATE_CACHE_LOCK:
        if key not in _CANDIDATE_TEMPLATE_CACHE:
            # 双重检查：可能其他 worker 已渲染并缓存
            if len(_CANDIDATE_TEMPLATE_CACHE) >= _CANDIDATE_TEMPLATE_CACHE_MAX:
                # LRU 淘汰：移除最旧条目
                _CANDIDATE_TEMPLATE_CACHE.popitem(last=False)
            _CANDIDATE_TEMPLATE_CACHE[key] = template
        return _CANDIDATE_TEMPLATE_CACHE[key]


def _clear_candidate_template_cache():
    """清空候选模板缓存（仅在测试或显式回收时调用）。"""
    with _CANDIDATE_TEMPLATE_CACHE_LOCK:
        _CANDIDATE_TEMPLATE_CACHE.clear()


# ==================== red_pix 跨字符缓存（C++ 加速版辅助） ====================
_RED_PIX_CACHE = {}
_RED_PIX_CACHE_MAX = 100


def _get_or_render_red_pix(page, rect, char_text, font_size_pt):
    """获取或渲染红色字符 pixmap（带缓存）。

    利用平移等价性：red_pix 只依赖 bbox 宽高和字号，与 rect 位置无关。
    相同 (char_text, font_size_pt, bbox_w, bbox_h) 的 red_pix 完全相同。

    Args:
        page: fitz.Page 对象
        rect: fitz.Rect，原字符 bbox
        char_text: 字符文本
        font_size_pt: 字号（pt）

    Returns:
        fitz.Pixmap：红色字符渲染 pixmap
    """
    bbox_w = round(rect.x1 - rect.x0, 2)
    bbox_h = round(rect.y1 - rect.y0, 2)
    fs = round(font_size_pt, 2)
    key = (char_text, fs, bbox_w, bbox_h)
    if key in _RED_PIX_CACHE:
        return _RED_PIX_CACHE[key]
    pix = render_red_char_to_pixmap(page, rect, char_text, font_size_pt)
    if len(_RED_PIX_CACHE) >= _RED_PIX_CACHE_MAX:
        _RED_PIX_CACHE.clear()
    _RED_PIX_CACHE[key] = pix
    return pix


def _clear_red_pix_cache():
    """清空 red_pix 缓存（每页处理前调用，避免跨页内存增长）。"""
    _RED_PIX_CACHE.clear()


def write_punct_with_overlap(page, rect, char_text, font_size_pt, drawing):
    """标点覆盖率嵌字算法（C++ 加速版）。

    利用平移等价性优化：
    - red_pix 跨所有候选位置完全相同（缓存复用，相同字符+字号+bbox 只渲染一次）
    - orig_pix 内容相同仅位置平移（渲染一次，C++ 内批量平移计算 IoU）
    从原 20 次 PyMuPDF 渲染/标点 降至 2 次/标点（含缓存后更低）。

    算法流程：
    1. 预设偏移表（与 legacy 一致）
    2. 构造候选平移列表（预设偏移 + ±1pt 网格 9 点），pt→px 转换并去重
    3. C++ 批量计算所有候选位置的 IoU（一次调用）
    4. 选择 IoU 最大的位置写入红字
    5. C++ 不可用或异常时回落到 _write_punct_with_overlap_legacy

    Args:
        page: fitz.Page 对象
        rect: fitz.Rect，原字符 drawing 的 bbox
        char_text: 要写入的标点字符文本
        font_size_pt: 字号（pt）
        drawing: 原矢量字形 drawing（用于 IoU 计算时渲染原字形），可为 None
    """
    if drawing is None or not drawing.get('items'):
        write_red_char_overlap(page, rect, char_text, font_size_pt)
        return

    # 1. 预设偏移表（与 legacy 一致）
    x_offset = 0.0
    y_offset = 0.0
    if char_text == '。':
        y_offset = 0.3 * font_size_pt
    elif char_text == '、':
        x_offset = -0.2 * font_size_pt
        y_offset = 0.3 * font_size_pt
    elif char_text == '…':
        y_offset = 0.1 * font_size_pt
    elif char_text in ('-', '—'):
        y_offset = 0.0

    # 2. 构造候选平移列表（pt → px），去重
    dpi_scale = OCR_DPI / 72.0  # ≈ 4.1667
    candidates = [(x_offset, y_offset)]
    for dx in (-1.0, 0.0, 1.0):
        for dy in (-1.0, 0.0, 1.0):
            candidates.append((dx, dy))
    shifts = list(set(
        (int(round(dx * dpi_scale)), int(round(dy * dpi_scale)))
        for dx, dy in candidates
    ))

    # 3. C++ 批量计算（优先）
    if _NATIVE_AVAILABLE and compute_iou_with_shifts is not None:
        try:
            _native_log()
            red_pix = _get_or_render_red_pix(page, rect, char_text, font_size_pt)
            orig_pix = render_original_char_to_pixmap(page, drawing, rect, font_size_pt)
            ious = compute_iou_with_shifts(
                red_pix.samples, red_pix.width, red_pix.height, red_pix.n,
                orig_pix.samples, orig_pix.width, orig_pix.height, orig_pix.n,
                shifts, dilate_radius=3)
            best_idx = ious.index(max(ious))
            best_dx_px, best_dy_px = shifts[best_idx]
            best_dx_pt = best_dx_px / dpi_scale
            best_dy_pt = best_dy_px / dpi_scale
            best_rect = fitz.Rect(
                rect.x0 + best_dx_pt, rect.y0 + best_dy_pt,
                rect.x1 + best_dx_pt, rect.y1 + best_dy_pt,
            )
            write_red_char_overlap(page, best_rect, char_text, font_size_pt)
            return
        except Exception as e:
            print(f"  [WARN] C++ compute_iou_with_shifts 失败，回落: {e}")

    # 4. 回落到原逻辑
    _write_punct_with_overlap_legacy(page, rect, char_text, font_size_pt, drawing)


# ==================== 9.5 重合率检测嵌字验证（Task 1） ====================
def render_red_char_to_pixmap(page, rect, text, font_size_pt, pad=2.0):
    """在临时小页面上用与 write_red_char_overlap 相同的水平居中+垂直居中算法
    渲染红色字符，提取并返回 pixmap。

    临时页面尺寸 = max(bbox, char_size) + 2*pad，确保红字不被裁剪
    （SimSun 全角字符宽度=字号，可能大于 bbox 宽度）。
    bbox 区域在临时页面中居中，保持与原字形渲染一致的坐标系。

    Args:
        page: fitz.Page 对象（保留参数以兼容调用方签名）
        rect: fitz.Rect，原字符 drawing 的 bbox
        text: 要渲染的字符文本
        font_size_pt: 字号（pt）
        pad: float，临时页面四周保留的边距（pt）

    Returns:
        fitz.Pixmap：渲染得到的红色字符 pixmap
    """
    font = get_font_for_char(text)
    bbox_w_pt = rect.x1 - rect.x0
    bbox_h_pt = rect.y1 - rect.y0
    try:
        char_w_pt = font.text_length(text, fontsize=font_size_pt)
    except Exception:
        char_w_pt = 0.0

    # 临时页面尺寸：取 bbox 和字符尺寸的较大者，避免红字超出页面被裁剪
    temp_w = max(bbox_w_pt, char_w_pt) + 2 * pad
    temp_h = max(bbox_h_pt, font_size_pt) + 2 * pad
    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(width=temp_w, height=temp_h)

    # bbox 区域在临时页面中居中
    bbox_x = (temp_w - bbox_w_pt) / 2
    bbox_y = (temp_h - bbox_h_pt) / 2
    # 红字位置（与 write_red_char_overlap 一致的居中算法，平移到 bbox 居中位置）
    pos_x = bbox_x + (bbox_w_pt - char_w_pt) / 2
    pos_y = bbox_y + bbox_h_pt / 2 + (font.ascender + font.descender) / 2 * font_size_pt

    tw = fitz.TextWriter(temp_page.rect)
    try:
        tw.append((pos_x, pos_y), text, font=font, fontsize=font_size_pt)
        tw.write_text(temp_page, render_mode=0, color=(1, 0, 0))
    except Exception as e:
        print(f"  [WARN] render_red_char_to_pixmap 写入失败: char={text!r}, err={e}")
    pix = temp_page.get_pixmap(dpi=OCR_DPI)
    temp_doc.close()
    return pix


def render_original_char_to_pixmap(page, drawing, rect, font_size_pt, pad=2.0):
    """渲染原矢量字形到与红字相同尺寸的临时页面，bbox 区域居中。

    用与 render_red_char_to_pixmap 相同的临时页面尺寸和 bbox 居中策略，
    确保两者坐标系一致，IoU 计算时位置对齐。

    Args:
        page: fitz.Page 对象（保留参数以兼容调用方签名）
        drawing: dict，drawing 结构（含 items、rect、fill 等字段）
        rect: fitz.Rect，原字符 bbox（用于计算临时页面尺寸和平移量）
        font_size_pt: 字号（pt，用于计算临时页面尺寸，与红字一致）
        pad: float，临时页面边距（pt）

    Returns:
        fitz.Pixmap：原矢量字形的渲染 pixmap
    """
    bbox_w_pt = rect.x1 - rect.x0
    bbox_h_pt = rect.y1 - rect.y0
    try:
        font = get_font_for_char('内')
        char_w_pt = font.text_length('内', fontsize=font_size_pt)
    except Exception:
        char_w_pt = bbox_w_pt

    temp_w = max(bbox_w_pt, char_w_pt) + 2 * pad
    temp_h = max(bbox_h_pt, font_size_pt) + 2 * pad
    temp_doc = fitz.open()
    temp_page = temp_doc.new_page(width=temp_w, height=temp_h)

    # bbox 区域在临时页面中居中
    bbox_x = (temp_w - bbox_w_pt) / 2
    bbox_y = (temp_h - bbox_h_pt) / 2
    # 原字形 shift：rect.x0 → bbox_x, rect.y0 → bbox_y
    shift = fitz.Point(-rect.x0 + bbox_x, -rect.y0 + bbox_y)

    shape = temp_page.new_shape()
    for item in drawing.get('items', []):
        op = item[0]
        if op == 'l':
            shape.draw_line(item[1] + shift, item[2] + shift)
        elif op == 'c':
            shape.draw_bezier(
                item[1] + shift, item[2] + shift,
                item[3] + shift, item[4] + shift,
            )
        elif op == 're':
            r = item[1]
            new_rect = fitz.Rect(
                r.x0 + shift.x, r.y0 + shift.y,
                r.x1 + shift.x, r.y1 + shift.y,
            )
            shape.draw_rect(new_rect)
    shape.finish(
        fill=drawing.get('fill'),
        color=drawing.get('color'),
        fill_opacity=drawing.get('fill_opacity') or 1.0,
        stroke_opacity=drawing.get('stroke_opacity') or 1.0,
        width=drawing.get('width') or 1.0,
        closePath=drawing.get('closePath') or False,
        even_odd=True,
    )
    shape.commit()
    pix = temp_page.get_pixmap(dpi=OCR_DPI)
    temp_doc.close()
    return pix


def compute_char_iou(page, rect, text, font_size_pt, drawing=None, dilate_radius=3):
    """计算红字嵌字与原矢量字形的 IoU（Intersection over Union）。

    流程：
    1. 调用 render_red_char_to_pixmap 渲染红字 pixmap（临时页面足够大，避免裁剪）
    2. 调用 render_original_char_to_pixmap 渲染原字形 pixmap（相同尺寸，bbox 居中）
    3. 用 _pixmap_to_binary 二值化（True=黑色像素）
    4. 处理尺寸不一致：将较小图像居中 pad 到较大图像尺寸
    5. 对两个二值图做形态学膨胀（dilate_radius 像素），容忍字体笔画粗细差异
    6. 计算 intersection / union，返回 float IoU

    形态学膨胀的必要性：原 PDF 字体（如 STSong）与红字字体（SimSun）笔画
    粗细不同，直接像素 IoU 会偏低。膨胀后关注字形位置和形状匹配度，而非
    像素级重合，能更准确反映嵌字质量。

    Args:
        page: fitz.Page 对象
        rect: fitz.Rect，字符 bbox
        text: 嵌字字符文本
        font_size_pt: 字号（pt）
        drawing: 原矢量字形 drawing（None 时返回 1.0，表示无参照默认通过）
        dilate_radius: int，形态学膨胀半径（像素），默认 3

    Returns:
        float: IoU 值，范围 [0.0, 1.0]
    """
    if drawing is None:
        return 1.0
    try:
        red_pix = render_red_char_to_pixmap(page, rect, text, font_size_pt)
        orig_pix = render_original_char_to_pixmap(page, drawing, rect, font_size_pt)
    except Exception as e:
        print(f"  [WARN] compute_char_iou 渲染失败: char={text!r}, err={e}")
        return 0.0

    red_bin = _pixmap_to_binary(red_pix)
    orig_bin = _pixmap_to_binary(orig_pix)

    # 处理尺寸不一致：将较小图像居中 pad 到较大图像尺寸
    h1, w1 = red_bin.shape
    h2, w2 = orig_bin.shape
    max_h = max(h1, h2)
    max_w = max(w1, w2)

    def _center_pad(bin_arr, target_h, target_w):
        h, w = bin_arr.shape
        pad_h = target_h - h
        pad_w = target_w - w
        top = pad_h // 2
        bottom = pad_h - top
        left = pad_w // 2
        right = pad_w - left
        return np.pad(
            bin_arr,
            ((top, bottom), (left, right)),
            mode='constant',
            constant_values=False,
        )

    red_padded = _center_pad(red_bin, max_h, max_w)
    orig_padded = _center_pad(orig_bin, max_h, max_w)

    # 形态学膨胀：容忍字体笔画粗细差异，关注字形位置和形状匹配
    if dilate_radius > 0:
        struct = ndimage.generate_binary_structure(2, 2)
        red_dilated = ndimage.binary_dilation(
            red_padded, structure=struct, iterations=dilate_radius
        )
        orig_dilated = ndimage.binary_dilation(
            orig_padded, structure=struct, iterations=dilate_radius
        )
    else:
        red_dilated = red_padded
        orig_dilated = orig_padded

    # 计算 IoU（True 为黑色像素）
    if _NATIVE_AVAILABLE:
        _native_log()
        # 将 bool 数组转为 uint8 bytes (255=前景, 0=背景)，调用 C++ 批量 IoU
        red_bytes = (red_dilated.astype(np.uint8) * 255).tobytes()
        orig_bytes = (orig_dilated.astype(np.uint8) * 255).tobytes()
        iou_results = compute_iou_batch([(red_bytes, orig_bytes, max_w, max_h)])
        return float(iou_results[0])
    # 原 numpy 实现
    intersection = int((red_dilated & orig_dilated).sum())
    union = int((red_dilated | orig_dilated).sum())
    if union == 0:
        return 0.0
    return intersection / union


# ==================== 10. 单页处理接口（供并行调度器与 UI 调用） ====================
def process_page(engine, page, page_idx, elements_dir, output_callback=None):
    """处理单页 Pass 1：提取 drawings、分行、整行 OCR、保存元素图片。

    封装原 main() 中单页 Pass 1 的逻辑，供 ParallelOCRRunner 并行调度。
    线程安全说明：本函数内只读 page 对象（get_drawings），渲染在 render_line_image
    内新建 temp_doc.new_page() 完成，不涉及原 page 的写入操作。

    Args:
        engine: RapidOCR 引擎实例（每 worker 线程一个独立实例）
        page: fitz.Page 对象
        page_idx: 页面索引（0-based）
        elements_dir: 元素图片输出根目录（函数内会创建 page_{idx+1} 子目录）
        output_callback: 进度回调函数，接受 str 参数；None 时不输出

    Returns:
        list[dict]: page_results 列表，每个元素含 idx、rect、w、h、text、score、img、drawing 字段
    """
    page_dir = os.path.join(elements_dir, f'page_{page_idx + 1}')
    os.makedirs(page_dir, exist_ok=True)
    page_results = []

    # 提取字符 drawings 并分行
    char_draws = extract_char_drawings(page)
    if output_callback:
        output_callback(f"  第 {page_idx + 1} 页提取到 {len(char_draws)} 个字符 drawing")
    lines = group_drawings_by_line(char_draws, y_tol=2.0)
    if output_callback:
        output_callback(f"  第 {page_idx + 1} 页分行: {len(lines)} 行")

    global_idx = 0  # 全页字符 idx（用于文件名）

    # Pass 1: 整行 OCR + 保存元素图片
    for line_idx, line_draws in enumerate(lines):
        try:
            line_results = recognize_line(engine, page, line_draws)
        except Exception as e:
            if output_callback:
                output_callback(f"  [WARN] 第 {page_idx + 1} 页行 {line_idx + 1} OCR 失败: {e}")
            global_idx += len(line_draws)
            continue

        for d, (text, score, pix) in zip(line_draws, line_results):
            rect = d['rect']
            if not text or score < 0.1:
                global_idx += 1
                continue
            img_name = save_element_image(pix, page_dir, global_idx, rect)
            page_results.append({
                'idx': global_idx,
                'rect': rect,
                'w': rect.x1 - rect.x0,
                'h': rect.y1 - rect.y0,
                'text': text,
                'score': score,
                'img': img_name,
                'drawing': d,  # 保留原 drawing 引用，供 Pass 1.5 后处理使用
            })
            global_idx += 1

        if output_callback:
            success_count = sum(1 for r in page_results if r.get('text'))
            output_callback(f"  第 {page_idx + 1} 页 Pass 1 行 {line_idx + 1}/{len(lines)}: "
                            f"本行 {len(line_draws)} 字, 累计成功 {success_count}")

    return page_results


def _build_line_index(page_results, y_tolerance=2.0):
    """构建同行字符索引。

    按 y 中心容差分组所有 page_results，返回 dict：r_idx -> 同行其他字符列表。

    Args:
        page_results: 页面所有字符的列表
        y_tolerance: y 中心容差（pt）

    Returns:
        dict: {r_idx: [同行的其他字符 dict 列表]}
    """
    # 先收集 (idx, y_center) 对
    char_infos = []
    for idx, r in enumerate(page_results):
        rect = r.get('rect')
        if rect is None:
            continue
        y_center = (rect.y0 + rect.y1) / 2
        char_infos.append((idx, y_center))

    # 按 y 中心分组（首字符落入某行后，行 y 中心更新为组内平均）
    lines = []
    for idx, y_center in char_infos:
        found = False
        for line in lines:
            if abs(line['y_center'] - y_center) <= y_tolerance:
                line['indices'].append(idx)
                # 更新行 y 中心为组内平均
                line['y_center'] = sum(
                    char_infos[i][1] for i in line['indices']
                ) / len(line['indices'])
                found = True
                break
        if not found:
            lines.append({'y_center': y_center, 'indices': [idx]})

    # 构建 r_idx -> 同行其他字符列表
    index = {}
    for line in lines:
        for idx in line['indices']:
            index[idx] = [page_results[i] for i in line['indices'] if i != idx]
    return index


def process_page_pass15(page, page_results, page_idx, page_dir, output_callback=None):
    """Pass 1.5 阶段：分组消歧（规则优先 + NCC 兜底）。

    遍历 page_results，对 text 在 _DISAMBIG_GROUPS 中的字符执行消歧：
    1. 每页渲染一次整页位图（page.get_pixmap）
    2. 构建同行字符索引（按 y 中心容差 2pt 分组），为规则判定提供 height_ratio
    3. 对消歧组内字符，先按规则强判定（height_ratio/black_ratio/aspect）
    4. 规则无匹配时回落到 NCC 像素相似度比对（带模板缓存）
    5. 低于阈值时保持原 OCR 结果

    Args:
        page: fitz.Page 对象
        page_results: process_page 返回的 page_results 列表
        page_idx: 页面索引（0-based）
        page_dir: 该页元素图片目录
        output_callback: 进度回调函数

    Returns:
        dict: {'fix_count': int, 'elapsed_pass15': float}
    """
    t0 = time.time()

    # 防御性确保 page_dir 存在
    os.makedirs(page_dir, exist_ok=True)

    fix_count = 0

    # 检查是否有消歧组字符
    has_disambig = any(r.get('text', '') in _DISAMBIG_GROUPS for r in page_results)
    if has_disambig:
        # 候选模板缓存跨页跨 worker 共享（模板只依赖字符+字号+尺寸，与页无关）
        # 不在此处清空，依赖 _CANDIDATE_TEMPLATE_CACHE_MAX=500 的 LRU 淘汰
        # 构建 y 中心容差 2pt 分组的同行字符索引
        line_index = _build_line_index(page_results, y_tolerance=2.0)

        # 每页渲染一次整页位图
        page_pixmap = page.get_pixmap(dpi=OCR_DPI)

        for r_idx, r in enumerate(page_results):
            text = r.get('text', '')
            if text not in _DISAMBIG_GROUPS:
                continue
            try:
                # 获取同行其他字符
                line_chars = line_index.get(r_idx, [])
                result_char, decision_info = _disambiguate_char(
                    page, r, page_pixmap, page_idx, line_chars,
                    page_results=page_results, r_idx=r_idx
                )
                if result_char and result_char != text:
                    r['text'] = result_char
                    fix_count += 1
                    if output_callback:
                        output_callback(
                            f"  [Pass1.5] 第 {page_idx + 1} 页 idx={r.get('idx', r_idx)}: "
                            f"'{text}' → '{result_char}' ({decision_info})"
                        )
            except Exception as e:
                if output_callback:
                    output_callback(
                        f"  [WARN] 第 {page_idx + 1} 页 idx={r.get('idx', r_idx)} 消歧失败: {e}"
                    )

    elapsed_pass15 = time.time() - t0

    if output_callback:
        output_callback(
            f"  第 {page_idx + 1} 页 Pass 1.5 完成: 修正 {fix_count} 个字符, 耗时={elapsed_pass15:.2f}s"
        )

    return {
        'fix_count': fix_count,
        'elapsed_pass15': elapsed_pass15,
    }


def process_page_pass2_write(page, page_results, page_idx, page_dir, output_callback=None):
    """Pass 2: 计算字号 + 写入红字。

    必须主线程串行执行（PyMuPDF page 写入非线程安全）。

    Args:
        page: fitz.Page 对象（将被写入红字）
        page_results: list[dict]，已经过 Pass 1.5 修正 text 字段；
                      本函数会向每个 dict 写入 'font_size_pt' 字段
        page_idx: 页面索引（0-based，用于日志）
        page_dir: 该页元素图片目录
        output_callback: 进度回调函数，接受 str 参数；None 时不输出

    Returns:
        dict: {'page_chars': int, 'page_success': int, 'avg_score': float,
               'elapsed_pass2': float}
    """
    # 防御性确保 page_dir 存在
    os.makedirs(page_dir, exist_ok=True)
    pass2_t0 = time.time()
    _clear_red_pix_cache()  # 每页处理前清空缓存，避免跨页内存增长

    # 从 page_results 派生 Pass 1 统计（process_page 仅返回成功识别的条目）
    page_chars = len(page_results)
    page_success = len(page_results)
    page_score_sum = sum(r.get('score', 0.0) for r in page_results)

    # Pass 2 需要行字号（基于 rect，rect 未被 Pass 1.5 修改，结果与 Pass 1.5 一致）
    row_fontsizes = compute_row_fontsizes(page_results)

    # Pass 2: 按行字号写入红字（重合率算法）
    # 字号取值规则：
    #   - ASCII 字母/数字: 同行中文字号（get_row_fontsize）
    #   - 标点符号（含罗马数字、省略号）: 使用 get_punct_compensated_fontsize 视觉补偿
    #   - 其他（中文字符等）: max(rect_h, 1.0)
    for r in page_results:
        rect = r['rect']
        text = r['text']
        h_pt = rect.y1 - rect.y0
        if text and len(text) == 1:
            c = text[0]
            if ('0' <= c <= '9') or ('a' <= c <= 'z') or ('A' <= c <= 'Z'):
                font_size_pt = get_row_fontsize(rect, row_fontsizes)
            elif is_punctuation(c):
                # 标点符号使用视觉补偿字号（小尺寸/长形/全角标点分别补偿）
                font_size_pt = get_punct_compensated_fontsize(c, rect, row_fontsizes)
            else:
                font_size_pt = max(h_pt, 1.0)
        else:
            font_size_pt = max(h_pt, 1.0)
        r['font_size_pt'] = font_size_pt  # 保存供 Pass 4 IoU 计算使用
        # 标点符号使用覆盖率嵌字算法（位置优化，选择 IoU 最大的位置）
        # 非标点字符使用原重合率算法（水平居中 + 垂直居中）
        if text and len(text) == 1 and is_punctuation(text[0]):
            write_punct_with_overlap(page, rect, text, font_size_pt, r.get('drawing'))
        else:
            write_red_char_overlap(page, rect, text, font_size_pt)

    if output_callback:
        output_callback(f"  第 {page_idx + 1} 页 Pass 2 完成: 写入 {len(page_results)} 个红字")

    avg_score = page_score_sum / max(page_success, 1)

    return {
        'page_chars': page_chars,
        'page_success': page_success,
        'avg_score': avg_score,
        'elapsed_pass2': time.time() - pass2_t0,
    }


def process_page_post(page, page_results, page_idx, page_dir, output_callback=None):
    """处理单页 Pass 1.5 + Pass 2 + Pass 3（向后兼容包装器）。

    内部顺序调用 process_page_pass15 + process_page_pass2_write，
    返回字典与原实现字段一致。

    Args:
        page: fitz.Page 对象
        page_results: process_page 返回的 page_results 列表
        page_idx: 页面索引（0-based）
        page_dir: 该页元素图片目录
        output_callback: 进度回调函数

    Returns:
        dict: 含 page_idx/page_chars/page_success/avg_score/fix_count/
              elapsed 字段
    """
    page_t0 = time.time()

    # 防御性确保 page_dir 存在
    os.makedirs(page_dir, exist_ok=True)

    # Pass 1.5: 规则消歧
    stat15 = process_page_pass15(page, page_results, page_idx, page_dir, output_callback)

    # Pass 2 + Pass 3: 写入红字 + 行审计
    stat2 = process_page_pass2_write(page, page_results, page_idx, page_dir, output_callback)

    page_elapsed = time.time() - page_t0

    if output_callback:
        output_callback(f"  第 {page_idx + 1} 页完成: 字符数={stat2['page_chars']}, "
                        f"识别成功={stat2['page_success']}, 平均置信度={stat2['avg_score']:.3f}, "
                        f"Pass1.5修正={stat15['fix_count']}, "
                        f"耗时={page_elapsed:.2f}s")

    return {
        'page_idx': page_idx,
        'page_chars': stat2['page_chars'],
        'page_success': stat2['page_success'],
        'avg_score': stat2['avg_score'],
        'fix_count': stat15['fix_count'],
        'elapsed': page_elapsed,
    }