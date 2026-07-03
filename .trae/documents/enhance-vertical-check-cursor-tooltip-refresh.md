# 纵校原图预览交互优化计划

## 摘要

针对 `d:\hx\software2\ui\vertical_check_window.py` 的三项改进:
1. **蓝框 tooltip 立即显示**:用 `QToolTip.showText()` 替代 Qt 原生 tooltip 延迟机制,鼠标悬停蓝框时 0ms 显示对应文字
2. **红框边缘 cursor 切换 + 红框优先级**:鼠标悬停红框 8 个手柄时显示对应的 SizeFDiag/SizeBDiag/SizeHor/SizeVer 指针;悬停红框内部显示 SizeAllCursor;红框与蓝框重叠时优先红框操作
3. **切片显示立即刷新**:红框拖拽修改后,切换到同页其他切片时,被修改的切片立即重新计算图像并刷新显示(新增 `SliceItemWidget.set_pixmap` 方法,单 widget 刷新,不重建整页)

## 当前状态分析

基于代码探索(d:\hx\software2\ui\vertical_check_window.py,约 1550 行):

### Tooltip 机制(问题 1)
- 蓝框 `QGraphicsRectItem.setToolTip(char_text)`(L345)
- Qt 原生 tooltip 延迟约 700ms,用户体验"太慢"
- `mouseMoveEvent` 非拖拽分支仅调用 `super().mouseMoveEvent(event)`(L238),依赖 Qt 内建 hover 触发 tooltip
- 全文件无 `QToolTip` 引用

### Cursor 处理(问题 2)
- 仅 L172 平移开始时 `setCursor(Qt.ClosedHandCursor)`,L257 平移结束 `unsetCursor()`
- `mouseMoveEvent` 非拖拽分支**无手柄检测、无 cursor 切换**
- `_hit_red_rect_handle`(L71-112)返回 8 种手柄标识:`tl/tr/bl/br`(角) + `t/b/l/r`(边中点),仅在 `mousePressEvent`(L147)调用一次
- `mousePressEvent` 优先级链(L121-173):**蓝框高亮(L126-143) > 红框手柄(L145-154) > 红框内部(L155-165) > 平移(L167-173)**

### 切片刷新机制(问题 3)
- `_commit_pending_red_box_resize`(L1405-1455)仅更新 `char_slice.image/bbox` + 失效 `_pixmap_cache`,**不刷新任何 UI**
- `SliceItemWidget`(L389-413)仅在 `__init__` 内 `image_label.setPixmap(scaled)`,**无 `set_pixmap` 方法**
- `_current_slice_widgets`(L519, L988):`Dict[int, SliceItemWidget]`,键为 `global_idx`
- `_on_slice_clicked`(L777)和 `_preview_slice`(L813)调用 commit 后**不重建网格**,导致被修改切片的缩略图不刷新

## 提议变更

所有变更均在 `d:\hx\software2\ui\vertical_check_window.py` 单文件内。

### 变更 1:导入 QToolTip

**位置**:L3-26 `from PyQt5.QtWidgets import (...)`

**改动**:在 import 列表中添加 `QToolTip`

**原因**:`QToolTip.showText()` 是静态方法,需导入 `QToolTip` 类

### 变更 2:调整 mousePressEvent 优先级链(红框优先于蓝框)

**位置**:L121-173 `PreviewGraphicsView.mousePressEvent`

**当前优先级**:蓝框高亮 > 红框手柄 > 红框内部 > 平移

**调整后优先级**:红框手柄 > 红框内部 > 蓝框高亮 > 平移

**实现**:把 L145-165 的红框检测块(优先级 2+3)移到 L126 之前(蓝框检测之前)。具体顺序:
1. 红框边角手柄检测(`_hit_red_rect_handle` 命中 → 进入 `_resizing`,记录 handle/start_rect/start_pos,`event.accept(); return`)
2. 红框内部检测(`view_poly.boundingRect().contains(event.pos())` → `_red_rect_selected=True`,高亮 pen #ff0000 3px,`event.accept(); return`)
3. 蓝框高亮(勾选 `_overlay_interaction_enabled` 时,`scene().itemAt(scene_pos)` 命中且 `data(UserRole)` 非 None → 高亮橙色 #ff9500 2px,重置上一个高亮为蓝色,`event.accept(); return`)
4. 平移(兜底)

**原因**:用户明确要求"鼠标在红框和其他框重叠区域时,优先红框操作"

### 变更 3:重写 mouseMoveEvent 非拖拽分支(添加 cursor 切换 + 立即 tooltip)

**位置**:L175-238 `PreviewGraphicsView.mouseMoveEvent`,重点修改 L237-238 的 `else` 分支

**实现**(替换原 `else: super().mouseMoveEvent(event)`):

```python
else:
    # 非拖拽状态:检测红框手柄/内部、设置 cursor、显示蓝框 tooltip
    handle = None
    in_red = False
    if self._rect_item is not None:
        handle = self._hit_red_rect_handle(event.pos())
        if handle is None:
            view_poly = self.mapFromScene(self._rect_item.sceneBoundingRect())
            if view_poly.boundingRect().contains(event.pos()):
                in_red = True

    # cursor 切换(8 手柄 + 内部 + 默认)
    if handle in ("tl", "br"):
        self.setCursor(QCursor(Qt.SizeFDiagCursor))
    elif handle in ("tr", "bl"):
        self.setCursor(QCursor(Qt.SizeBDiagCursor))
    elif handle in ("l", "r"):
        self.setCursor(QCursor(Qt.SizeHorCursor))
    elif handle in ("t", "b"):
        self.setCursor(QCursor(Qt.SizeVerCursor))
    elif in_red:
        self.setCursor(QCursor(Qt.SizeAllCursor))
    else:
        self.unsetCursor()

    # 蓝框 tooltip 立即显示(仅当不在红框上,且勾选了"显示其他字框")
    if (handle is None and not in_red
            and self._overlay_interaction_enabled
            and self.scene() is not None):
        scene_pos = self.mapToScene(event.pos())
        item = self.scene().itemAt(scene_pos, self.transform())
        if item is not None and item.data(Qt.UserRole) is not None:
            QToolTip.showText(event.globalPos(), str(item.data(Qt.UserRole)))

    super().mouseMoveEvent(event)
```

**手柄→cursor 映射表**:

| handle | 位置 | cursor 形状 |
|--------|------|------------|
| `tl`/`br` | 主对角(左上↔右下) | `SizeFDiagCursor` (↘) |
| `tr`/`bl` | 副对角(右上↔左下) | `SizeBDiagCursor` (↙) |
| `l`/`r` | 水平边 | `SizeHorCursor` (↔) |
| `t`/`b` | 垂直边 | `SizeVerCursor` (↕) |
| 红框内部 | 非边缘 | `SizeAllCursor` (移动) |
| 其他 | 框外 | `ArrowCursor`(`unsetCursor`) |

**原因**:
- cursor 切换提供视觉反馈,用户能直观判断手柄位置和拖拽方向
- `QToolTip.showText()` 绕过 Qt 原生 tooltip 的 ~700ms 延迟,实现立即显示
- 红框优先:不在红框上时才检测蓝框 tooltip,避免红框操作被蓝框 tooltip 干扰
- 末尾保留 `super().mouseMoveEvent(event)` 维持 Qt 内建 hover 行为(setToolTip 作为兜底)

### 变更 4:mouseReleaseEvent 中清理 cursor(平移结束时)

**位置**:L255-260 `mouseReleaseEvent`

**当前实现**:L257 平移结束时 `self.unsetCursor()`

**改动**:无需修改。`unsetCursor()` 恢复默认箭头,与新逻辑一致。

### 变更 5:SliceItemWidget 新增 set_pixmap 方法

**位置**:L389-455 `SliceItemWidget` 类,在 `set_char_text` 方法(L452-455)之后添加

**实现**:

```python
def set_pixmap(self, pixmap: QPixmap):
    """更新切片显示的图像(用于红框调整后刷新单个切片)。"""
    if pixmap.isNull():
        self.image_label.setText("(无)")
    else:
        scaled = pixmap.scaled(
            80, 80,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
        self.image_label.setText("")  # 清除可能残留的"(无)"
```

**原因**:当前 `SliceItemWidget` 构造后无法更新 pixmap。新增此方法支持单 widget 刷新,避免重建整页网格的闪烁和开销。复用 `__init__` 中的缩放参数(80x80, KeepAspectRatio, SmoothTransformation)保持视觉一致。

### 变更 6:VerticalCheckWindow 新增 _refresh_slice_widget 方法

**位置**:在 `_commit_pending_red_box_resize`(L1405)方法之前添加

**实现**:

```python
def _refresh_slice_widget(self, idx: int):
    """刷新指定索引切片的缩略图显示(若该切片在当前页可见)。

    用于红框拖拽提交后,立即更新网格中对应 widget 的图像,
    避免用户切页或切字符组才能看到新切片。
    """
    widget = self._current_slice_widgets.get(idx)
    if widget is None:
        return  # 切片不在当前页,无需刷新
    slices = self.char_slices.get(self._current_char_text, [])
    if idx < 0 or idx >= len(slices):
        return
    char_slice = slices[idx]
    pixmap = self._pil_to_pixmap(char_slice.image) if char_slice.image else QPixmap()
    widget.set_pixmap(pixmap)
    # 重新填充缓存,避免下次 _render_current_page 重复计算
    cache_key = (self._current_char_text, idx)
    self._pixmap_cache[cache_key] = pixmap
    self._pixmap_cache.move_to_end(cache_key)
    if len(self._pixmap_cache) > self._max_cache_size:
        self._pixmap_cache.popitem(last=False)
```

**原因**:
- 检查 `idx` 是否在 `_current_slice_widgets` 中(即是否在当前显示页可见),不可见则跳过
- 从 `char_slice.image` 重新生成 pixmap(此时 image 已被 `_commit_pending_red_box_resize` 更新)
- 调用 `widget.set_pixmap(pixmap)` 单 widget 刷新
- 重新填充 `_pixmap_cache`,避免 `_render_current_page` 重复执行 `_pil_to_pixmap`(PIL→QPixmap 转换有开销)

### 变更 7:_commit_pending_red_box_resize 末尾调用切片刷新

**位置**:L1405-1455 `_commit_pending_red_box_resize`,在 L1454-1455 清空 dirty 之前添加刷新调用

**当前末尾**:
```python
        # 失效该切片的 pixmap 缓存,使下次渲染重新加载
        cache_key = (self._current_char_text, idx)
        self._pixmap_cache.pop(cache_key, None)
        # 清除脏状态,避免重复提交
        view._resized_dirty = False
        view._resized_rect = None
```

**改为**:
```python
        # 失效该切片的 pixmap 缓存,使下次渲染重新加载
        cache_key = (self._current_char_text, idx)
        self._pixmap_cache.pop(cache_key, None)
        # 立即刷新该切片的网格缩略图显示(若在当前页可见)
        self._refresh_slice_widget(idx)
        # 清除脏状态,避免重复提交
        view._resized_dirty = False
        view._resized_rect = None
```

**原因**:
- `_commit_pending_red_box_resize` 已在 7 个焦点切换入口被调用(L721/781/816/1219/1510/1519/1536)
- `_on_slice_clicked`(L781)和 `_preview_slice`(L816)路径下,网格不重建,需显式刷新被修改切片的 widget
- 其他路径(切字符组/翻页/上下一步)会重建网格,刷新调用是冗余但无害(widget 即将被 deleteLater,刷新它不影响正确性)
- 放在 `pop cache` 之后、`清空 dirty` 之前,确保 `_refresh_slice_widget` 能拿到最新的 `char_slice.image`

## 假设与决策

1. **Tooltip 方案**:采用 `QToolTip.showText()` 立即显示,保留 `setToolTip` 作为兜底(键盘导航等场景)。`QToolTip.showText` 在同一位置显示新文本时会更新现有 tooltip,不会重复弹出。
2. **Cursor 方案**:在 `mouseMoveEvent` 非拖拽分支检测手柄并 `setCursor`。`setCursor` 作用于 `QGraphicsView` 的 viewport,影响整个视图区域。8 个手柄对应 4 种 cursor 形状(对角×2、水平、垂直)+ 红框内部 `SizeAllCursor`。
3. **优先级调整**:从"蓝框 > 红框"改为"红框 > 蓝框"。这是行为变更,但符合用户明确要求。实际场景中红框(当前字)与蓝框(同行其他字)bbox 通常不重叠,影响极小。
4. **切片刷新方案**:新增 `SliceItemWidget.set_pixmap` 方法 + `_refresh_slice_widget` 辅助方法,单 widget 刷新。比重建整页(`_render_current_page`)高效且无闪烁。
5. **缓存一致性**:`_refresh_slice_widget` 重新生成 pixmap 并填回 `_pixmap_cache`,与 `_render_current_page` 的缓存逻辑(L965-973)保持一致,避免下次渲染重复计算。
6. **不修改 `mouseReleaseEvent`**:平移结束的 `unsetCursor()` 与新逻辑兼容(下次 `mouseMoveEvent` 会重新设置 cursor)。
7. **`super().mouseMoveEvent(event)` 保留**:即使增加了 cursor 和 tooltip 逻辑,仍调用父类实现维持 Qt 内建 hover 事件链(`setToolTip` 兜底、`QGraphicsScene` hover 事件等)。
8. **性能考量**:`mouseMoveEvent` 每次移动都执行 `_hit_red_rect_handle`(8 次坐标比较)+ 可能的 `scene().itemAt`(蓝框检测)。开销很小(微秒级),不影响交互流畅度。

## 验证步骤

1. **语法验证**:`python -m py_compile ui\vertical_check_window.py` 退出码 0
2. **Grep 确认关键符号**:
   - `QToolTip` 已导入并使用
   - `set_pixmap` 方法已定义
   - `_refresh_slice_widget` 方法已定义
   - `SizeFDiagCursor`/`SizeBDiagCursor`/`SizeHorCursor`/`SizeVerCursor`/`SizeAllCursor` 均已使用
3. **Grep 确认优先级调整**:mousePressEvent 中红框检测块在蓝框检测块之前
4. **Grep 确认刷新调用**:`_commit_pending_red_box_resize` 末尾调用 `_refresh_slice_widget(idx)`
5. **context7 复查**:
   - `QToolTip.showText(QPoint, str, QWidget=None)` 静态方法签名正确
   - `Qt.SizeFDiagCursor` 等 CursorShape 枚举值存在
   - `QGraphicsView.setCursor` / `unsetCursor` 继承自 `QWidget`
6. **逻辑通读**:
   - mouseMoveEvent 非拖拽分支:手柄检测 → cursor 设置 → 蓝框 tooltip(仅非红框区域)→ super 调用
   - mousePressEvent:红框手柄 → 红框内部 → 蓝框高亮 → 平移
   - _commit_pending_red_box_resize:重算 image → 失效缓存 → 刷新 widget → 清空 dirty
   - _refresh_slice_widget:检查可见性 → 生成 pixmap → set_pixmap → 回填缓存

## 影响范围

- **修改文件**:`d:\hx\software2\ui\vertical_check_window.py`(单文件)
- **影响功能**:纵校窗口原图预览的蓝框 tooltip、红框 cursor 反馈、红框/蓝框优先级、切片缩略图刷新
- **不影响**:横校、导入、OCR 引擎、数据模型等其他模块
- **向后兼容**:是。新增方法不影响现有 API;优先级调整是行为优化,不破坏数据完整性
