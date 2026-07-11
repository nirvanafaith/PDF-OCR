"""RapidOCR 测试脚本。

使用 铁路客货运输.pdf 和 铁路客货运输_middle.json 测试 RapidOCR 的 CUDA 推理是否正常工作。
验证项：
1. nvrtc64_120_0.dll 可加载（解决 "Could not locate nvrtc64_120_0.dll" 错误）
2. middle.json 可正确解析（验证 para_blocks/preproc_blocks 兼容修复）
3. RapidOCR GPU 推理无 HEURISTIC_QUERY_FAILED 错误
4. RapidOCR 成功识别文本

用法:
    cd e:\\hx\\software1
    python test_rapidocr.py [--pages N] [--pdf PATH] [--json PATH]

参数:
    --pages N   测试前 N 页（默认 3）
    --pdf PATH  PDF 文件路径（默认 铁路客货运输.pdf）
    --json PATH middle.json 文件路径（默认 铁路客货运输_middle.json）
"""

import argparse
import ctypes
import json
import os
import sys
import time

# 确保能导入 software1 内部模块
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

# 第一步：设置 CUDA DLL 路径（必须在导入 onnxruntime/rapidocr 之前）
from cuda_dll_setup import setup_cuda_dll_paths
setup_cuda_dll_paths()


def test_nvrtc_dll():
    """测试 1：验证 nvrtc64_120_0.dll 可加载。"""
    print("=" * 60)
    print("[测试 1] 验证 nvrtc64_120_0.dll 可加载")
    print("=" * 60)
    try:
        ctypes.WinDLL('nvrtc64_120_0.dll')
        print("  [PASS] nvrtc64_120_0.dll 加载成功")
        return True
    except OSError as e:
        print(f"  [FAIL] nvrtc64_120_0.dll 加载失败: {e}")
        return False


def test_middle_json(json_path, num_pages):
    """测试 2：加载 middle.json 并提取文本框区域。

    middle.json 的 bbox 为 PDF 点坐标（72 DPI），
    需乘以 dpi/72 转换为渲染后像素坐标。

    参数:
        json_path: middle.json 文件路径
        num_pages: 要提取的页数

    返回:
        tuple: (success, regions_dict) regions_dict 格式为 {page_idx: [[x1,y1,x2,y2], ...]}
    """
    print("\n" + "=" * 60)
    print("[测试 2] 加载 middle.json 并提取文本框区域")
    print("=" * 60)

    if not os.path.isfile(json_path):
        print(f"  [FAIL] 文件不存在: {json_path}")
        return False, {}

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    pdf_info = data.get('pdf_info', [])
    if not pdf_info:
        print("  [FAIL] middle.json 中无 pdf_info")
        return False, {}

    print(f"  middle.json 包含 {len(pdf_info)} 页数据")

    # 提取文本框区域
    dpi = 300
    scale = dpi / 72.0  # PDF 点坐标 → 像素坐标
    expand = 2  # 边界扩展像素

    # 文本块类型（与 draw_box_window.py TEXT_BLOCK_TYPES 一致）
    text_block_types = {'text', 'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
    text_sub_block_types = {'text', 'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    regions = {}
    total_blocks = 0

    for page_idx, page_data in enumerate(pdf_info):
        if page_idx >= num_pages:
            break
        # 兼容 para_blocks 和 preproc_blocks
        blocks = page_data.get('para_blocks', []) or page_data.get('preproc_blocks', [])
        page_regions = []
        for block in blocks:
            block_type = block.get('type', '')
            bboxes_to_add = []
            if block_type in text_block_types:
                bbox = block.get('bbox', [])
                if len(bbox) == 4:
                    bboxes_to_add.append(bbox)
            elif block_type in ('list', 'image', 'table'):
                for sub_block in block.get('blocks', []):
                    if sub_block.get('type', '') not in text_sub_block_types:
                        continue
                    bbox = sub_block.get('bbox', [])
                    if len(bbox) == 4:
                        bboxes_to_add.append(bbox)
            for bbox in bboxes_to_add:
                x0, y0, x1, y1 = bbox
                ix0 = max(0, x0 * scale - expand)
                iy0 = max(0, y0 * scale - expand)
                ix1 = x1 * scale + expand
                iy1 = y1 * scale + expand
                page_regions.append([ix0, iy0, ix1, iy1])
                total_blocks += 1
        if page_regions:
            regions[page_idx] = page_regions

    if total_blocks == 0:
        print("  [FAIL] 未提取到任何文本框区域（para_blocks/preproc_blocks 键名可能不匹配）")
        return False, {}
    print(f"  [PASS] 提取到 {total_blocks} 个文本框区域（前 {min(num_pages, len(pdf_info))} 页）")
    for page_idx, page_regions in sorted(regions.items()):
        print(f"    第 {page_idx + 1} 页: {len(page_regions)} 个区域")
    return True, regions


def test_rapidocr_full_page(pdf_path, num_pages):
    """测试 3：RapidOCR 整页识别（无区域限制）。

    参数:
        pdf_path: PDF 文件路径
        num_pages: 测试页数

    返回:
        tuple: (success, lines_count, chars_count)
    """
    print("\n" + "=" * 60)
    print(f"[测试 3] RapidOCR 整页识别（前 {num_pages} 页）")
    print("=" * 60)

    import fitz  # PyMuPDF

    if not os.path.isfile(pdf_path):
        print(f"  [FAIL] PDF 文件不存在: {pdf_path}")
        return False, 0, 0

    print("  正在实例化 OCREngine（触发 RapidOCR + CUDA 检测）...")
    t0 = time.time()
    from ocr_engine import OCREngine
    engine = OCREngine()
    print(f"  OCREngine 实例化完成，耗时 {time.time() - t0:.1f}s")

    # 将 PDF 前 N 页转为图像
    doc = fitz.open(pdf_path)
    dpi = 300
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)

    from PIL import Image
    page_images = []
    for i in range(min(num_pages, len(doc))):
        pix = doc[i].get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        page_images.append(img)
    doc.close()
    print(f"  已加载 {len(page_images)} 页图像")

    # 逐页识别
    total_lines = 0
    total_chars = 0
    for page_idx, page_image in enumerate(page_images):
        t0 = time.time()
        lines, chars = engine._recognize_page(page_image, page_idx)
        elapsed = time.time() - t0
        line_count = len(lines)
        char_count = len(chars)
        total_lines += line_count
        total_chars += char_count
        # 打印前几行识别结果
        preview_lines = lines[:3]
        preview_text = " | ".join(l.get('text', '')[:20] for l in preview_lines)
        print(f"  第 {page_idx + 1} 页: {line_count} 行, {char_count} 字符, {elapsed:.1f}s — {preview_text}")

    if total_lines == 0:
        print(f"  [FAIL] 未识别到任何文本（Lines=0）")
        return False, 0, 0
    print(f"  [PASS] 共识别 {total_lines} 行, {total_chars} 字符")
    return True, total_lines, total_chars


def test_rapidocr_with_regions(pdf_path, json_path, num_pages):
    """测试 4：RapidOCR 区域识别（使用 middle.json 提取的区域）。

    参数:
        pdf_path: PDF 文件路径
        json_path: middle.json 文件路径
        num_pages: 测试页数

    返回:
        tuple: (success, lines_count, chars_count)
    """
    print("\n" + "=" * 60)
    print(f"[测试 4] RapidOCR 区域识别（middle.json 区域，前 {num_pages} 页）")
    print("=" * 60)

    # 先提取区域
    success, regions = test_middle_json(json_path, num_pages)
    if not success:
        print("  [SKIP] 区域提取失败，跳过区域识别测试")
        return False, 0, 0

    if not regions:
        print("  [SKIP] 无区域数据，跳过区域识别测试")
        return False, 0, 0

    import fitz
    from PIL import Image
    from ocr_engine import OCREngine

    print("  正在实例化 OCREngine...")
    engine = OCREngine()

    # 加载 PDF 页面图像
    doc = fitz.open(pdf_path)
    dpi = 300
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)

    page_images = {}
    for page_idx in regions:
        if page_idx >= len(doc):
            continue
        pix = doc[page_idx].get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        page_images[page_idx] = img
    doc.close()

    # 对每页的每个区域裁剪并识别
    total_lines = 0
    total_chars = 0
    for page_idx, page_regions in sorted(regions.items()):
        if page_idx not in page_images:
            continue
        page_img = page_images[page_idx]
        for region_idx, region in enumerate(page_regions):
            x0, y0, x1, y1 = [int(v) for v in region]
            # 裁剪区域
            cropped = page_img.crop((x0, y0, x1, y1))
            # 识别
            lines, chars = engine._recognize_page(cropped, page_idx)
            total_lines += len(lines)
            total_chars += len(chars)
        preview = f"{len(page_regions)} 区域"
        print(f"  第 {page_idx + 1} 页: {preview}")

    if total_lines == 0:
        print(f"  [FAIL] 区域识别未识别到任何文本")
        return False, 0, 0
    print(f"  [PASS] 区域识别共 {total_lines} 行, {total_chars} 字符")
    return True, total_lines, total_chars


def main():
    parser = argparse.ArgumentParser(description='RapidOCR 测试脚本')
    parser.add_argument('--pages', type=int, default=3, help='测试前 N 页（默认 3）')
    parser.add_argument('--pdf', type=str, default='铁路客货运输.pdf', help='PDF 文件路径')
    parser.add_argument('--json', type=str, default='铁路客货运输_middle.json', help='middle.json 文件路径')
    args = parser.parse_args()

    pdf_path = os.path.join(_script_dir, args.pdf)
    json_path = os.path.join(_script_dir, args.json)
    num_pages = args.pages

    print(f"PDF: {pdf_path}")
    print(f"JSON: {json_path}")
    print(f"测试页数: {num_pages}")

    results = {}

    # 测试 1：nvrtc DLL
    results['nvrtc_dll'] = test_nvrtc_dll()

    # 测试 2：middle.json 加载
    results['middle_json'], _ = test_middle_json(json_path, num_pages)

    # 测试 3：整页 RapidOCR
    results['full_page'], lines, chars = test_rapidocr_full_page(pdf_path, num_pages)

    # 测试 4：区域 RapidOCR
    results['region_ocr'], r_lines, r_chars = test_rapidocr_with_regions(pdf_path, json_path, num_pages)

    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"  nvrtc64_120_0.dll 加载:  {'PASS' if results['nvrtc_dll'] else 'FAIL'}")
    print(f"  middle.json 解析:        {'PASS' if results['middle_json'] else 'FAIL'}")
    print(f"  整页 RapidOCR:           {'PASS' if results['full_page'] else 'FAIL'} ({lines} 行, {chars} 字符)")
    print(f"  区域 RapidOCR:           {'PASS' if results['region_ocr'] else 'FAIL'} ({r_lines} 行, {r_chars} 字符)")
    print("=" * 60)

    all_pass = all(results.values())
    if all_pass:
        print("\n所有测试通过！")
        return 0
    else:
        print("\n部分测试失败，请检查上方输出。")
        return 1


if __name__ == '__main__':
    sys.exit(main())
