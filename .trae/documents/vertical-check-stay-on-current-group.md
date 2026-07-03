# 纵校窗口删除/修改切片后停留在当前字符组

## 问题分析

当前纵校窗口中，修改字符（重定位）和删除切片操作后，界面会跳转到其他字符组：

1. **`_on_relocate`（修改字符）**：修改后跳转到新字符组（第398-404行），用户希望停留在原字符组
2. **`_on_delete_slice`（删除切片）**：删除后跳转到第0行（第443-447行），用户希望停留在当前字符组

## 修改方案

### 修改1：`_on_relocate` - 修改字符后停留在原字符组

当前代码（第395-406行）：
```python
self._refresh_label_list()

# 直接更新显示到新字符组，确保切片出现在新标签下
if new_text in self.char_slices:
    for i in range(self.label_list.count()):
        item = self.label_list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == new_text:
            self.label_list.setCurrentItem(item)
            break
    self._update_slice_display(new_text)
elif self.label_list.count() > 0:
    self.label_list.setCurrentRow(0)
```

修改为：刷新列表后，重新选中当前字符组（如果还存在），否则选中第0行：
```python
self._refresh_label_list()

# 停留在当前字符组
if current_char in self.char_slices:
    for i in range(self.label_list.count()):
        item = self.label_list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == current_char:
            self.label_list.setCurrentItem(item)
            break
    self._update_slice_display(current_char)
elif self.label_list.count() > 0:
    self.label_list.setCurrentRow(0)
```

注意：如果原字符组删除后为空被移除了，则回退到选中第0行。

### 修改2：`_on_delete_slice` - 删除切片后停留在当前字符组

当前代码（第442-447行）：
```python
self._refresh_label_list()
if self.label_list.count() > 0:
    self.label_list.setCurrentRow(0)
    current_item = self.label_list.currentItem()
    if current_item:
        self._update_slice_display(current_item.data(Qt.ItemDataRole.UserRole))
```

修改为：刷新列表后，重新选中当前字符组：
```python
self._refresh_label_list()

# 停留在当前字符组
if current_char in self.char_slices:
    for i in range(self.label_list.count()):
        item = self.label_list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == current_char:
            self.label_list.setCurrentItem(item)
            break
    self._update_slice_display(current_char)
elif self.label_list.count() > 0:
    self.label_list.setCurrentRow(0)
    current_item = self.label_list.currentItem()
    if current_item:
        self._update_slice_display(current_item.data(Qt.ItemDataRole.UserRole))
```

### 修改3：`_update_slice_display` - 不重置页码

当前 `_update_slice_display` 每次都重置 `_current_page = 0`。但在删除/修改操作后重新显示当前字符组时，应保持当前页码，避免跳回第一页。

方案：添加可选参数 `reset_page`，默认为 `True`（保持向后兼容），删除/修改操作调用时传 `False`。

```python
def _update_slice_display(self, char_text: str, reset_page: bool = True):
    self._current_char_text = char_text
    if reset_page:
        self._current_page = 0
    else:
        # 确保页码不超出范围
        slices = self.char_slices.get(char_text, [])
        total_pages = max(1, (len(slices) + self._page_size - 1) // self._page_size)
        if self._current_page >= total_pages:
            self._current_page = total_pages - 1
    self._render_current_page()
```

然后在 `_on_relocate` 和 `_on_delete_slice` 中调用 `_update_slice_display(current_char, reset_page=False)`。

### 需要修改的文件

**文件**: `软件2/ui/vertical_check_window.py`

1. `_update_slice_display` 方法：添加 `reset_page` 参数
2. `_on_relocate` 方法：修改后停留在原字符组，传 `reset_page=False`
3. `_on_delete_slice` 方法：删除后停留在当前字符组，传 `reset_page=False`

## 验证步骤

1. 运行软件2，进入纵校阶段
2. 选择一个有多个切片的字符组
3. 右键修改某个切片的字符 → 确认停留在原字符组
4. 右键删除某个切片 → 确认停留在当前字符组
5. 删除到当前字符组为空 → 确认跳转到第一个字符组
6. 在非第一页操作 → 确认页码保持不变（不跳回第一页）
