# 精修环节输出文件时增加进度条弹窗

## 需求分析

当前精修窗口（RefineWindow）中，用户点击"输出"或"确认完成"按钮后，PDF 生成过程在主线程同步执行，导致：
- UI 冻结，无法响应用户操作
- 用户无法感知生成进度，体验差
- 对于多页文档，等待时间较长时用户可能误以为程序卡死

**目标**：在用户确认输出文件路径后，弹出一个带进度条的模态对话框，实时显示 PDF 生成进度，保持 UI 响应。

## 当前流程

```
用户点击"输出"/"确认完成"
  → RefineWindow 弹出文件保存对话框
  → RefineWindow 发射 save_signal (两次：红色版 + 透明版)
  → MainWindow._on_refine_save() 同步调用 PDFOutputGenerator.generate()
  → UI 冻结直到两份 PDF 全部生成完毕
  → 弹出成功提示
```

## 新流程

```
用户点击"输出"/"确认完成"
  → RefineWindow 弹出文件保存对话框
  → RefineWindow 创建 QProgressDialog + PDFOutputWorker(QThread)
  → Worker 在子线程中依次生成红色版和透明版 PDF
  → Worker 通过信号实时报告进度 → 更新进度条和标签文字
  → 生成完毕后关闭进度条，弹出成功提示
```

## 实施步骤

### 步骤 1：修改 `PDFOutputGenerator.generate()` — 增加进度回调

**文件**：`pdf_processor/pdf_output.py`

- 为 `generate()` 方法增加 `progress_callback=None` 参数
- 回调签名：`progress_callback(current_page: int, total_pages: int)`
- 在每页绘制完成后（`c.showPage()` 之前）调用回调
- 回调为 `None` 时不调用，保持向后兼容

### 步骤 2：创建 `PDFOutputWorker(QThread)` — PDF 生成工作线程

**文件**：`pdf_processor/pdf_output.py`（同文件内新增类）

- 继承 `QThread`，封装两份 PDF 的生成逻辑
- 构造参数：`generator, corrected_chars, page_images, red_path, transparent_path, pdf_path`
- 信号：
  - `progress_signal(int, str)` — 进度百分比(0-100) + 描述文字
  - `finished_signal()` — 生成成功完成
  - `error_signal(str)` — 生成出错，携带错误信息
- `run()` 方法逻辑：
  1. 计算总步骤数 = 2 × 总页数
  2. 生成红色版 PDF，每完成一页发射 `progress_signal`，描述为"正在生成红色文字版... (第 X/Y 页)"
  3. 生成透明版 PDF，每完成一页发射 `progress_signal`，描述为"正在生成透明文字版... (第 X/Y 页)"
  4. 全部完成后发射 `finished_signal`
  5. 出错时发射 `error_signal`

### 步骤 3：修改 `RefineWindow` — 使用工作线程 + 进度条弹窗

**文件**：`ui/refine_window.py`

#### 3a. 增加导入

- 从 `PyQt6.QtWidgets` 增加 `QProgressDialog`
- 从 `PyQt6.QtCore` 增加 `QThread`
- 从 `pdf_processor.pdf_output` 增加 `PDFOutputGenerator, PDFOutputWorker`

#### 3b. 修改 `_on_output()` 方法

原逻辑：
```python
self.save_signal.emit(corrected_chars, self.page_images, red_path, "red")
self.save_signal.emit(corrected_chars, self.page_images, transparent_path, "transparent")
self.output_complete_signal.emit(red_path, transparent_path)
```

新逻辑：
```python
self._start_pdf_generation(corrected_chars, red_path, transparent_path, is_finish=False)
```

#### 3c. 修改 `_on_finish_confirm()` 方法

原逻辑：
```python
self.save_signal.emit(corrected_chars, self.page_images, red_path, "red")
self.save_signal.emit(corrected_chars, self.page_images, transparent_path, "transparent")
self.output_complete_signal.emit(red_path, transparent_path)
self.finished_signal.emit()
```

新逻辑：
```python
self._start_pdf_generation(corrected_chars, red_path, transparent_path, is_finish=True)
```

#### 3d. 新增 `_start_pdf_generation()` 方法

核心方法，负责创建进度条弹窗和工作线程：

1. 创建 `QProgressDialog`：
   - 窗口标题："正在生成PDF"
   - 标签文字：初始为"正在准备..."
   - 范围：0-100
   - 模态对话框
   - 禁用取消按钮（`setCancelButton(None)`）
   - 设置 `setWindowModality(Qt.WindowModality.WindowModal)`
   - 设置 `setMinimumDuration(0)` 立即显示

2. 创建 `PDFOutputGenerator` 实例

3. 创建 `PDFOutputWorker` 实例

4. 连接信号：
   - `worker.progress_signal` → 更新进度条值和标签文字
   - `worker.finished_signal` → 关闭进度条、发射 `output_complete_signal`、若 `is_finish` 则发射 `finished_signal`、清理 worker
   - `worker.error_signal` → 关闭进度条、弹出错误提示、清理 worker

5. 存储 worker 引用（`self._output_worker`）防止被垃圾回收

6. 启动 worker

#### 3e. 移除 `save_signal`

- `save_signal` 不再需要，因为 PDF 生成现在由 RefineWindow 内部的工作线程完成
- 删除 `save_signal = pyqtSignal(list, list, str, str)` 声明

### 步骤 4：修改 `MainWindow` — 移除旧的同步保存处理

**文件**：`main.py`

- 删除 `_on_refine_save()` 方法
- 删除 `self.refine_widget.save_signal.connect(self._on_refine_save)` 连接
- 保留 `output_complete_signal` 和 `finished_signal` 的连接不变

### 步骤 5：为进度条弹窗添加样式

**文件**：`ui/styles.py`

在 `MAIN_STYLESHEET` 中增加 `QProgressDialog` 和 `QProgressBar` 的样式定义，保持与现有 Bootstrap 5 配色方案一致：

```css
QProgressDialog {
    background-color: #ffffff;
}

QProgressDialog QLabel {
    color: #212529;
    font-size: 13px;
}

QProgressBar {
    border: 1px solid #ced4da;
    border-radius: 4px;
    text-align: center;
    background-color: #e9ecef;
    min-height: 20px;
}

QProgressBar::chunk {
    background-color: #0D6EFD;
    border-radius: 3px;
}
```

## 涉及文件清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `pdf_processor/pdf_output.py` | 修改 + 新增 | 增加 progress_callback 参数；新增 PDFOutputWorker 类 |
| `ui/refine_window.py` | 修改 | 新增 _start_pdf_generation 方法；修改 _on_output 和 _on_finish_confirm；移除 save_signal |
| `main.py` | 修改 | 删除 _on_refine_save 方法及其信号连接 |
| `ui/styles.py` | 修改 | 增加 QProgressDialog 和 QProgressBar 样式 |

## 进度条弹窗交互设计

```
┌─────────────────────────────────────────┐
│  正在生成PDF                        ✕    │
├─────────────────────────────────────────┤
│                                         │
│  正在生成红色文字版... (第 3/10 页)      │
│                                         │
│  ████████████░░░░░░░░░░░░░░░  15%       │
│                                         │
└─────────────────────────────────────────┘
```

- 进度百分比 = (已完成页数 / 总步骤数) × 100
- 总步骤数 = 2 × 页面总数（红色版 + 透明版各一遍）
- 标签文字随阶段切换：红色版 → 透明版
- 窗口模态，阻止用户在生成期间操作主窗口
- 无取消按钮，避免生成半成品文件
