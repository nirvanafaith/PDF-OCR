# QThread 闪退修复与纵校切片宽度加固 实施计划

## 问题分析

### 问题1：精修输出后闪退 - QThread: Destroyed while thread is still running

**根因**：`OCRPrepareWindow._on_run_ocr` 中创建了 `QThread` 和 `OCRWorker`，OCR 完成后从未调用 `thread.quit()` / `thread.wait()` 清理线程。当精修完成调用 `_on_refine_finished` 时：

1. `self._start_ocr_prepare()` 创建新的 `OCRPrepareWindow`
2. 旧的 `self.ocr_prepare_window` 引用被覆盖
3. 旧窗口的 `ocr_thread` 对象被 Python GC 回收
4. 但 QThread 内部线程状态未正确清理 → "QThread: Destroyed while thread is still running"

**附加问题**：`_on_refine_save` 中引用 `self.ocr_prepare_window.pdf_path`，依赖旧窗口对象，不安全。

### 问题2：纵校切片宽度

当前代码已有缩放逻辑，但缺少除零保护（`pixmap.width()` 可能为 0），需要加固。

---

## 实施步骤

### Step 1: 修改 MainWindow - 保存 pdf_path 并清理旧窗口

**文件**: `main.py`

1. 在 `__init__` 中添加 `self.pdf_path = ""`
2. 在 `_on_prepare_finished` 中保存 `self.pdf_path = self.ocr_prepare_window.pdf_path`
3. 修改 `_on_refine_save`：使用 `self.pdf_path` 替代 `self.ocr_prepare_window.pdf_path`
4. 修改 `_on_refine_finished`：
   - 调用旧 `ocr_prepare_window` 的 cleanup 方法（如果存在）
   - 调用旧 `refine_window` 的 cleanup 方法（如果存在）
   - 然后再创建新窗口

### Step 2: 修改 OCRPrepareWindow - 添加 cleanup 方法

**文件**: `ui/ocr_prepare_window.py`

添加 `cleanup()` 方法：
```python
def cleanup(self):
    if self.ocr_thread is not None:
        if self.ocr_thread.isRunning():
            self.ocr_thread.quit()
            self.ocr_thread.wait(3000)
        self.ocr_thread = None
        self.ocr_worker = None
```

### Step 3: 修改 RefineWindow - 添加 cleanup 方法

**文件**: `ui/refine_window.py`

添加 `cleanup()` 方法：
```python
def cleanup(self):
    self.scene.clear()
```

### Step 4: 纵校切片宽度加固

**文件**: `ui/vertical_check_window.py`

在 eventFilter 的切片缩放逻辑中添加除零保护：
- 当 `pixmap.width() <= 0` 时跳过缩放
- `scaled_pixmap` 的目标宽高用 `max(1, ...)` 保护

---

## 依赖关系
- Step 1 依赖 Step 2 和 Step 3（需要 cleanup 方法存在）
- Step 2 和 Step 3 可并行
- Step 4 独立
