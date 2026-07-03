# 修复计划：UTF-8解码错误 + Qt线程安全问题

## 根因分析

### 错误1: UTF-8解码错误
**错误信息**: `'utf-8' codec can't decode byte 0xa8 in position 24: invalid start byte`
**位置**: `surya_engine.py` 第25-32行
**根因**: 
- 使用 `text=True, encoding="utf-8"` 打开 subprocess stdout
- Windows系统上，surya_ocr 输出的中文可能使用GBK编码（0xa8是GBK编码中的字节）
- 当输出包含非UTF-8字符时，Python解码失败

### 错误2: Qt线程问题
**错误信息**: `QObject::setParent: Cannot set parent, new parent is in a different thread`
**位置**: `ocr_prepare_window.py` 第120-141行
**根因**:
- `run_ocr_async` 使用 `threading.Thread` 在后台执行
- `output_callback`、`on_finished`、`on_error` 直接在子线程中调用 `self._append_output()` 更新UI
- Qt要求所有UI操作必须在主线程执行

## 修复方案

### 修复1: ocr_engine/surya_engine.py

将 subprocess 改为二进制模式读取，手动解码：

```python
# 修改前
self._process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    bufsize=1,
)
for line in self._process.stdout:
    output_callback(line.rstrip())

# 修改后
self._process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    bufsize=1,
)
for line_bytes in self._process.stdout:
    line = self._decode_line(line_bytes)
    if output_callback and line:
        output_callback(line.rstrip())

# 新增解码方法
def _decode_line(self, line_bytes: bytes) -> str:
    for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
        try:
            return line_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return line_bytes.decode('utf-8', errors='replace')
```

### 修复2: ui/ocr_prepare_window.py

使用 `QThread` + `pyqtSignal` 替代 `threading.Thread`：

```python
# 新增 OCRWorker 类
class OCRWorker(QObject):
    output_signal = pyqtSignal(str)      # 实时输出
    finished_signal = pyqtSignal(dict, str)  # 完成 (results, output_dir)
    error_signal = pyqtSignal(str)       # 错误

    def __init__(self, pdf_path, output_dir, ocr_engine):
        super().__init__()
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.ocr_engine = ocr_engine

    def run(self):
        try:
            results = self.ocr_engine.run_ocr(
                self.pdf_path, 
                self.output_dir,
                output_callback=lambda line: self.output_signal.emit(line)
            )
            self.finished_signal.emit(results, self.output_dir)
        except Exception as e:
            self.error_signal.emit(str(e))

# 修改 _on_run_ocr 方法
def _on_run_ocr(self):
    # 创建 worker 和 thread
    self.ocr_thread = QThread()
    self.ocr_worker = OCRWorker(self.pdf_path, output_dir, self.ocr_engine)
    self.ocr_worker.moveToThread(self.ocr_thread)
    
    # 连接信号
    self.ocr_worker.output_signal.connect(self._append_output)
    self.ocr_worker.finished_signal.connect(self._on_ocr_finished)
    self.ocr_worker.error_signal.connect(self._on_ocr_error)
    self.ocr_thread.started.connect(self.ocr_worker.run)
    
    # 启动
    self.ocr_thread.start()
```

## 修改文件清单

1. `ocr_engine/surya_engine.py`
   - 修改 `run_ocr` 方法：使用二进制模式读取stdout
   - 新增 `_decode_line` 方法：尝试多种编码解码

2. `ui/ocr_prepare_window.py`
   - 新增 `OCRWorker` 类：继承QObject，使用信号通信
   - 修改 `_on_run_ocr` 方法：使用QThread替代threading.Thread
   - 新增 `_on_ocr_finished` 和 `_on_ocr_error` 槽函数
