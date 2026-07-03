# 修复纵校原图预览框过大并实现固定比例布局

## 问题摘要

上次纵校改造后,原图预览框高度过大,挤压切片展示区域。用户要求:
1. 修复预览框过大问题,确保大小正常
2. 原图预览与切片展示保持固定比例
3. 窗口拉伸时比例保持不变

## 根因分析(systematic-debugging Phase 1)

### 布局结构
[vertical_check_window.py](file:///d:/hx/software2/ui/vertical_check_window.py) `_init_ui` 中:
- `right_column_layout = QVBoxLayout()` 包含两个 QGroupBox
- `preview_group`(原图预览) — `addWidget(preview_group)` stretch=0
- `right_group`(切片展示) — `addWidget(right_group, 1)` stretch=1

`preview_group` 内部:
- `preview_stack`(QStackedWidget)SizePolicy=(Expanding, Fixed)
- `preview_view`(PreviewGraphicsView)SizePolicy=(Expanding, Fixed) + `setFixedHeight(240)`

### 根因
`preview_view.setFixedHeight(240)`(line 427)设置 `minimumHeight = maximumHeight = 240`,导致 `preview_group` 的最小高度固定为 ~260px(240 + margins 8 + title 12)。

在 `right_column_layout` 中 `preview_group` stretch=0,占其 minimumSize(260px);`right_group` stretch=1,占剩余空间。

- 窗口高 500px:预览 260px(52%),切片 240px(48%)→ 预览"非常大",挤压切片
- 窗口高 800px:预览 260px(33%),切片 540px(67%)→ 比例不固定
- 窗口高 1000px:预览 260px(26%),切片 740px(74%)→ 比例仍不固定

这违反用户"固定比例"需求。`setFixedHeight(240)` 使预览高度不随窗口变化,无法保持比例。

### 排除的其他假设
- `setSceneRect(±50000)`:QGraphicsView 未重写 sizeHint()/minimumSizeHint(),使用 QAbstractScrollArea 默认实现(基于 viewport,默认 (0,0)),不受 sceneRect 影响。保留不影响布局。
- `grid_container` SizePolicy 改为 (Preferred, Preferred):只影响水平方向(左上起排),不影响垂直布局。保留。
- PyQt5 vs PyQt6 枚举差异:已正确迁移,无影响。

## 修复方案

### 修改文件
仅修改 [vertical_check_window.py](file:///d:/hx/software2/ui/vertical_check_window.py) 的 `_init_ui` 方法。

### 具体改动

**1. 移除固定高度(line 427)**
```python
# 删除:
self.preview_view.setFixedHeight(240)
```

**2. preview_view SizePolicy 垂直改 Expanding(lines 423-426)**
```python
# 修改前:
self.preview_view.setSizePolicy(
    QSizePolicy.Expanding,
    QSizePolicy.Fixed,
)
# 修改后:
self.preview_view.setSizePolicy(
    QSizePolicy.Expanding,
    QSizePolicy.Expanding,
)
self.preview_view.setMinimumHeight(150)  # 避免预览过小
```

**3. preview_stack SizePolicy 垂直改 Expanding(lines 406-409)**
```python
# 修改前:
self.preview_stack.setSizePolicy(
    QSizePolicy.Expanding,
    QSizePolicy.Fixed,
)
# 修改后:
self.preview_stack.setSizePolicy(
    QSizePolicy.Expanding,
    QSizePolicy.Expanding,
)
```

**4. right_column_layout 设置 stretch 比例 3:7(line 436, 494)**
```python
# line 436 修改前:
right_column_layout.addWidget(preview_group)
# 修改后:
right_column_layout.addWidget(preview_group, 3)

# line 494 修改前:
right_column_layout.addWidget(right_group, 1)
# 修改后:
right_column_layout.addWidget(right_group, 7)
```

### 保留不变(上次正确修改)
- `setSceneRect(QRectF(-50000, -50000, 100000, 100000))` — 无边界拖拽所需
- `grid_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)` — 左上起排所需
- `SliceItemWidget` 中 `Qt.KeepAspectRatio` + `Qt.SmoothTransformation` — 完整放缩所需
- `center_on_rect` 无 0.01 阈值 — 红框居中所需

## 预期效果

| 窗口高度 | 预览高度 | 切片高度 | 比例 |
|---------|---------|---------|------|
| 500px | 150px(minHeight 限制) | 350px | 3:7 |
| 800px | 240px | 560px | 3:7 |
| 1000px | 300px | 700px | 3:7 |
| 1200px | 360px | 840px | 3:7 |

- 预览:切片始终 3:7 固定比例
- 窗口拉伸时比例保持
- 预览最小 150px,避免内容不可见
- 无边界拖拽、左上起排、完整放缩、红框居中均不受影响

## 假设与决策

1. **比例选择 3:7**:基于原 `setFixedHeight(240)` 在 800px 窗口下占 30% 的历史行为,选择 3:7 保持视觉一致性。如用户偏好不同比例,可调整 stretch 值(如 2:8 或 1:3)。
2. **minimumHeight(150)**:防止窗口极小时预览区无法显示红框。150px 足以显示一行切片的红框居中预览。
3. **不恢复 grid_container 为 Expanding**:上次改为 Preferred 是为切片左上起排,与本次修复无关,保留。
4. **不删除 setSceneRect(±50000)**:无边界拖拽所必需,且不影响布局(已分析排除)。

## 验证步骤

1. **语法验证**:`python -m py_compile ui\vertical_check_window.py`
2. **布局验证**:启动软件,观察预览框高度约占窗口 30%,切片展示约占 70%
3. **比例保持验证**:拉伸窗口,确认预览:切片始终 3:7
4. **功能回归验证**:
   - 点击切片,红框严格居中
   - 拖动原图,无边界限制(可露出灰底)
   - 切片展示从左上起排,固定间隙
   - 切片图像完整放缩,不裁剪
5. **极小窗口验证**:窗口缩到最小,预览不低于 150px
