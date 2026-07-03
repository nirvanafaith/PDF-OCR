# 提升 OCR 识别 GPU 利用率：多页并行识别

## 当前瓶颈分析

当前 `run_ocr` 方法是**逐页串行识别**：

```python
for page_idx, page_image in enumerate(page_images):
    page_lines, page_chars = self._recognize_page(page_image, page_idx, output_callback)
```

每页的 OCR 流程是：Det(GPU) → Cls(GPU) → Rec(GPU)，三个模型串行执行。GPU 在每个模型推理之间有空闲期，且页与页之间也是串行的，导致 GPU 利用率只有约 60%。

## 优化方案：多页并行识别

### 核心思路

使用 `concurrent.futures.ThreadPoolExecutor` 实现多页并行识别：
- 同时提交 N 页的 OCR 任务到线程池
- 每个线程调用 `self.engine(page_image, ...)` 执行整页识别
- onnxruntime 的 CUDA Provider 内部使用 CUDA Stream 实现并发执行
- 多个页面的不同模型（Det/Rec）可以交替使用 GPU，减少空闲时间
- CPU 负责图像预处理和结果后处理，与 GPU 推理重叠执行

### 为什么用多线程而非多进程

1. **onnxruntime CUDA Provider 是线程安全的**：多个线程可以共享同一个 InferenceSession，CUDA 内部通过 Stream 序列化访问
2. **GIL 释放**：onnxruntime 在执行推理时释放 Python GIL，允许其他 Python 线程并行运行
3. **内存效率**：多进程需要复制模型权重，多线程共享同一模型实例
4. **简单可靠**：不需要处理进程间通信和模型序列化问题

### 修改文件：`ocr_engine/rapidocr_engine.py`

#### 1. 添加 `_recognize_page_batch` 方法

```python
def _recognize_page_batch(self, page_images_with_idx, output_callback=None):
    """并行识别多页图像。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for page_idx, page_image in page_images_with_idx:
            future = executor.submit(self._recognize_page, page_image, page_idx, output_callback)
            futures[future] = page_idx
        
        for future in as_completed(futures):
            page_idx = futures[future]
            results[page_idx] = future.result()
    
    return results
```

#### 2. 修改 `run_ocr` 方法

将逐页串行循环改为批量并行：

```python
# 收集需要识别的页面
pages_to_process = []
for page_idx, page_image in enumerate(page_images):
    if regions is not None and len(regions) > 0:
        page_regions = regions.get(page_idx, [])
        if not page_regions:
            continue
    pages_to_process.append((page_idx, page_image))

# 并行识别
batch_results = self._recognize_page_batch(pages_to_process, output_callback)

# 按页码顺序处理结果
for page_idx, page_image in enumerate(page_images):
    if page_idx not in batch_results:
        continue
    page_lines, page_chars = batch_results[page_idx]
    # ... 后续过滤和ID偏移逻辑不变
```

### 线程数选择

- `max_workers=3`：3 个线程同时提交 OCR 任务
- 原因：Det/Rec 模型交替执行时，3 个线程可以确保 GPU 始终有任务在队列中
- 不宜过大（避免 GPU 内存溢出），3 是平衡点

### 预期效果

| 指标 | 修改前 | 修改后 |
|---|---|---|
| GPU 利用率 | ~60% | ~85-95% |
| CPU 利用率 | 较低 | 中等（预处理+后处理与GPU重叠） |
| 识别速度 | 基准 | 提升 2-3x |

### 验证计划

1. 启动应用，加载 PDF，执行 OCR 识别
2. 观察 GPU 利用率是否提升到 85%+
3. 对比修改前后的识别耗时
4. 确认识别结果正确性不变
