# 精修窗口新增右键删除、红色文字覆盖、双文件输出计划

## 需求分析

用户提出三个关联需求：

1. **右键删除**：在精修窗口中，右键一个被拖拽的单字弹出删除按钮，按下后该单字消失
2. **红色文字覆盖**：精修界面上覆盖的单字颜色改为红色
3. **双文件输出**：点击输出后生成两个PDF文件——一个覆盖文字为红色（文件名含"红"），另一个覆盖文字为透明（文件名含"透明"）

## 现状分析

### 右键删除
- `MovableTextItem.contextMenuEvent` 已实现右键菜单（修改文字+删除），但由于 `RefineWindow` 的 `view` 设置了 `CustomContextMenu` 策略，右键事件被 `RefineWindow._on_context_menu` 拦截，而该方法在检测到点击的是 `MovableTextItem` 时直接 `return`，导致 `MovableTextItem` 自身的 `contextMenuEvent` 永远不会被触发
- **需要修复**：在 `_on_context_menu` 中，当拖拽模式下右键点击 `MovableTextItem` 时，弹出修改/删除菜单

### 文字颜色
- `MovableTextItem.__init__` 中 `self._text_item.setDefaultTextColor(Qt.GlobalColor.black)` 设置为黑色
- **需要修改**：改为红色 `Qt.GlobalColor.red`

### 双文件输出
- 当前 `_on_output` 只生成一个PDF文件，`PDFOutputGenerator.generate` 中文字颜色硬编码为黑色 `c.setFillColorRGB(0, 0, 0)`
- **需要修改**：
  - `PDFOutputGenerator.generate` 增加 `text_color` 参数
  - `_on_output` 基于用户选择的路径生成两个文件：`{base}_红.pdf` 和 `{base}_透明.pdf`
  - `MainWindow._on_refine_save` 需要处理双文件输出逻辑

## 实施步骤

### 步骤1：修改 `ui/refine_window.py` — 文字颜色改为红色

**文件**：`ui/refine_window.py`
**位置**：`MovableTextItem.__init__` 第82行

将：
```python
self._text_item.setDefaultTextColor(Qt.GlobalColor.black)
```
改为：
```python
self._text_item.setDefaultTextColor(Qt.GlobalColor.red)
```

### 步骤2：修改 `ui/refine_window.py` — 右键菜单支持删除

**文件**：`ui/refine_window.py`
**位置**：`RefineWindow._on_context_menu` 方法

当前逻辑：检测到 `MovableTextItem` 时直接 `return`，不做任何处理。

修改为：在拖拽模式下，右键点击 `MovableTextItem` 时弹出上下文菜单，提供"修改文字"和"删除"选项：
- "修改文字"：调用该 `MovableTextItem` 的 `_edit_text()` 方法
- "删除"：将该字符标记为 `ignored=True` 并隐藏图元

具体改动：
```python
def _on_context_menu(self, pos):
    scene_pos = self.view.mapToScene(pos)
    item = self.scene.itemAt(scene_pos, self.view.transform())
    if isinstance(item, QGraphicsTextItem) and isinstance(item.parentItem(), MovableTextItem):
        item = item.parentItem()
    if isinstance(item, MovableTextItem):
        if self._drag_mode:
            menu = QMenu(self)
            modify_action = menu.addAction("修改文字")
            delete_action = menu.addAction("删除")
            chosen = menu.exec(self.view.mapToGlobal(pos))
            if chosen == modify_action:
                item._edit_text()
            elif chosen == delete_action:
                item._data.ignored = True
                item.setVisible(False)
                item.setSelected(False)
                self._selected_item = None
        return
    if self._add_text_mode:
        menu = QMenu(self)
        add_action = menu.addAction("添加文字")
        chosen = menu.exec(self.view.mapToGlobal(pos))
        if chosen == add_action:
            self._add_text_at(scene_pos)
```

### 步骤3：修改 `pdf_processor/pdf_output.py` — 支持文字颜色参数

**文件**：`pdf_processor/pdf_output.py`
**位置**：`PDFOutputGenerator.generate` 方法

增加 `text_color` 参数，支持以下值：
- `"red"`：红色文字 `c.setFillColorRGB(1, 0, 0)`
- `"transparent"`：透明文字，使用 reportlab 的 `Color(0, 0, 0, alpha=0)` 实现
- 默认 `"red"`（与精修界面红色显示一致）

具体改动：
```python
from reportlab.lib.colors import Color

def generate(self, corrected_chars, page_images, output_path,
             pdf_path=None, text_color="red"):
    # ... 现有代码 ...
    # 替换 c.setFillColorRGB(0, 0, 0) 为：
    if text_color == "transparent":
        c.setFillColor(Color(0, 0, 0, alpha=0))
    else:
        c.setFillColorRGB(1, 0, 0)  # red
    c.drawString(llx, lly, char.text)
```

### 步骤4：修改 `ui/refine_window.py` — 双文件输出逻辑

**文件**：`ui/refine_window.py`
**位置**：`RefineWindow._on_output` 方法

修改输出逻辑：用户选择一个基础路径后，自动生成两个文件：
- `{base}_红.pdf`：红色文字覆盖
- `{base}_透明.pdf`：透明文字覆盖

需要修改 `save_signal` 的签名，增加 `text_color` 参数，或者改为发射两次信号。

**方案**：修改 `save_signal` 签名为 `pyqtSignal(list, list, str, str)`，增加 `text_color` 参数。在 `_on_output` 中发射两次信号。

具体改动：
```python
# 修改信号定义
save_signal = pyqtSignal(list, list, str, str)  # corrected_chars, page_images, output_path, text_color

def _on_output(self):
    self._sync_current_page()
    output_path, _ = QFileDialog.getSaveFileName(
        self, "保存文件", "", "PDF 文件 (*.pdf);;所有文件 (*)"
    )
    if not output_path:
        return
    corrected_chars = self._build_corrected_chars()

    # 生成两个文件路径
    base, ext = os.path.splitext(output_path)
    red_path = f"{base}_红{ext}"
    transparent_path = f"{base}_透明{ext}"

    self.save_signal.emit(corrected_chars, self.page_images, red_path, "red")
    self.save_signal.emit(corrected_chars, self.page_images, transparent_path, "transparent")
    self.finished_signal.emit()
```

需要在文件顶部添加 `import os`。

### 步骤5：修改 `main.py` — 处理双文件输出

**文件**：`main.py`
**位置**：`MainWindow._on_refine_save` 方法

修改回调函数签名，接收 `text_color` 参数，传递给 `PDFOutputGenerator.generate`：

```python
def _on_refine_save(self, corrected_chars, page_images, output_path, text_color):
    try:
        self.pdf_output.generate(
            corrected_chars,
            page_images,
            output_path,
            self.pdf_path,
            text_color=text_color,
        )
        color_label = "红色" if text_color == "red" else "透明"
        QMessageBox.information(
            self,
            "成功",
            f"{color_label}文字PDF已成功生成！\n保存路径：{output_path}",
        )
    except Exception as e:
        QMessageBox.critical(
            self, "错误", f"生成PDF失败：{e}"
        )
```

注意：由于 `save_signal` 会发射两次，弹窗也会出现两次。可以考虑只在第二次发射后弹窗，或者合并为一次弹窗。**优化方案**：在 `_on_output` 中先发射两次 `save_signal`，然后发射一个新的 `all_done_signal`，主窗口只在收到 `all_done_signal` 时弹一次窗。

**更简洁的方案**：将两次生成合并到一次信号中，在 `MainWindow` 中一次性生成两个文件。修改 `save_signal` 不携带 `text_color`，而是在 `MainWindow._on_refine_save` 中直接调用两次 `generate`。

最终方案：
- `save_signal` 保持 `pyqtSignal(list, list, str)` 不变
- `_on_output` 生成两个路径，分别发射两次 `save_signal`，但增加 `text_color` 参数
- 或者更好的方案：`save_signal` 改为 `pyqtSignal(list, list, str, str)`，`MainWindow` 收到后根据 `text_color` 调用 `generate`

考虑到弹窗问题，采用以下方案：
- `save_signal` 改为 `pyqtSignal(list, list, str, str)`
- `_on_output` 发射两次信号（红+透明），然后发射 `finished_signal`
- `_on_refine_save` 每次静默生成，不弹窗
- 新增一个 `output_complete_signal = pyqtSignal(str, str)` 信号，在两次生成完成后发射，携带两个文件路径
- `MainWindow` 连接 `output_complete_signal`，一次性弹出成功提示

**最终简化方案**（避免信号复杂化）：

在 `_on_output` 中不使用信号，而是直接在 `RefineWindow` 中调用 `PDFOutputGenerator`。但这违反了当前的架构设计。

**最终采用方案**：

1. `save_signal` 改为 `pyqtSignal(list, list, str, str)`，增加 `text_color`
2. `_on_output` 发射两次 `save_signal`
3. `MainWindow._on_refine_save` 每次静默生成，不弹窗
4. 新增 `output_complete_signal = pyqtSignal(str, str)` 信号，在两次生成完成后发射，携带两个文件路径
5. `MainWindow` 连接 `output_complete_signal`，一次性弹出成功提示

## 涉及文件汇总

| 文件 | 修改内容 |
|------|---------|
| `ui/refine_window.py` | 文字颜色改红、右键菜单支持删除、双文件输出逻辑、新增 `output_complete_signal` |
| `pdf_processor/pdf_output.py` | `generate` 方法增加 `text_color` 参数，支持红色和透明 |
| `main.py` | `_on_refine_save` 增加 `text_color` 参数，新增 `_on_output_complete` 处理 |
