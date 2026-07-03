# 精修输出逻辑修正与返回按钮计划

## 需求分析

用户提出两个需求：

1. **精修输出逻辑修正**：点击"输出"按钮后只生成PDF文件，不自动返回初始页面；新增"确认完成"按钮，按下后才返回最初的OCR准备页面
2. **返回上一步按钮**：给横校、纵校、精修三个界面加上左上角的"返回"按钮，点击后返回上一步

## 现状分析

### 精修输出逻辑
- 当前 `_on_output` 方法在输出PDF后立即发射 `finished_signal`，导致 `MainWindow._on_refine_finished` 被触发，清理所有窗口并重新进入OCR准备阶段
- **需要修改**：`_on_output` 不再发射 `finished_signal`，新增独立的"确认完成"按钮来发射该信号

### 返回上一步
- 当前三个校对窗口（横校、纵校、精修）都没有"返回上一步"的按钮
- 横校窗口没有工具栏，使用 `QHBoxLayout` 布局
- 纵校和精修窗口使用 `QToolBar` 工具栏
- 需要在每个窗口新增 `back_signal` 信号，由 `MainWindow` 处理返回逻辑

### MainWindow 中的返回逻辑
- 横校 → 返回OCR准备：需要重新显示 `OCRPrepareWindow`
- 纵校 → 返回横校：需要重新显示 `HorizontalCheckWindow`（保留横校数据）
- 精修 → 返回纵校：需要重新显示 `VerticalCheckWindow`（保留纵校数据）

**关键设计决策**：返回上一步时，是否保留当前步骤的修改？
- 横校返回OCR准备：横校数据丢弃（因为OCR准备阶段会重新生成数据）
- 纵校返回横校：纵校数据丢弃（因为横校阶段会重新构建行数据）
- 精修返回纵校：精修数据丢弃（因为纵校阶段会重新构建精修数据）

这意味着返回上一步本质上是"回退到上一个阶段"，当前阶段的数据会被丢弃。

## 实施步骤

### 步骤1：修改 `ui/refine_window.py` — 输出不再自动完成 + 新增确认完成按钮

**1a. 修改 `_on_output` 方法**：移除 `self.finished_signal.emit()`

```python
def _on_output(self):
    self._sync_current_page()
    output_path, _ = QFileDialog.getSaveFileName(
        self, "保存文件", "", "PDF 文件 (*.pdf);;所有文件 (*)"
    )
    if not output_path:
        return
    corrected_chars = self._build_corrected_chars()
    base, ext = os.path.splitext(output_path)
    red_path = f"{base}_红{ext}"
    transparent_path = f"{base}_透明{ext}"
    self.save_signal.emit(corrected_chars, self.page_images, red_path, "red")
    self.save_signal.emit(corrected_chars, self.page_images, transparent_path, "transparent")
    self.output_complete_signal.emit(red_path, transparent_path)
    # 不再发射 finished_signal
```

**1b. 在工具栏中新增"确认完成"按钮**：在"输出"按钮之后添加

```python
self.finish_btn = QPushButton("确认完成")
self.finish_btn.setStyleSheet(
    "QPushButton { background-color: #198754; color: white; ... }"
)
self.finish_btn.clicked.connect(self._on_finish_confirm)
toolbar.addWidget(self.finish_btn)
```

**1c. 新增 `_on_finish_confirm` 方法**：弹出确认对话框后发射 `finished_signal`

```python
def _on_finish_confirm(self):
    reply = QMessageBox.question(
        self, "确认完成", "确认完成后将返回初始页面，当前精修数据将不再保留。\n是否确认？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply == QMessageBox.StandardButton.Yes:
        self.finished_signal.emit()
```

**1d. 新增 `back_signal` 信号**：

```python
back_signal = pyqtSignal()
```

**1e. 在工具栏最左侧添加"返回"按钮**：

```python
self.back_btn = QPushButton("← 返回")
self.back_btn.clicked.connect(self._on_back)
toolbar.insertWidget(toolbar.actions()[0], self.back_btn)  # 插到最前面
```

实际上由于工具栏是用 `addWidget` 而非 `addAction`，需要在第一个 widget 之前插入。更简单的方式是在工具栏构建时，最先添加返回按钮。

**1f. 新增 `_on_back` 方法**：

```python
def _on_back(self):
    self.back_signal.emit()
```

### 步骤2：修改 `ui/vertical_check_window.py` — 新增返回按钮

**2a. 新增 `back_signal` 信号**：

```python
back_signal = pyqtSignal()
```

**2b. 在工具栏最左侧添加"返回"按钮**：在 `_init_ui` 中，toolbar 构建时最先添加

```python
self.back_btn = QPushButton("← 返回")
self.back_btn.clicked.connect(self._on_back)
toolbar.addWidget(self.back_btn)
toolbar.addSeparator()
```

**2c. 新增 `_on_back` 方法**：

```python
def _on_back(self):
    self.back_signal.emit()
```

### 步骤3：修改 `ui/horizontal_check_window.py` — 新增返回按钮

横校窗口没有工具栏，使用 `QHBoxLayout`。需要在界面顶部或左侧添加返回按钮。

**方案**：在 `_init_ui` 中，在 `main_layout` 之上增加一个顶部水平布局，放置返回按钮。

或者更简单的方式：在左侧字符列表区域的上方添加返回按钮。

**3a. 新增 `back_signal` 信号**：

```python
back_signal = pyqtSignal()
```

**3b. 在左侧面板顶部添加返回按钮**：在 `left_layout` 的最前面添加

```python
self.back_btn = QPushButton("← 返回上一步")
self.back_btn.clicked.connect(self._on_back)
left_layout.addWidget(self.back_btn)
```

**3c. 新增 `_on_back` 方法**：

```python
def _on_back(self):
    self.back_signal.emit()
```

### 步骤4：修改 `main.py` — 处理返回信号和精修完成逻辑

**4a. 横校返回OCR准备**：在 `_on_prepare_finished` 中连接 `back_signal`

```python
self.horiz_widget.back_signal.connect(self._on_horizontal_back)
```

新增 `_on_horizontal_back` 方法：
```python
def _on_horizontal_back(self):
    self.horiz_widget.cleanup()
    self.stack.removeWidget(self.horiz_widget)
    self.horiz_widget.deleteLater()
    self.current_stage = 0
    self.step_indicator.set_current(0)
    self.stack.setCurrentWidget(self.prepare_widget)
```

注意：返回OCR准备时不需要重新创建 `OCRPrepareWindow`，只需要切回已有的 widget。但当前 `_on_prepare_finished` 中调用了 `self.prepare_widget.cleanup()`，可能已清理了线程资源。需要检查 `OCRPrepareWindow` 在 cleanup 后是否仍可用。

查看代码发现 `cleanup()` 只清理线程，窗口本身仍可用，所以可以直接切回。

**4b. 纵校返回横校**：在 `_on_horizontal_finished` 中连接 `back_signal`

```python
self.vert_widget.back_signal.connect(self._on_vertical_back)
```

新增 `_on_vertical_back` 方法：
```python
def _on_vertical_back(self):
    self.stack.removeWidget(self.vert_widget)
    self.vert_widget.deleteLater()
    self.current_stage = 1
    self.step_indicator.set_current(1)
    self.stack.setCurrentWidget(self.horiz_widget)
```

**4c. 精修返回纵校**：在 `_on_vertical_finished` 中连接 `back_signal`

```python
self.refine_widget.back_signal.connect(self._on_refine_back)
```

新增 `_on_refine_back` 方法：
```python
def _on_refine_back(self):
    self.stack.removeWidget(self.refine_widget)
    self.refine_widget.deleteLater()
    self.current_stage = 2
    self.step_indicator.set_current(2)
    self.stack.setCurrentWidget(self.vert_widget)
```

**4d. 修改 `_on_refine_finished`**：由于 `_on_output` 不再自动触发 `finished_signal`，`_on_refine_finished` 只由"确认完成"按钮触发，逻辑不变。

## 涉及文件汇总

| 文件 | 修改内容 |
|------|---------|
| `ui/refine_window.py` | `_on_output` 移除 `finished_signal.emit()`；新增"确认完成"按钮和 `_on_finish_confirm` 方法；新增 `back_signal` 信号和"← 返回"按钮及 `_on_back` 方法 |
| `ui/vertical_check_window.py` | 新增 `back_signal` 信号和"← 返回"按钮及 `_on_back` 方法 |
| `ui/horizontal_check_window.py` | 新增 `back_signal` 信号和"← 返回上一步"按钮及 `_on_back` 方法 |
| `main.py` | 连接三个窗口的 `back_signal`；新增 `_on_horizontal_back`、`_on_vertical_back`、`_on_refine_back` 三个回调方法 |
