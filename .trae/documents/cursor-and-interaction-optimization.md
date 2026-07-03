# 鼠标光标与交互优化 实施计划

## 问题分析

### 1. 鼠标光标问题
- 纵校和精修窗口都设置了 `QGraphicsView.DragMode.ScrollHandDrag`，导致鼠标始终显示为手型
- 用户期望：默认状态为普通指针，只有按住鼠标拖拽时才临时变为手型（Acrobat 行为）

### 2. 按钮按下状态视觉反馈
- "拖拽"和"新增文字"按钮已设置 `setCheckable(True)`，但样式表缺少 `:checked` 伪状态样式
- 按下后视觉上没有明显区分，看不出按钮处于激活状态

### 3. 拖拽模式下点击空白处取消选中
- 当前拖拽模式下选中一个文字后，点击空白处不会取消选中（框不消失）
- 应学习 Acrobat：点击空白处取消当前选中项

---

## 实施步骤

### Step 1: 修改样式表 - 添加 checked 按钮样式

**文件**: `ui/styles.py`

在 `QToolBar QPushButton:pressed` 样式块之后添加：

```css
QToolBar QPushButton:checked {
    background-color: #0D6EFD;
    color: white;
    border-color: #0a58ca;
}
```

这样当拖拽/新增文字按钮被按下（checked）时，会显示蓝色高亮背景+白色文字，明显区分激活状态。

### Step 2: 修改精修窗口 - 光标与交互优化

**文件**: `ui/refine_window.py`

#### 2.1 修改 QGraphicsView 的拖拽模式
- 默认模式：`QGraphicsView.DragMode.NoDrag`，鼠标为普通指针
- 拖拽工具激活：`NoDrag`，鼠标仍为普通指针（因为要点击选中文字）
- 新增文字工具激活：`NoDrag`，鼠标设为十字光标 `Qt.CursorShape.CrossCursor`
- 滚轮缩放/滚动条仍然正常工作

#### 2.2 添加"手型工具"按钮
- 在工具栏中添加"手型工具"按钮（checkable），用于平移页面
- 激活时：`DragMode.ScrollHandDrag`，鼠标为手型
- 与拖拽/新增文字互斥

#### 2.3 点击空白处取消选中
- 在 `_init_ui` 中给 view 的 viewport 安装 eventFilter
- eventFilter 处理鼠标按下事件：
  - 如果点击位置没有 MovableTextItem，则取消所有 MovableTextItem 的选中状态

#### 2.4 工具切换逻辑更新
- `_on_drag_toggle`：激活时设置 view 的 DragMode 为 NoDrag，光标为 ArrowCursor
- `_on_add_text_toggle`：激活时设置 view 的 DragMode 为 NoDrag，光标为 CrossCursor；取消时恢复 ArrowCursor
- 新增 `_on_hand_tool_toggle`：激活时设置 DragMode 为 ScrollHandDrag；取消时恢复 NoDrag + ArrowCursor
- 三个工具互斥：激活一个自动取消其他两个

### Step 3: 修改纵校窗口 - 光标优化

**文件**: `ui/vertical_check_window.py`

- 将 `QGraphicsView.DragMode.ScrollHandDrag` 改为 `QGraphicsView.DragMode.NoDrag`
- 添加"手型工具"按钮（checkable），用于平移页面
- 默认鼠标为普通指针
- 手型工具激活时才显示手型光标并可拖拽平移页面
- 滚轮缩放仍然正常工作

---

## 依赖关系
- Step 1（样式）独立
- Step 2（精修）和 Step 3（纵校）可并行
