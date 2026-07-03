# Python 软件 Win7 适配与纵校改造 Spec

## Why
当前 `D:\hx\software2` 基于 PyQt6 + Python 3.12,无法在 Windows 7 上运行(PyQt6 强制要求 Win10+,Python 3.9+ 也已放弃 Win7)。同时纵校窗口的原图预览存在拖拽边界限制、切片展示布局错位、切片图像被裁剪而非完整放缩、点击切片后红框未严格居中四类体验问题,需统一改造。

## What Changes
- **Win7 适配** **BREAKING**: 全量从 PyQt6 迁移到 PyQt5(枚举短形式、`pyqtSignal` 类型签名、`QGraphicsView`/`QGraphicsScene` API);锁定依赖版本至 Python 3.8 + Win7 兼容组合;清理 `requirements.txt` 中未使用的 `paddlepaddle-gpu`。
- **纵校原图预览无边界拖拽**: 重构 `PreviewGraphicsView`,放弃受 `sceneRect` 约束的 `centerOn()` 平移;改为以 `QGraphicsPixmapItem` 作为根项,`QGraphicsRectItem` 作为其子项,鼠标拖拽通过 `pixmap_item.moveBy()` 平移整个组;`sceneRect` 扩展为大范围以解除边界限制,使图像可被任意拖出预览框露出灰色背景。
- **切片展示左上起排、固定间隙**: 修改 `grid_container` 的 `SizePolicy` 与 `grid_layout` 的 `Alignment`,确保从左上角开始、行优先排列,横向纵向间隙固定为 `_K_SLICE_SPACING`,不被均匀拉伸。
- **切片图像完整放缩**: `SliceItemWidget` 中将 `KeepAspectRatioByExpanding` 改为 `KeepAspectRatio`,并将 `FastTransformation` 改为 `SmoothTransformation`,使每个字符切片图按比例完整装入小框且放缩到最大尺寸不出框。
- **红框严格居中**: 重写 `center_on_rect` 与 `_show_line_preview` 的居中逻辑:同时按宽高计算适配 scale,移除 0.01 差异阈值,每次都调用 `setTransform` + `centerOn(rect.center())`,确保点击切片后红框中心与视口中心严格重合。
- **启动脚本**: 在 `main.py` 同级目录新增 `run.bat`,设置 UTF-8 编码、可选激活虚拟环境、启动 `python main.py`,Win7 cmd.exe 直接可执行。

## Impact
- Affected specs: 无(本项目此前无 Python Win7 适配 spec)
- Affected code:
  - `D:\hx\software2\requirements.txt` — 依赖锁版与清理
  - `D:\hx\software2\main.py` — PyQt6 → PyQt5
  - `D:\hx\software2\ui\import_window.py` — PyQt6 → PyQt5
  - `D:\hx\software2\ui\vertical_check_window.py` — PyQt6 → PyQt5 + 纵校四项核心改造
  - `D:\hx\software2\ui\horizontal_check_window.py` — PyQt6 → PyQt5
  - `D:\hx\software2\ui\refine_window.py` — PyQt6 → PyQt5
  - `D:\hx\software2\ui\styles.py` — 文档字符串提及 PyQt6,改为 PyQt5
  - `D:\hx\software2\ui\zoom_utils.py` — PyQt6 → PyQt5
  - `D:\hx\software2\pdf_processor\pdf_output.py` — `QThread`/`pyqtSignal` 来源 PyQt6 → PyQt5
  - `D:\hx\software2\run.bat` — 新增启动脚本

## ADDED Requirements

### Requirement: Win7 兼容运行环境
系统 SHALL 在 Windows 7 SP1 + Python 3.8.x 环境下完整启动并运行四阶段(导入/纵校/横校/精修)流程,所有依赖 SHALL 锁定到该环境可安装的版本。

#### Scenario: 全模块导入
- **WHEN** 执行 `python -c "import main"` (或 `python main.py`)
- **THEN** 不出现 `ImportError`、`AttributeError` 等异常,GUI 主窗口正常显示

#### Scenario: 依赖安装
- **WHEN** 在 Python 3.8 + Win7 SP1 环境执行 `pip install -r requirements.txt`
- **THEN** 所有依赖成功安装,不出现版本冲突或预编译 wheel 缺失

### Requirement: 纵校原图预览无边界拖拽
原图预览视图 SHALL 支持鼠标左键按住后向任意方向无限拖动行切片图像,拖动行为不受图像边界、视口边界、sceneRect 边界限制;拖动后图像可在视口任意一侧露出灰色预览框底色。

#### Scenario: 向右拖到露出左侧灰底
- **WHEN** 用户按住鼠标左键向右拖动原图
- **THEN** 图像继续向右移动,图像左边界可越过视口左边界,左侧露出预览框灰色背景,不被任何边界停止

#### Scenario: 上下方向同样无边界
- **WHEN** 用户向上或向下拖动图像
- **THEN** 图像可移出视口上下边界,露出灰底,行为与左右一致

### Requirement: 切片展示左上起排固定间隙
切片展示区 SHALL 从左上角开始,按从左到右、单行排满后下一行的顺序排列切片;横向与纵向切片间隙 SHALL 固定为 `_K_SLICE_SPACING`(8px),不随容器宽度变化被拉伸。

#### Scenario: 容器宽度大于内容总宽度
- **WHEN** 视口宽度大于所有切片+间隙的总宽度
- **THEN** 切片仍从左上角紧密排列,右侧剩余空间留白,不被均匀拉开

#### Scenario: 单行排满后换行
- **WHEN** 当行已排满 `_current_columns` 个切片,继续添加切片
- **THEN** 新切片从下一行第一列开始排列

### Requirement: 切片图像完整放缩装入小框
每个字符切片图 SHALL 按原始宽高比完整装入 `SliceItemWidget` 的图像显示区,不裁剪、不出框,并在不违反前两条前提下放缩到最大尺寸;放缩 SHALL 使用平滑插值保证视觉质量。

#### Scenario: 高瘦字符图
- **WHEN** 切片原图高度远大于宽度
- **THEN** 缩放后高度填满可用高度,宽度按比例缩短并居中显示,左右留白

#### Scenario: 宽扁字符图
- **WHEN** 切片原图宽度远大于高度
- **THEN** 缩放后宽度填满可用宽度,高度按比例缩短并居中显示,上下留白

### Requirement: 点击切片红框严格居中
用户每次点击切片进行原图预览时,系统 SHALL 保证红框中心点与原图预览视口中心点严格重合,无论图像当前是否已被拖动到偏移位置;居中 SHALL 同时考虑视口宽高,不依赖差异阈值跳过缩放调整。

#### Scenario: 任意拖动后点击切片
- **WHEN** 用户先拖动原图到任意偏移位置,然后点击切片
- **THEN** 视图变换被重置为适配 scale,红框中心精确位于视口几何中心

#### Scenario: 红框尺寸大于视口
- **WHEN** 红框尺寸大于视口尺寸
- **THEN** 视图缩小到红框能装入视口的 scale,红框中心仍与视口中心重合

### Requirement: Win7 启动脚本
`D:\hx\software2\run.bat` SHALL 作为 Windows 7 兼容启动入口,位于 `main.py` 同级目录,设置 UTF-8 控制台编码,自动激活同级虚拟环境(若存在),传递必要环境变量,启动 `python main.py`。

#### Scenario: 存在虚拟环境
- **WHEN** `D:\hx\software2\venv\Scripts\activate.bat` 存在
- **THEN** 脚本调用 `venv\Scripts\activate.bat` 激活,然后运行 `python main.py`

#### Scenario: 不存在虚拟环境
- **WHEN** 虚拟环境目录不存在
- **THEN** 脚本直接使用系统 `python` 运行 `main.py`,不报错

#### Scenario: 启动失败保留窗口
- **WHEN** `python main.py` 异常退出(非零退出码)
- **THEN** 脚本 `pause` 等待按键,让用户看到错误信息

## MODIFIED Requirements

### Requirement: 纵校窗口 PyQt5 兼容
纵校窗口及其子组件 SHALL 使用 PyQt5 API,所有枚举 SHALL 使用短形式(`Qt.AlignCenter`、`Qt.LeftButton`、`Qt.UserRole`、`QGraphicsView.AnchorViewCenter`、`Qt.ScrollBarAlwaysOff`、`Qt.KeepAspectRatio`、`Qt.SmoothTransformation` 等),不再使用 PyQt6 的长形式枚举。

### Requirement: `PreviewGraphicsView` 拖拽实现
`PreviewGraphicsView` SHALL 改用 `QGraphicsPixmapItem.moveBy()` 实现拖拽,红框 `QGraphicsRectItem` SHALL 作为 pixmap item 的子项以同步移动;`sceneRect` SHALL 设为大范围常量(±50000)以解除 `centerOn` 边界约束;`center_on_rect` SHALL 总是重置 transform 并调用 `centerOn` 实现严格居中。
