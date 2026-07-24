# -*- coding: utf-8 -*-
"""一次性冒烟测试：验证 software3 OCR 流水线可在无 GUI 情况下端到端运行。"""
import os
import sys
import time

# 确保 software3 包可导入
sys.path.insert(0, r'd:\hx\software3')
os.chdir(r'd:\hx\software3')

from cuda_dll_setup import setup_cuda_dll_paths
setup_cuda_dll_paths()

import fitz
from ocr_engine.parallel_runner import ParallelOCRRunner

TEST_PDF = r'd:\hx\software3\test_data\27141城市轨道交通通信技术内文1-1_前10页.pdf'
OUT_PDF = r'd:\hx\software3\test_data\_smoke_out.pdf'
ELEMENTS_DIR = r'd:\hx\software3\test_data\_smoke_elements'

t0 = time.time()
print(f"[smoke] Opening {TEST_PDF}")
doc = fitz.open(TEST_PDF)
print(f"[smoke] Total pages: {len(doc)}")

# 只测第 1 页以加速
page_indices = [0]
runner = ParallelOCRRunner(max_workers=1)
print(f"[smoke] Preparing engines...")
engines = runner.prepare_engines()
print(f"[smoke] Engines ready: {len(engines)}, CUDA: {getattr(engines[0], '_has_cuda', 'unknown')}")

print(f"[smoke] Pass 1 parallel on page {page_indices}...")
all_page_results = runner.run_pass1_parallel(
    doc, page_indices, ELEMENTS_DIR,
    output_callback=lambda msg: print(f"[smoke] {msg}")
)
print(f"[smoke] Pass 1 done, {len(all_page_results)} pages returned")

print(f"[smoke] Pass 2 serial...")
stats = runner.run_pass2_serial(
    doc, all_page_results, ELEMENTS_DIR,
    output_callback=lambda msg: print(f"[smoke] {msg}")
)
print(f"[smoke] Pass 2 done, stats: {stats}")

print(f"[smoke] Saving output to {OUT_PDF}")
doc.save(OUT_PDF, garbage=4, deflate=True)
doc.close()

runner.shutdown()
elapsed = time.time() - t0
print(f"[smoke] OK, total elapsed: {elapsed:.1f}s")
print(f"[smoke] Output exists: {os.path.exists(OUT_PDF)}, size: {os.path.getsize(OUT_PDF) / 1024:.1f} KB")
