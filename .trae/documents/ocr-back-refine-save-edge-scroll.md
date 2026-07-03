# OCR准备返回按钮、精修完成自动保存、画框边缘滚动优化计划

## 需求分析

用户提出三个需求：

1. **OCR准备页面返回按钮**：在OCR准备页面添加视觉清晰的返回按钮，点击后返回画框界面
2. **精修完成自动保存并返回画框**：点击"确认完成"后自动保存精修结果，然后导航回画框界面
3. **画框边缘智能滚动**：画框时鼠标接近视口边缘，自动向对应方向平滑滚动，速度随距离动态调整

## 现状分析

### 需求1：OCR准备返回按钮
- `OCRPrepareWindow` 当前没有返回按钮
- 需要添加 `back_signal` 信号和返回按钮
- `MainWindow` 需要连接该信号，切回画框界面
- 注意：返回画框时需要保留画框窗口的数据（已加载的PDF和已画的框），不能重新创建

**关键问题**：当前 `_on_draw_box_finished` 会创建新的 `OCRPrepareWindow`，但返回画框时画框窗口可能已被从 stack 中移除。查看代码发现 `_on_draw_box_finished` 只是添加新的 prepare_widget，draw_box_widget 仍在 stack 中但被隐藏。所以返回画框只需 `stack.setCurrentWidget(self.draw_box_widget)`。

但还有个问题：`_on_prepare_finished` 中调用了 `self.prepare_widget.cleanup()`，这会清理线程但不会删除 widget。返回画框后再次进入OCR准备时需要重新创建 `OCRPrepareWindow`。

### 需求2：精修完成自动保存
- 当前 `_on_finish_confirm` 只发射 `finished_signal`，没有自动保存
- 需要在确认完成后先自动调用保存逻辑（与"输出"按钮相同），然后返回画框
- `MainWindow._on_refine_finished` 已经清理所有窗口并重新进入画框阶段
- 需要在 `_on_finish_confirm` 中先执行保存，再发射 `finished_signal`

**方案**：在 `_on_finish_confirm` 中确认后，先调用 `_on_output` 的保存逻辑（但不弹出文件选择对话框，而是自动生成路径），然后发射 `finished_signal`。

但自动生成路径需要知道保存位置，这不太好。更好的方案是：确认完成后，如果之前已经输出过（有保存路径），则自动使用之前的路径重新保存；如果没输出过，则弹出保存对话框。

**更简洁的方案**：确认完成后，直接弹出保存对话框（与输出按钮相同逻辑），保存完成后发射 `finished_signal`。这样用户在确认完成时一次性完成保存和返回。

### 需求3：画框边缘智能滚动
- 当前 `DrawBoxWindow.eventFilter` 处理鼠标事件，但没有边缘滚动逻辑
- 需要在 `MouseMove` 事件中检测鼠标是否接近视口边缘
- 使用 `QTimer` 实现平滑滚动，滚动速度根据鼠标与边缘距离动态调整
- 边缘检测范围：50像素
- 滚动速度：距离越近越快，最大速度约 30px/100ms，最小约 5px/100ms

## 实施步骤

### 步骤1：OCR准备页面添加返回按钮

**文件**：`ui/ocr_prepare_window.py`

1. 添加 `back_signal = pyqtSignal()` 信号
2. 在 `_init_ui` 的底部布局中，在"下一步"按钮左侧添加"← 返回画框"按钮
3. 按钮样式：与现有界面风格一致，使用灰色调（`#6c757d`）区分于主操作按钮
4. 添加悬停和点击效果
5. 新增 `_on_back` 方法发射 `back_signal`

**按钮样式**：
```python
self.back_btn = QPushButton("← 返回画框")
self.back_btn.setStyleSheet(
    "QPushButton { background-color: #6c757d; color: white; "
    "min-height: 44px; min-width: 120px; padding: 10px 30px; "
    "border: none; border-radius: 6px; font-size: 14px; }"
    "QPushButton:hover { background-color: #5a6268; }"
    "QPushButton:pressed { background-color: #545b62; }"
)
self.back_btn.clicked.connect(self._on_back)
```

### 步骤2：MainWindow 处理OCR准备返回信号

**文件**：`main.py`

1. 在 `_setup_prepare_stage` 中连接 `back_signal`
2. 新增 `_on_prepare_back` 方法：切回画框窗口

```python
def _on_prepare_back(self):
    self.prepare_widget.cleanup()
    self.stack.removeWidget(self.prepare_widget)
    self.prepare_widget.deleteLater()
    self.current_stage = 0
    self.step_indicator.set_current(0)
    self.stack.setCurrentWidget(self.draw_box_widget)
```

### 步骤3：精修完成自动保存并返回画框

**文件**：`ui/refine_window.py`

修改 `_on_finish_confirm` 方法：
1. 确认后先同步当前页面数据
2. 弹出保存对话框让用户选择保存路径
3. 如果用户选择了路径，执行保存（与 `_on_output` 相同的逻辑）
4. 无论是否保存，都发射 `finished_signal` 返回画框

```python
def _on_finish_confirm(self):
    reply = QMessageBox.question(...)
    if reply == QMessageBox.StandardButton.Yes:
        self._sync_current_page()
        output_path, _ = QFileDialog.getSaveFileName(...)
        if output_path:
            corrected_chars = self._build_corrected_chars()
            base, ext = os.path.splitext(output_path)
            red_path = f"{base}_红{ext}"
            transparent_path = f"{base}_透明{ext}"
            self.save_signal.emit(corrected_chars, self.page_images, red_path, "red")
            self.save_signal.emit(corrected_chars, self.page_images, transparent_path, "transparent")
            self.output_complete_signal.emit(red_path, transparent_path)
        self.finished_signal.emit()
```

### 步骤4：画框边缘智能滚动

**文件**：`ui/draw_box_window.py`

1. 在 `__init__` 中添加滚动相关状态：
   - `self._scroll_timer = QTimer()` — 滚动定时器
   - `self._scroll_dx = 0` — 水平滚动方向和速度
   - `self._scroll_dy = 0` — 垂直滚动方向和速度
   - `self._edge_zone = 50` — 边缘检测范围（像素）

2. 在 `_init_ui` 中配置滚动定时器：
   ```python
   self._scroll_timer.setInterval(16)  # ~60fps
   self._scroll_timer.timeout.connect(self._on_scroll_tick)
   ```

3. 修改 `eventFilter` 的 `MouseMove` 分支：
   - 当 `_drawing` 为 True 时，检测鼠标是否在边缘区域
   - 计算水平和垂直方向的滚动速度
   - 如果需要滚动，启动定时器；否则停止定时器

4. 新增 `_on_scroll_tick` 方法：
   ```python
   def _on_scroll_tick(self):
       if self._scroll_dx != 0 or self._scroll_dy != 0:
           self.view.horizontalScrollBar().setValue(
               self.view.horizontalScrollBar().value() + self._scroll_dx
           )
           self.view.verticalScrollBar().setValue(
               self.view.verticalScrollBar().value() + self._scroll_dy
           )
   ```

5. 修改 `MouseButtonRelease` 分支：
   - 释放鼠标时停止滚动定时器

6. 速度计算逻辑：
   ```python
   EDGE_ZONE = 50
   MAX_SPEED = 30

   pos = event.pos()
   vx, vy = 0, 0

   # 左边缘
   if pos.x() < EDGE_ZONE:
       vx = -MAX_SPEED * (1 - pos.x() / EDGE_ZONE)
   # 右边缘
   elif pos.x() > viewport_width - EDGE_ZONE:
       vx = MAX_SPEED * (1 - (viewport_width - pos.x()) / EDGE_ZONE)

   # 上边缘
   if pos.y() < EDGE_ZONE:
       vy = -MAX_SPEED * (1 - pos.y() / EDGE_ZONE)
   # 下边缘
   elif pos.y() > viewport_height - EDGE_ZONE:
       vy = MAX_SPEED * (1 - (viewport_height - pos.y()) / EDGE_ZONE)

   self._scroll_dx = int(vx)
   self._scroll_dy = int(vy)

   if vx != 0 or vy != 0:
       self._scroll_timer.start()
   else:
       self._scroll_timer.stop()
   ```

## 涉及文件汇总

| 文件 | 修改内容 |
|------|---------|
| `ui/ocr_prepare_window.py` | 新增 `back_signal`、返回按钮、`_on_back` 方法 |
| `main.py` | 连接 `back_signal`，新增 `_on_prepare_back` 方法 |
| `ui/refine_window.py` | 修改 `_on_finish_confirm`，确认后自动保存再返回 |
| `ui/draw_box_window.py` | 新增边缘滚动定时器、速度计算、`_on_scroll_tick` 方法 |
