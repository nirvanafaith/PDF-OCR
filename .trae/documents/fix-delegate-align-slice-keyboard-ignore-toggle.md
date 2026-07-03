# 纵校委托对齐修复 + 切片方向键失灵修复 + 横校忽略切换

## 摘要

3 项需求：
1. **纵校已检查条目文字居左** — `CharListDelegate.paint()` 用 `Qt.AlignCenter` 导致文字居中，改为左对齐 + padding 匹配 QSS。
2. **纵校切片方向键失灵修复** — 手动点击切片后焦点在 `SliceItemWidget`，方向键被 `QAbstractScrollArea.keyPressEvent` 消费用于视口滚动，不到 `VerticalCheckWindow.keyPressEvent`。新增 `SliceItemWidget.keyPressEvent` 将按键交给父窗口处理。
3. **横校忽略切换** — 右键已忽略的行时，菜单按钮改为"取消忽略"，点击后恢复。

---

## 当前状态分析

### Task 1 根因

[CharListDelegate.paint L567-585](file:///d:/hx/software2/ui/vertical_check_window.py#L567-L585) 在已检查分支用 `Qt.AlignCenter` 绘制文字（L581），导致浅蓝条目文字居中。QSS `::item` 规则（[styles.py L45-48](file:///d:/hx/software2/ui/styles.py#L45-L48) `padding: 8px 12px`）对应默认左对齐 + padding，委托自绘需手动加 padding 才能匹配。

### Task 2 根因（已用 sequentialthinking + context7 确认）

事件传播链：
1. [SliceItemWidget L439](file:///d:/hx/software2/ui/vertical_check_window.py#L439) `setFocusPolicy(Qt.StrongFocus)` — 点击切片后获得焦点
2. 方向键事件发给 SliceItemWidget，它未重写 keyPressEvent，调用 QWidget 默认实现（对方向键 `ignore()`）
3. 事件沿父链传播：`SliceItemWidget → grid_container → scroll_content → viewport → scroll_area`
4. `QAbstractScrollArea.keyPressEvent`（context7 确认存在）消费方向键用于视口滚动，`accept` 事件
5. 事件不再传播到 `VerticalCheckWindow.keyPressEvent`，导航失灵

这解释了"刚进入集合时可用"（焦点在 label_list，NoArrowListWidget `ignore` 后直接传播到 VerticalCheckWindow）和"点击切片后失灵"（焦点在 SliceItemWidget，方向键被 scroll_area 消费）。

### Task 3 现状

[horizontal_check_window.py L672-709 _on_context_menu](file:///d:/hx/software2/ui/horizontal_check_window.py#L672-L709)：
- L696 `ignore_action = menu.addAction("忽略/删除")` — 固定文字，不区分已忽略/未忽略
- L802-822 `_on_ignore_line` — 仅设置 `ls._ignored = True`，无切换逻辑
- L349/373/395 根据 `_ignored` 显示灰色文字

---

## 提议修改

### 修改 1：CharListDelegate.paint 文字左对齐（Task 1）

**文件**：[vertical_check_window.py](file:///d:/hx/software2/ui/vertical_check_window.py)
**位置**：[L574-582](file:///d:/hx/software2/ui/vertical_check_window.py#L574-L582) 已检查分支

**当前代码**：
```python
        elif checked:
            # 已检查(非选中): 自绘浅蓝底色 + 黑字，绕过 QSS
            painter.save()
            painter.fillRect(option.rect, QColor("#b3d9ff"))
            painter.setPen(QColor("black"))
            painter.setFont(option.font)
            text = index.data(Qt.DisplayRole)
            painter.drawText(option.rect, Qt.AlignCenter, text)
            painter.restore()
```

**替换为**：
```python
        elif checked:
            # 已检查(非选中): 自绘浅蓝底色 + 黑字左对齐，绕过 QSS
            # 左右各 12px padding 匹配 QSS ::item { padding: 8px 12px }
            painter.save()
            painter.fillRect(option.rect, QColor("#b3d9ff"))
            painter.setPen(QColor("black"))
            painter.setFont(option.font)
            text = index.data(Qt.DisplayRole)
            text_rect = option.rect.adjusted(12, 0, -12, 0)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.restore()
```

**原因**：
- `Qt.AlignLeft | Qt.AlignVCenter` 左对齐 + 垂直居中，匹配 QListWidget 默认外观
- `option.rect.adjusted(12, 0, -12, 0)` 模拟 QSS `padding: 8px 12px` 的左右 12px padding
- 上下 padding 由 `Qt.AlignVCenter` 自动处理（垂直居中）

### 修改 2：SliceItemWidget 新增 keyPressEvent（Task 2）

**文件**：[vertical_check_window.py](file:///d:/hx/software2/ui/vertical_check_window.py)
**位置**：[SliceItemWidget 类 L415-536](file:///d:/hx/software2/ui/vertical_check_window.py#L415-L536)，在 `mousePressEvent` 之后新增方法

**新增代码**（放在 `mousePressEvent` 方法之后，`_show_context_menu` 之前）：
```python
    def keyPressEvent(self, event):
        """将按键事件交给父窗口处理，阻止 scroll_area 消费方向键。

        SliceItemWidget 获得焦点后，方向键事件默认会传播到 scroll_area，
        被 QAbstractScrollArea.keyPressEvent 消费用于视口滚动，导致
        VerticalCheckWindow.keyPressEvent 收不到方向键导航切片。
        本方法将所有按键事件交给父窗口（VerticalCheckWindow）处理。
        """
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, '_navigate_selection'):
                event.accept()
                parent.keyPressEvent(event)
                return
            parent = parent.parent()
        super().keyPressEvent(event)
```

**原因**：
- `event.accept()` 阻止事件默认传播到 scroll_area（避免被消费用于滚动）
- 向上遍历父链找到 `VerticalCheckWindow`（通过 `hasattr(parent, '_navigate_selection')` 检测，避免硬编码类名）
- 调用 `parent.keyPressEvent(event)` 交给父窗口处理（方向键导航切片、Ctrl+方向键跳转字符集合、空格下一步、删除等）
- 如果找不到父窗口（理论上不会），`super().keyPressEvent(event)` 兜底
- 不影响 `_char_input` (QLineEdit) 的按键处理（焦点在 QLineEdit 时，按键事件直接给 QLineEdit，不经过 SliceItemWidget.keyPressEvent）

**副作用分析**：
- 焦点在 SliceItemWidget 时，所有按键（方向键、空格、删除、Escape 等）都交给父窗口处理
- 父窗口 keyPressEvent 不处理的按键会 `super().keyPressEvent(event)`（VerticalCheckWindow 父类），无副作用
- _char_input 编辑时焦点在 QLineEdit，按键不经过 SliceItemWidget.keyPressEvent，正常编辑

### 修改 3：横校右键菜单忽略切换（Task 3）

**文件**：[horizontal_check_window.py](file:///d:/hx/software2/ui/horizontal_check_window.py)

#### 3a. `_on_context_menu` 菜单文字根据忽略状态切换

**位置**：[L695-697](file:///d:/hx/software2/ui/horizontal_check_window.py#L695-L697)

**当前代码**：
```python
            modify_action = menu.addAction("修改文字")
            ignore_action = menu.addAction("忽略/删除")
            relocate_action = menu.addAction("重新定位行框")
```

**替换为**：
```python
            modify_action = menu.addAction("修改文字")
            ls = item.data(1)
            is_ignored = ls is not None and hasattr(ls, "_ignored") and ls._ignored
            ignore_action = menu.addAction("取消忽略" if is_ignored else "忽略/删除")
            relocate_action = menu.addAction("重新定位行框")
```

**原因**：检查 item 关联的 LineSlice 的 `_ignored` 属性，已忽略显示"取消忽略"，未忽略显示"忽略/删除"。

#### 3b. `_on_ignore_line` 改为切换逻辑

**位置**：[L802-822](file:///d:/hx/software2/ui/horizontal_check_window.py#L802-L822)

**当前代码**：
```python
    def _on_ignore_line(self, item: QGraphicsTextItem):
        """将指定行切片标记为忽略状态，并在界面上以灰色显示。

        被 _on_context_menu 调用。设置行切片的 _ignored 属性为 True，
        将文本颜色改为灰色以示区分，并记录忽略操作。

        参数:
            item (QGraphicsTextItem): 被右键点击的文本图元，
                其 data(1) 存储了关联的 LineSlice 对象。

        依赖:
            - models.data_models.LineSlice: 行切片数据模型
        """
        ls = item.data(1)
        if ls is None:
            return
        ls._ignored = True
        self._render_page()
        self.modifications.append(
            {"type": "ignore", "text": ls.text, "details": "ignored"}
        )
```

**替换为**：
```python
    def _on_ignore_line(self, item: QGraphicsTextItem):
        """切换指定行切片的忽略状态，并在界面上以灰色/正常显示。

        被 _on_context_menu 调用。切换行切片的 _ignored 属性，
        将文本颜色改为灰色(忽略)或黑色(恢复)以示区分，并记录操作。

        参数:
            item (QGraphicsTextItem): 被右键点击的文本图元，
                其 data(1) 存储了关联的 LineSlice 对象。

        依赖:
            - models.data_models.LineSlice: 行切片数据模型
        """
        ls = item.data(1)
        if ls is None:
            return
        if hasattr(ls, "_ignored") and ls._ignored:
            # 已忽略: 取消忽略
            ls._ignored = False
            self._render_page()
            self.modifications.append(
                {"type": "unignore", "text": ls.text, "details": "unignored"}
            )
        else:
            # 未忽略: 标记为忽略
            ls._ignored = True
            self._render_page()
            self.modifications.append(
                {"type": "ignore", "text": ls.text, "details": "ignored"}
            )
```

**原因**：
- 检查当前 `_ignored` 状态，True → 设为 False（取消忽略），False → 设为 True（忽略）
- `modifications` 记录 `type: "unignore"` 用于取消忽略操作统计
- `_render_page()` 会根据 `_ignored` 切换文字颜色（L349/373/395 已有逻辑）

#### 3c. 完成统计兼容取消忽略

**位置**：[_on_finish L1129-1152](file:///d:/hx/software2/ui/horizontal_check_window.py#L1129-L1152) 完成统计

需确认 `ignore_count` 统计是否需要调整。当前 L1143-1144：
```python
ignore_count = sum(
    1 for m in self.modifications if m["type"] == "ignore"
)
```

**决策**：保持不变。`ignore_count` 统计 `type == "ignore"` 的操作数。取消忽略记录为 `type == "unignore"`，不计入 ignore_count。这会导致：忽略后取消，ignore_count 仍为 1（净忽略数为 0）。但用户看到的是操作次数，不是净忽略数，可接受。

**不修改 L1143-1152**，保持现有统计逻辑。

---

## 假设与决策

1. **Task 1 padding 值**：QSS `::item { padding: 8px 12px }`（[styles.py L46](file:///d:/hx/software2/ui/styles.py#L46)），左右 12px。委托自绘用 `option.rect.adjusted(12, 0, -12, 0)` 模拟。上下 padding 由 `Qt.AlignVCenter` 自动处理。

2. **Task 2 父窗口检测**：用 `hasattr(parent, '_navigate_selection')` 检测 VerticalCheckWindow，避免硬编码类名和循环引用。VerticalCheckWindow 有 `_navigate_selection` 方法（[L1663](file:///d:/hx/software2/ui/vertical_check_window.py#L1663)），唯一匹配。

3. **Task 2 event.accept()**：先 `event.accept()` 阻止默认传播（避免 scroll_area 消费），再手动调用父窗口 keyPressEvent。父窗口 keyPressEvent 内部会根据按键类型处理或 `super().keyPressEvent(event)`。

4. **Task 2 _char_input 不受影响**：QLineEdit 有自己的 keyPressEvent，焦点在 QLineEdit 时按键直接给 QLineEdit，不经过 SliceItemWidget.keyPressEvent。

5. **Task 3 菜单文字**：已忽略显示"取消忽略"，未忽略显示"忽略/删除"（保留原文案，仅切换）。

6. **Task 3 统计不调整**：`ignore_count` 统计 `type == "ignore"` 的操作次数，取消忽略记为 `type == "unignore"` 不计入。用户看到操作次数而非净忽略数，可接受。

7. **Task 3 CorrectedLine.ignored**：[L1214](file:///d:/hx/software2/ui/horizontal_check_window.py#L1214) `ignored = hasattr(ls, "_ignored") and ls._ignored` 已根据最终状态导出，取消忽略后 `ls._ignored = False`，导出 `ignored=False`。无需修改。

---

## 验证步骤

1. `python -m py_compile ui\vertical_check_window.py` 语法检查通过
2. `python -m py_compile ui\horizontal_check_window.py` 语法检查通过
3. `Grep "AlignCenter"` 确认 CharListDelegate 已无 AlignCenter（SliceItemWidget 的 image_label 仍有，正常）
4. `Grep "AlignLeft"` 确认委托使用 AlignLeft
5. `Grep "def keyPressEvent"` 在 SliceItemWidget 中确认新增方法
6. `Grep "取消忽略"` 确认横校菜单文字切换
7. `Grep "unignore"` 确认取消忽略操作记录
8. context7 MCP 验证 QStyledItemDelegate.paint 和 QWidget.keyPressEvent 用法
9. sequentialthinking 深度分析每个修改的副作用（实现时执行）
10. 逻辑审查：确认方向键不被 scroll_area 消费、忽略切换逻辑正确

---

## 实现顺序

1. sequentialthinking 分析 Task 1 对齐修复的 padding 匹配
2. 执行修改 1（CharListDelegate.paint AlignLeft + padding）
3. context7 验证 QWidget.keyPressEvent 和事件传播
4. sequentialthinking 分析 Task 2 SliceItemWidget.keyPressEvent 副作用
5. 执行修改 2（SliceItemWidget 新增 keyPressEvent）
6. 执行修改 3a（_on_context_menu 菜单文字切换）
7. 执行修改 3b（_on_ignore_line 切换逻辑）
8. py_compile + Grep 验证全部修改
