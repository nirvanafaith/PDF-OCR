# 切片右下角常显输入框与连锁修改功能

## 摘要

将纵校切片展示从"双击进入编辑"改造为"每个切片右下角常显输入框,点击即可修改"。修改后切片暂时不消失,点击"下一步"时根据新文字重分配到对应集合并更新 OCR JSON 数据。支持多选连锁修改:选中多个切片后修改其中一个,所有选中切片的文字同步更新。点击选中切片的输入框不丢失其他选中状态。

## 当前状态分析

[vertical_check_window.py](file:///d:/hx/software2/ui/vertical_check_window.py) 现状:

**SliceItemWidget(L180-320)**:
- 布局:`QVBoxLayout` 包含 `image_label`(80x80)+ `_char_input`(QLineEdit 80x24,默认 `setVisible(False)`)
- 编辑触发:`eventFilter` 捕获 `MouseButtonDblClick`/`F2`/`Enter` → `_start_edit()` 显示输入框、隐藏图像 → `returnPressed`/`editingFinished` → `_on_edit_finished` → `emit modifyRequested(int)`(无新文字参数)
- 信号:`clicked(int,object)`、`right_clicked(int)`、`delete_clicked(int)`、`modifyRequested(int)`

**VerticalCheckWindow**:
- `_on_slice_clicked(L589)`:Ctrl 切换选中,Shift 范围选,无修饰替换为单选
- `_on_slice_modify_requested(L796)`:接收 `modifyRequested` → 读 `widget.char_text` → `_pending_modifications[idx]=new_text` → `_apply_modify_to_selection` **立即 pop+append 移动切片**(违背"暂时不消失")
- `_apply_modify_to_selection(L814)`:`_update_ocr_results_char` + 清缓存 + `slices.pop` + `char_slices[new_text].append`
- `_flush_pending_modifications(L842)`:按 idx 降序遍历 `_pending_modifications` 调用 `_apply_modify_to_selection`
- `_on_relocate(L859)`:右键"修改字符"弹对话框,立即 `_apply_modify_to_selection`
- `_update_ocr_results_char(L1118)`:更新内存 `ocr_results` 字典中对应 char_data["char"]
- main.py 不直接写 JSON,`ocr_results` 经 `finished_signal` 传递,由后续 refine/export 阶段保存

**问题**:
1. 需双击才能编辑,不符合需求
2. 输入框默认隐藏,非"右下角常显"
3. 修改后立即移动切片,违背"暂时不消失"
4. 无连锁修改多选切片能力
5. 点击非切片区域不会清空选中

## 改造方案

仅修改 [vertical_check_window.py](file:///d:/hx/software2/ui/vertical_check_window.py) 一个文件。

### 改动 1: SliceItemWidget 常显右下角输入框

**移除 QVBoxLayout,改绝对定位**(`__init__` L195-243):
- `image_label.setGeometry(0, 0, 90, 90)` 满铺显示图像
- `_char_input.setGeometry(40, 68, 45, 18)` 右下角浮层(宽 45 高 18)
- `_char_input.setVisible(True)` 常显(原 `False`)
- `_char_input.setText(char_text)` 初始显示集合字符
- `_char_input.setAlignment(Qt.AlignRight)` 文字右对齐
- 样式改为半透明白底:`"QLineEdit { background-color: rgba(255,255,255,200); border: 1px solid #0D6EFD; border-radius: 2px; font-size: 12px; padding: 0px 2px; }"`

**移除双击/F2 触发编辑**(`eventFilter` L269-282):
- 删除 `MouseButtonDblClick` 分支
- 删除 `F2`/`Return`/`Enter` 分支
- `eventFilter` 可简化为只保留默认处理(或直接移除 eventFilter 与 installEventFilter)

**简化 `_start_edit`/`_on_edit_finished`**(L284-305):
- `_start_edit` 不再需要(输入框常显,点击即编辑)
- `_on_edit_finished`:比较 `new_text` 与 `self.char_text`,若不同则 `self.char_text = new_text; self.modifyRequested.emit(self.index, new_text)`(防重入:returnPressed 与 editingFinished 双触发时第二次 `new_text == self.char_text` 跳过)
- 不再切换 `image_label.setVisible`(图像始终可见,输入框浮层)

**信号改造**:
- `modifyRequested = pyqtSignal(int, str)`(原 `pyqtSignal(int)`,增加 new_text 参数)

**`set_char_text` 增强**(L265-267):
- 同时更新 `self._char_input.setText(text)`(用于连锁修改时同步显示)

### 改动 2: _on_slice_modify_requested 暂不移动 + 连锁

**重写 `_on_slice_modify_requested(self, slice_index, new_text)`**(L796-812):
```
def _on_slice_modify_requested(self, slice_index, new_text):
    try:
        current_char = self._current_char_text
        slices = self.char_slices.get(current_char, [])
        if slice_index < 0 or slice_index >= len(slices):
            return
        char_slice = slices[slice_index]
        # 更新 OCR results (复用修改字符的 JSON 更新逻辑)
        self._update_ocr_results_char(char_slice, new_text)
        # 记录挂起修改
        self._pending_modifications[slice_index] = new_text
        # 更新当前 widget 显示
        widget = self._current_slice_widgets.get(slice_index)
        if widget is not None:
            widget.set_char_text(new_text)
        # 连锁修改:若该切片在选中集中且选中数>1,同步所有选中切片
        if (slice_index in self._selected_indices
                and len(self._selected_indices) > 1):
            for idx in list(self._selected_indices):
                if idx == slice_index:
                    continue
                if idx < 0 or idx >= len(slices):
                    continue
                sub_slice = slices[idx]
                self._update_ocr_results_char(sub_slice, new_text)
                self._pending_modifications[idx] = new_text
                sub_widget = self._current_slice_widgets.get(idx)
                if sub_widget is not None:
                    sub_widget.set_char_text(new_text)
    except Exception:
        traceback.print_exc()
```

### 改动 3: 拆分 _apply_modify_to_selection

**提取 `_move_slice_to_new_char(self, slice_index, new_text)`**(从 `_apply_modify_to_selection` L814-840 抽取移动逻辑):
```
def _move_slice_to_new_char(self, slice_index, new_text):
    """实际移动切片到新字符集合(在 flush 时调用)。"""
    try:
        current_char = self._current_char_text
        slices = self.char_slices.get(current_char, [])
        if slice_index < 0 or slice_index >= len(slices):
            return
        char_slice = slices[slice_index]
        keys_to_remove = [k for k in self._pixmap_cache
                          if k[0] in (current_char, new_text)]
        for k in keys_to_remove:
            del self._pixmap_cache[k]
        slices.pop(slice_index)
        char_slice.text = new_text
        if new_text not in self.char_slices:
            self.char_slices[new_text] = []
        self.char_slices[new_text].append(char_slice)
        if not slices:
            del self.char_slices[current_char]
    except Exception:
        traceback.print_exc()
```

**`_flush_pending_modifications` 改用 `_move_slice_to_new_char`**(L842-849):
```
def _flush_pending_modifications(self):
    if not self._pending_modifications:
        return
    for idx in sorted(self._pending_modifications.keys(), reverse=True):
        new_text = self._pending_modifications[idx]
        self._move_slice_to_new_char(idx, new_text)
    self._pending_modifications.clear()
```

**`_apply_modify_to_selection` 保留**(供 `_on_relocate` 对话框方式立即移动使用):
- 内部改为调用 `_update_ocr_results_char` + `_move_slice_to_new_char`(原逻辑拆分)

### 改动 4: 非切片区域点击清空选中

**`eventFilter` 处理 grid_container 点击**(VerticalCheckWindow 已有 `grid_container.installEventFilter(self)` L462):
在 VerticalCheckWindow 新增 `eventFilter` 方法:
```
def eventFilter(self, obj, event):
    if obj is self.grid_container and event.type() == QEvent.MouseButtonPress:
        if event.button() == Qt.LeftButton:
            # 检查点击位置是否在任何 SliceItemWidget 内
            pos = event.pos()
            hit_widget = False
            for idx, widget in self._current_slice_widgets.items():
                if widget.geometry().contains(pos):
                    hit_widget = True
                    break
            if not hit_widget:
                self._selected_indices.clear()
                self._last_clicked_index = None
                self._refresh_slice_selection_visuals()
    return super().eventFilter(obj, event)
```

### 改动 5: 信号连接更新

`_render_current_page` 中(L782):
- `item_widget.modifyRequested.connect(self._on_slice_modify_requested)` 已连接,信号签名变化自动适配(PyQt5)

## 保留不变

- 右键菜单"修改字符"/"删除"保留(`_on_relocate`/`_on_delete_slice`)
- `_on_relocate` 对话框方式仍立即移动(作为备用快捷操作)
- Alt 框选逻辑保留
- `_on_slice_clicked` 选中逻辑保持(无修饰替换、Ctrl 切换、Shift 范围)
- `_update_ocr_results_char` 复用(满足"复用修改字符功能"的 JSON 更新)
- `setSceneRect(±50000)` 无边界拖拽保留
- 切片左上起排、完整放缩、红框居中保留

## 假设与决策

1. **输入框尺寸 45x18**:右下角浮层,较小避免大面积遮挡图像。文字右对齐符合"右下角"语义。
2. **输入框常显不隐藏**:点击即获焦点编辑,无需双击触发。editingFinished 在 Return/失焦时触发提交。
3. **连锁修改仅影响当前页可见 widget**:其他页选中切片的 ocr_results 与 pending 已更新,widget 显示在下次渲染时体现(因 SliceItemWidget 用 `self._current_char_text` 初始化,flush 后移动到新集合,切到新集合时显示新字符)。可接受。
4. **`_on_edit_finished` 防重入**:先更新 `self.char_text=new_text` 再 emit,使 editingFinished 二次触发时 `new_text==self.char_text` 跳过。
5. **不删除 `_apply_modify_to_selection`**:`_on_relocate` 对话框方式仍需立即移动,保留作为其实现。
6. **输入框遮挡图像右下角**:用户明确要求"右下角输入框",接受有限遮挡。半透明背景降低视觉干扰。
7. **json 文件更新**:复用 `_update_ocr_results_char` 更新内存 ocr_results,JSON 文件由后续 refine/export 阶段经 `finished_signal` 传递后保存(现有流程已支持)。
8. **"下一步"触发重分配**:`_on_next_step` 在最后一项时 `flush_current_pending`;非最后一项切换字符组经 `_on_label_selected` 也 flush。两种情况都满足"下一步时重分配"。

## 验证步骤

1. **语法验证**:`python -m py_compile ui\vertical_check_window.py`
2. **输入框常显验证**:启动软件进入纵校,每个切片右下角可见输入框,显示所在集合字符
3. **点击修改验证**:点击某切片右下角输入框,可输入新文字,回车后输入框显示新文字,切片不消失
4. **下一步重分配验证**:修改后点击"下一步",切片移动到新字符集合(左侧列表出现新字符项)
5. **连锁修改验证**:
   - Ctrl+点击多个切片选中
   - 点击其中一个被选中切片的输入框,输入新文字,回车
   - 所有选中切片的输入框文字同步更新
   - 选中状态保持(不高亮丢失)
6. **选中保持验证**:选中多个切片后,点击被选中切片的输入框,其他切片仍保持高亮
7. **非切片区域点击验证**:选中切片后,点击切片展示区空白处,所有高亮消失
8. **OCR JSON 更新验证**:修改后进入精修/导出,确认 OCR JSON 中对应 char 字段已更新
9. **功能回归验证**:
   - 无边界拖拽原图预览正常
   - 切片左上起排、完整放缩正常
   - 红框居中正常
   - 右键"修改字符"/"删除"菜单仍可用
   - Alt 框选正常
