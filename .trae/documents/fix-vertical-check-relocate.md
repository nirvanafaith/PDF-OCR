# 实施计划：修复纵校切片修改后不出现到新标签组的Bug

## 概述

在纵校（VerticalCheckWindow）中，右键切片修改字符后，切片没有出现在新字符标签的集合里。需要修复背后的功能逻辑。

---

## Bug分析

### 当前代码流程（`_on_relocate` 方法，第320-400行）

1. 获取当前字符 `current_char` 和其切片列表
2. 弹出对话框让用户输入新字符 `new_text`
3. 从原字符列表中移除切片：`slices.pop(slice_index)`
4. 更新切片文本：`char_slice.text = new_text`
5. 添加到新字符列表：`self.char_slices[new_text].append(char_slice)`
6. 调用 `_refresh_label_list()` 刷新标签列表
7. 尝试通过 `setCurrentItem` 选中新的字符标签

### 发现的问题

**问题1：重复信号连接（关键Bug）**

[vertical_check_window.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/ui/vertical_check_window.py#L500) 第500行：
```python
self.label_list.currentItemChanged.connect(self._on_label_selected)
```

`_refresh_label_list` 每次调用都重新连接信号，但从未先断开。这导致：
- 第1次刷新后，`_on_label_selected` 被调用2次
- 第2次刷新后，被调用3次
- 第N次刷新后，被调用N+1次

多次调用导致显示更新不可预测，可能覆盖正确的显示状态。

**问题2：显示刷新依赖信号触发**

`_on_relocate` 在 `_refresh_label_list()` 之后通过 `setCurrentItem` 间接触发显示更新。但由于问题1的重复信号连接，以及 `_refresh_label_list` 内部已经调用了 `setCurrentRow(0)`，最终的显示状态可能不是预期的 `new_text` 对应的切片。

**问题3：Pixmap缓存失效**

切片从A组移除后，A组中后续切片的索引发生变化，但缓存键仍使用旧索引，导致缓存错位。

---

## 修改方案

### 修改1：修复 `_refresh_label_list` 重复信号连接

```python
def _refresh_label_list(self):
    self.label_list.blockSignals(True)
    self.label_list.currentItemChanged.disconnect(self._on_label_selected)  # 先断开
    self.label_list.clear()

    sorted_keys = sorted(self.char_slices.keys(), key=lambda k: ord(k[0]) if k else 0)
    for char_text in sorted_keys:
        item = QListWidgetItem(char_text)
        item.setData(Qt.ItemDataRole.UserRole, char_text)
        self.label_list.addItem(item)

    self.label_list.blockSignals(False)
    self.label_list.currentItemChanged.connect(self._on_label_selected)  # 再连接

    if self.label_list.count() > 0:
        self.label_list.setCurrentRow(0)
```

### 修改2：修复 `_on_relocate` 显示刷新逻辑

在 `_refresh_label_list()` 之后，不再依赖 `setCurrentItem` 触发信号来更新显示，而是直接调用 `_update_slice_display(new_text)` 确保显示正确：

```python
self._refresh_label_list()

# 直接更新显示到新字符组，不依赖信号触发
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

### 修改3：修复 Pixmap 缓存失效

在 `_on_relocate` 中，清除受影响字符的所有缓存条目：

```python
# 清除原字符和新字符的所有缓存
keys_to_remove = [k for k in self._pixmap_cache
                  if k[0] in (current_char, new_text)]
for k in keys_to_remove:
    del self._pixmap_cache[k]
```

### 修改4：同样修复 `_on_delete_slice`

对 `_on_delete_slice` 应用相同的缓存清理和显示刷新修复。

---

## 验证步骤

1. 运行应用，进入纵校阶段
2. 在某字符标签下右键切片，修改为另一个已有字符 → 切片应从原标签消失，出现在新标签下
3. 修改为一个全新的字符 → 新标签应出现，切片在新标签下
4. 多次修改不同切片，确认每次都正确转移
5. 确认删除切片功能也正常工作
