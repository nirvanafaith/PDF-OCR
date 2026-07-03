# 精修环节单字化改进与横校删除功能 实施计划

## 问题分析

### 精修环节当前问题
1. **按行显示**：当前以 `CorrectedLine`（整行）为单位显示文字，无法精确到单字定位
2. **字体大小不精确**：使用 `QFont("Microsoft YaHei", int(font_size))` 设置的是点大小而非像素大小，无法与原字完美覆盖
3. **交互模式不合理**：所有文字项默认可拖拽，没有工具模式切换
4. **缺少模式化操作**：拖拽和新增文字应该是工具栏按钮激活后才可用

### 横校环节当前问题
1. **右键菜单只有修改**：`SliceItemWidget._show_context_menu` 只提供"修改字符"选项，缺少删除功能

---

## 实施步骤

### Step 1: 修改横校窗口 - 添加删除功能

**文件**: `ui/horizontal_check_window.py`

1. 在 `SliceItemWidget` 类中：
   - 添加 `delete_clicked = pyqtSignal(int)` 信号
   - 修改 `_show_context_menu`：在"修改字符"下方添加"删除"选项
   - "删除"触发时 emit `delete_clicked` 信号

2. 在 `HorizontalCheckWindow` 类中：
   - 在 `_update_slice_display` 中连接 `item_widget.delete_clicked` 到新方法 `_on_delete_slice`
   - 新增 `_on_delete_slice(self, slice_index: int)` 方法：
     - 获取当前字符和对应的 CharSlice
     - 调用 `_update_ocr_results_char` 将该字符的 char 设为空字符串（标记删除）
     - 从 `self.char_slices[current_char]` 中移除该 slice
     - 如果该字符列表为空，删除整个 key
     - 刷新显示

### Step 2: 重写精修窗口 - 单字嵌入 + 工具模式

**文件**: `ui/refine_window.py`

#### 2.1 数据源变更
- 构造函数改为接收 `page_lines: dict`（LineSlice 字典）而非 `corrected_lines: list`
- `_convert_lines` 改为 `_convert_chars`：遍历每个 `LineSlice`，从 `ls.chars` 提取单字数据
  - 跳过 `ls._ignored == True` 的行
  - 每个 char dict `{"text": "字", "bbox": [x1,y1,x2,y2]}` 转换为 `RefineTextItem`
  - font_size = bbox[3] - bbox[1]（精确像素高度）

#### 2.2 MovableTextItem 改进
- **字体精确匹配**：使用 `font.setPixelSize(int(h))` 代替 `QFont("Microsoft YaHei", int(font_size))`
  - `setPixelSize` 直接设置像素高度，确保字体与 bbox 高度一致
- **默认不可交互**：移除默认的 `ItemIsMovable` 和 `ItemIsSelectable` 标志
- **新增 activate/deactivate 方法**：
  - `activate()`: 设置 ItemIsMovable，接受悬停事件
  - `deactivate()`: 移除 ItemIsMovable，隐藏选中框和手柄，取消选中
- **双击显示框**：仅在 activate 状态下，双击显示蓝色虚线边框 + 四角手柄
- **Delete 键删除**：不在 MovableTextItem 内处理，由 RefineWindow 统一处理
- **右键菜单**：仅在 activate 状态下响应，包含"修改文字"和"删除"选项
- **文字定位微调**：`_text_item.setPos(0, 0)` 并调整使文字垂直居中于 rect

#### 2.3 RefineWindow 工具栏改造
- 新增工具栏按钮（在翻页/缩放按钮之后，输出按钮之前）：
  - **"拖拽"按钮**：`QPushButton` + `setCheckable(True)`，toggle 模式
  - **"新增文字"按钮**：`QPushButton` + `setCheckable(True)`，toggle 模式
- **互斥逻辑**：
  - 点击"拖拽"：如果"新增文字"已激活则先取消，再切换拖拽状态
  - 点击"新增文字"：如果"拖拽"已激活则先取消，再切换新增文字状态
  - 取消拖拽时：deactivate 所有 MovableTextItem，隐藏所有框
- **拖拽模式激活时**：
  - 所有 MovableTextItem 调用 `activate()`
  - 双击字符显示框（选中状态）
  - 可拖拽移动、拖拽手柄缩放
  - Delete 键删除选中项
  - 右键菜单：修改文字 / 删除
- **新增文字模式激活时**：
  - MovableTextItem 保持不可交互
  - 右键点击 PDF 空白处弹出输入对话框（只输入一个字符）
  - 确认后在点击位置创建新字符，默认字体大小取当前页平均字符高度

#### 2.4 键盘事件处理
- 重写 `keyPressEvent`：
  - Delete 键：删除当前选中的 MovableTextItem（标记 ignored=True 并隐藏）
  - 其他键传递给父类

#### 2.5 右键菜单调整
- 拖拽模式下：点击 MovableTextItem 显示"修改文字"/"删除"菜单
- 新增文字模式下：点击空白处显示"添加文字"菜单
- 默认模式下：无右键菜单

#### 2.6 输出数据变更
- `_build_corrected_chars()` 方法：遍历所有页面的 RefineTextItem，生成 `CorrectedChar` 列表
- `save_signal` 改为 `pyqtSignal(list, list, str)`（CorrectedChar 列表，page_images，output_path）

### Step 3: 修改主流程 main.py

**文件**: `main.py`

1. `_on_vertical_check_finished`：
   - 从 `self.vertical_window.page_lines` 获取 page_lines
   - 传递 `page_lines` 给 RefineWindow 而非 `corrected_lines`

2. `_on_refine_save`：
   - 参数从 `corrected_lines` 改为 `corrected_chars`
   - 传递 `corrected_chars` 给 `pdf_output.generate()`

### Step 4: 修改 PDF 输出 - 支持单字绘制

**文件**: `pdf_processor/pdf_output.py`

1. `generate` 方法参数从 `corrected_lines` 改为 `corrected_chars`
2. 遍历 `corrected_chars`，每个字符单独绘制：
   - 使用字符的 bbox 定位
   - font_size = y2 - y1（像素高度）
   - `c.drawString(llx, lly, char.text)` 绘制单个字符

### Step 5: 验证

- 运行 `python main.py` 确认无导入错误
- 测试横校右键删除功能
- 测试精修窗口单字显示和工具模式切换

---

## 依赖关系
- Step 1（横校）和 Step 2（精修）可并行
- Step 3 依赖 Step 2（RefineWindow 接口变更）
- Step 4 依赖 Step 2（输出数据格式变更）
- Step 5 依赖所有步骤完成
