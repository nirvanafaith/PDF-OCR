# -*- coding: utf-8 -*-
"""页面级并行 OCR 调度器。

使用 ThreadPoolExecutor 实现矢量字形 PDF 整行 OCR 的页面级并行调度，
每 worker 线程持有独立的 RapidOCR 实例（共享 GPU、独立 ONNXRuntime
session），从而充分运用 GPU 算力，规避 RapidOCR 非线程安全导致的
坐标污染问题（参见 spec fix-v6-ocr-thread-safety）。

调度流程：
    Pass 1（页面级并行）：每页一个 task，多 worker 并发调用
        vector_pdf_ocr.process_page 提取 drawings、分行、整行 OCR、
        保存元素图片。引擎通过 _get_next_engine 轮询分配，page 由
        主线程在提交前通过 doc[page_idx] 获取（fitz.Page 只读访问
        在 worker 线程中安全，process_page 内部不写入 page）。
    Pass 1.5 + Pass 2 + Pass 3（主线程串行）：收集所有页
        page_results 后，串行调用 vector_pdf_ocr.process_page_post
        执行规则消歧、红字嵌字、行审计，避免 PyMuPDF
        fitz.Page 写入的线程安全问题。

依赖:
    - ocr_engine.vector_pdf_ocr: 单页处理接口（create_ocr_engine /
      process_page / process_page_post）
    - concurrent.futures.ThreadPoolExecutor: 线程池
"""

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# 将 software3 根目录加入 sys.path，确保可导入 cuda_dll_setup 与 ocr_engine 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocr_engine import vector_pdf_ocr

# C++ 加速模块（可选，失败时回落到纯 Python）
# 注：消歧相关导入已移除，后续重新实现时按需导入


class ParallelOCRRunner:
    """页面级并行 OCR 调度器。

    使用 ThreadPoolExecutor 实现 Pass 1 阶段页面级并行 OCR。
    每 worker 线程持有独立的 RapidOCR 实例（共享 GPU、独立 ONNXRuntime
    session），通过轮询方式分配引擎，避免 RapidOCR 非线程安全导致的
    坐标污染问题。

    Pass 1.5 + Pass 2 + Pass 3 阶段在主线程串行执行，因为
    PyMuPDF fitz.Page 写入操作不是线程安全的。

    典型用法:
        runner = ParallelOCRRunner(max_workers=4)
        runner.prepare_engines()
        page_results = runner.run_pass1_parallel(doc, page_indices, elements_dir, cb)
        stats = runner.run_pass2_serial(doc, page_results, elements_dir, cb)
        doc.save(output_path)  # 由调用方负责保存
        runner.shutdown()

    Attributes:
        max_workers: 最大 worker 线程数。
        _executor: ThreadPoolExecutor 实例（lazy init，在 prepare_engines 中创建）。
        _engines: RapidOCR 实例列表，每 worker 一个独立实例。
        _next_engine_idx: 轮询分配引擎的索引（仅主线程访问，无需加锁）。
        _cancelled: 取消标志，True 时停止提交新 task。
    """

    def __init__(self, max_workers=4):
        """初始化并行调度器。

        Args:
            max_workers: 最大 worker 线程数，默认 4。建议取
                min(total_pages, 4) 由调用方决定。
        """
        self.max_workers = max_workers
        self._executor = None  # lazy init，在 prepare_engines 中创建
        self._engines = []  # 每 worker 一个独立 RapidOCR 实例
        self._next_engine_idx = 0  # 轮询分配引擎的索引
        self._cancelled = False  # 取消标志

    def prepare_engines(self, num_workers=None):
        """创建 OCR 引擎与线程池。

        在主线程中创建 num_workers 个独立 RapidOCR 实例（每实例独立加载
        det + rec 两个 ONNX 模型到 GPU 显存，约 4 × 800MB = 3.2GB），
        避免在子线程创建 onnxruntime session 导致的线程安全警告。
        同时创建 ThreadPoolExecutor 用于 Pass 1 阶段并发提交页面 task。

        Args:
            num_workers: worker 线程数；None 时使用 self.max_workers。

        Returns:
            list: RapidOCR 实例列表（self._engines）。
        """
        if num_workers is None:
            num_workers = self.max_workers

        # 主线程中创建 num_workers 个独立 RapidOCR 实例
        # 必须在创建 ThreadPoolExecutor 之前完成，避免子线程创建 onnxruntime session
        self._engines = [
            vector_pdf_ocr.create_ocr_engine() for _ in range(num_workers)
        ]

        # 创建线程池（thread_name_prefix 便于调试时区分 worker 线程）
        self._executor = ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix='ocr-pass1'
        )

        cuda_available = self._engines[0]._has_cuda if self._engines else False
        print(f"[ParallelOCRRunner] Prepared {num_workers} engines, "
              f"CUDA available: {cuda_available}")
        # 显存占用估算：每实例 det + rec 两模型约 800MB
        print(f"[ParallelOCRRunner] Estimated GPU memory: ~{num_workers * 800}MB "
              f"({num_workers} engines x 800MB/engine)")
        return self._engines

    def _get_next_engine(self):
        """轮询返回下一个 RapidOCR 引擎实例。

        通过 self._next_engine_idx 在 self._engines 中轮询分配，确保
        各 worker 线程使用独立引擎，避免 RapidOCR 非线程安全导致的
        坐标污染问题。本函数仅在主线程提交 task 前调用，无需加锁。

        Returns:
            RapidOCR: 下一个可用的引擎实例。
        """
        engine = self._engines[self._next_engine_idx]
        self._next_engine_idx = (self._next_engine_idx + 1) % len(self._engines)
        return engine

    def run_pass1_parallel(self, doc, page_indices, elements_dir, output_callback=None, progress_callback=None):
        """Pass 1 阶段：页面级并行执行 OCR 识别。

        使用 self._executor 提交每页 task，每 task 调用
        vector_pdf_ocr.process_page 提取 drawings、分行、整行 OCR、
        保存元素图片。引擎通过 _get_next_engine 轮询分配，page 在
        提交前由主线程通过 doc[page_idx] 获取（fitz.Page 只读访问在
        worker 线程中是安全的，process_page 内部不写入 page，仅在
        temp_doc 中渲染）。

        取消机制：每页提交前检查 self._cancelled，若已取消则不再提交
        剩余页。已提交的 task 继续执行，结果通过 future.exception()
        收集异常，单页失败不中断整体流程。

        线程安全说明：
            - self._next_engine_idx 仅在主线程提交循环中递增，无竞争。
            - 每个 worker 持有独立 RapidOCR 实例，无共享状态。
            - page 对象在 process_page 内部只读访问（get_drawings），
              渲染在 temp_doc 中完成，不涉及原 page 写入。

        Args:
            doc: fitz.Document 对象。
            page_indices: 0-based 页面索引列表。
            elements_dir: 元素图片输出根目录（process_page 内部创建
                page_{idx+1} 子目录）。
            output_callback: 进度回调函数，接受 str 参数；None 时不输出。
                注意：此回调会被 worker 线程间接调用（process_page 内部
                上报子进度），调用方需保证线程安全（如使用 Qt signal）。
            progress_callback: 数值进度回调函数，签名为 (current, total, status)；
                None 时不回调。每完成一页调用一次，调用方可用于驱动进度条。

        Returns:
            dict: {page_idx: page_results} 映射，按 page_idx 升序。失败
            的页面不会出现在返回字典中。
        """
        results = {}
        total = len(page_indices)
        completed = 0
        futures = {}  # future -> page_idx

        # 提交阶段：主线程串行提交每页 task
        for page_idx in page_indices:
            # 取消检查：若已取消则不再提交剩余页
            if self._cancelled:
                if output_callback:
                    output_callback(
                        f"[ParallelOCRRunner] Pass 1 已取消，跳过第 {page_idx + 1} 页及剩余页"
                    )
                break
            # 主线程中轮询分配引擎 + 获取 page 对象
            engine = self._get_next_engine()
            page = doc[page_idx]
            future = self._executor.submit(
                vector_pdf_ocr.process_page,
                engine, page, page_idx, elements_dir, output_callback,
            )
            futures[future] = page_idx

        # 收集阶段：按完成顺序收集结果
        for future in as_completed(futures):
            page_idx = futures[future]
            completed += 1
            try:
                page_results = future.result()
                results[page_idx] = page_results
            except Exception as exc:
                # 单页失败：记录错误，不中断整体流程
                err_msg = (f"[ParallelOCRRunner] 第 {page_idx + 1} 页 Pass 1 失败: "
                           f"{type(exc).__name__}: {exc}")
                print(err_msg)
                if output_callback:
                    output_callback(err_msg)
            # 进度回调（成功或失败都推进进度）
            if output_callback:
                output_callback(f"Pass 1 进度: {completed}/{total} 页完成")
            if progress_callback:
                progress_callback(completed, total, f"Pass 1 识别中: {completed}/{total}")

        # 按 page_idx 升序返回（dict 在 Python 3.7+ 保持插入顺序）
        return {idx: results[idx] for idx in sorted(results.keys())}

    def run_pass15_parallel(self, doc, all_page_results, elements_dir, output_callback=None, progress_callback=None):
        """Pass 1.5 阶段：页面级并行规则消歧。

        使用 ThreadPoolExecutor 并行调用 vector_pdf_ocr.process_page_pass15，
        每页一个 task。Pass 1.5 仅修改 page_results[i]['text'] 字段，不写原 page，
        可安全并行执行。

        worker 数取 min(os.cpu_count() or 8, total_pages)，不占用 GPU 资源。

        Args:
            doc: fitz.Document 对象（仅用于 doc[page_idx] 取 page）
            all_page_results: {page_idx: page_results} 映射，来自 Pass 1
            elements_dir: 元素图片输出根目录
            output_callback: 文本进度回调
            progress_callback: 数值进度回调 (current, total, status)

        Returns:
            dict: {'total_fix': int, 'elapsed': float}
        """
        total = len(all_page_results)
        if total == 0:
            return {'total_fix': 0, 'elapsed': 0.0}

        num_workers = min(os.cpu_count() or 8, total)
        print(f"[ParallelOCRRunner] Pass 1.5 parallel with {num_workers} workers")

        total_fix = 0
        total_elapsed = 0.0
        completed = 0
        futures = {}  # future -> page_idx

        # 临时线程池，仅本阶段使用，结束后立即 shutdown(wait=True)
        # 不复用 self._executor（那是 Pass 1 用的）
        executor = ThreadPoolExecutor(
            max_workers=num_workers, thread_name_prefix='ocr-pass15'
        )
        try:
            # 提交阶段：主线程串行提交每页 task
            for page_idx in sorted(all_page_results.keys()):
                # 取消检查：若已取消则不再提交剩余页
                if self._cancelled:
                    if output_callback:
                        output_callback(
                            f"[ParallelOCRRunner] Pass 1.5 已取消，跳过第 {page_idx + 1} 页及剩余页"
                        )
                    break
                page_results = all_page_results[page_idx]
                page = doc[page_idx]  # 主线程预取 page（与 run_pass1_parallel 一致）
                page_dir = os.path.join(elements_dir, f'page_{page_idx + 1}')
                os.makedirs(page_dir, exist_ok=True)
                future = executor.submit(
                    vector_pdf_ocr.process_page_pass15,
                    page, page_results, page_idx, page_dir, output_callback,
                )
                futures[future] = page_idx

            # 收集阶段：按完成顺序收集结果
            for future in as_completed(futures):
                page_idx = futures[future]
                completed += 1
                try:
                    stat = future.result()
                    total_fix += int(stat.get('fix_count', 0))
                    total_elapsed += float(stat.get('elapsed_pass15', 0.0))
                except Exception as exc:
                    # 单页失败：记录错误，不中断整体流程
                    err_msg = (f"[ParallelOCRRunner] 第 {page_idx + 1} 页 Pass 1.5 失败: "
                               f"{type(exc).__name__}: {exc}")
                    print(err_msg)
                    if output_callback:
                        output_callback(err_msg)
                # 进度回调（成功或失败都推进进度）
                if output_callback:
                    output_callback(f"Pass 1.5 进度: {completed}/{total} 页完成")
                if progress_callback:
                    progress_callback(completed, total, f"Pass 1.5 消歧中: {completed}/{total}")
        finally:
            executor.shutdown(wait=True)

        return {'total_fix': total_fix, 'elapsed': total_elapsed}

    def run_pass15_global_char_parallel(self, doc, all_page_results, elements_dir,
                                        output_callback=None, progress_callback=None):
        """Pass 1.5 阶段（空壳实现，直接调用 run_pass15_parallel）。

        保留函数签名以维持调用链路兼容性。
        后续将重新实现并行消歧调度逻辑。

        Args:
            doc: fitz.Document 对象（仅用于 doc[page_idx] 取 page）
            all_page_results: {page_idx: page_results} 映射，来自 Pass 1
            elements_dir: 元素图片输出根目录
            output_callback: 文本进度回调
            progress_callback: 数值进度回调 (current, total, status)

        Returns:
            dict: {'total_fix': int, 'elapsed': float}
        """
        return self.run_pass15_parallel(
            doc, all_page_results, elements_dir,
            output_callback=output_callback,
            progress_callback=progress_callback,
        )

    def run_pass2_write_serial(self, doc, all_page_results, elements_dir, output_callback=None, progress_callback=None):
        """Pass 2 + Pass 3 阶段：主线程串行写入红字 + 行审计。

        串行调用 vector_pdf_ocr.process_page_pass2_write，写原 page（PyMuPDF 非线程安全）。

        Args:
            doc: fitz.Document 对象
            all_page_results: {page_idx: page_results} 映射（已被 Pass 1.5 修正 text 字段）
            elements_dir: 元素图片输出根目录
            output_callback: 文本进度回调
            progress_callback: 数值进度回调 (current, total, status)

        Returns:
            dict: {'total_chars': int, 'total_success': int,
                   'avg_score': float, 'elapsed': float}
        """
        total_chars = 0
        total_success = 0
        total_avg_score = 0.0
        total_elapsed = 0.0

        total = len(all_page_results)
        completed = 0

        # 按 page_idx 升序处理，保证 PDF 写入顺序与原页面顺序一致
        for page_idx in sorted(all_page_results.keys()):
            # 取消检查
            if self._cancelled:
                if output_callback:
                    output_callback(
                        f"[ParallelOCRRunner] Pass 2 已取消，跳过第 {page_idx + 1} 页及剩余页"
                    )
                break

            page_results = all_page_results[page_idx]
            page = doc[page_idx]
            page_dir = os.path.join(elements_dir, f'page_{page_idx + 1}')
            os.makedirs(page_dir, exist_ok=True)  # 防御性

            try:
                stat = vector_pdf_ocr.process_page_pass2_write(
                    page, page_results, page_idx, page_dir, output_callback
                )
            except Exception as exc:
                # 单页失败：记录错误，不中断整体流程
                err_msg = (f"[ParallelOCRRunner] 第 {page_idx + 1} 页 Pass 2 失败: "
                           f"{type(exc).__name__}: {exc}")
                print(err_msg)
                if output_callback:
                    output_callback(err_msg)
                completed += 1
                if output_callback:
                    output_callback(f"Pass 2 进度: {completed}/{total} 页完成")
                if progress_callback:
                    progress_callback(completed, total, f"Pass 2 嵌字中: {completed}/{total}")
                continue

            # 累计统计（字段名对齐 process_page_pass2_write 的返回字典）
            total_chars += int(stat.get('page_chars', 0))
            total_success += int(stat.get('page_success', 0))
            total_avg_score += float(stat.get('avg_score', 0.0))
            total_elapsed += float(stat.get('elapsed_pass2', 0.0))

            completed += 1
            if output_callback:
                output_callback(f"Pass 2 进度: {completed}/{total} 页完成")
            if progress_callback:
                progress_callback(completed, total, f"Pass 2 嵌字中: {completed}/{total}")

        return {
            'total_chars': total_chars,
            'total_success': total_success,
            'avg_score': total_avg_score / max(len(all_page_results), 1),
            'elapsed': total_elapsed,
        }

    def run_pass2_serial(self, doc, all_page_results, elements_dir, output_callback=None, progress_callback=None):
        """Pass 1.5 + Pass 2 + Pass 3 阶段（向后兼容包装器）。

        内部顺序调用 run_pass15_parallel + run_pass2_write_serial。
        progress_callback 在三个子阶段间按 50-65% / 65-100% 映射。

        返回字典字段与原实现一致：total_pages/total_chars/total_success/total_fix/
        elapsed。
        """
        import time as _time
        t0 = _time.time()
        total = len(all_page_results)

        # Pass 1.5: 50-65%
        def _pass15_progress(current, tot, status):
            if progress_callback:
                combined = 50 + int(current * 15 / max(tot, 1))
                progress_callback(combined, 100, status)
        stat15 = self.run_pass15_parallel(
            doc, all_page_results, elements_dir, output_callback, _pass15_progress
        )

        # Pass 2+3: 65-100%
        def _pass2_progress(current, tot, status):
            if progress_callback:
                combined = 65 + int(current * 35 / max(tot, 1))
                progress_callback(combined, 100, status)
        stat2 = self.run_pass2_write_serial(
            doc, all_page_results, elements_dir, output_callback, _pass2_progress
        )

        return {
            'total_pages': total,
            'total_chars': stat2.get('total_chars', 0),
            'total_success': stat2.get('total_success', 0),
            'total_fix': stat15.get('total_fix', 0),
            'elapsed': _time.time() - t0,
        }

    def cancel(self):
        """设置取消标志，停止提交新 task。

        后续 submit 前会检查 _cancelled，已提交的 task 不主动中断
        （依赖 worker 自然完成）。run_pass2_serial 在每页处理前
        也会检查 _cancelled，已处理的页统计保留，剩余页跳过。
        """
        self._cancelled = True

    def shutdown(self):
        """关闭线程池并释放 OCR 引擎资源。

        等待所有已提交 task 完成（wait=True），清空引擎列表让
        onnxruntime session 被 GC 回收。调用后实例不可再使用，
        如需再次使用需重新调用 prepare_engines。
        """
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None
        # 释放 RapidOCR 实例引用，让 onnxruntime session 被 GC 回收
        self._engines = []
        self._next_engine_idx = 0
        print("[ParallelOCRRunner] Shutdown complete")
