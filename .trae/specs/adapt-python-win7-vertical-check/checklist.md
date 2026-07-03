# Checklist

## Win7 兼容性
- [x] `requirements.txt` 中所有依赖锁定到 Python 3.8 + Win7 SP1 可安装版本
- [x] `requirements.txt` 中 `paddlepaddle-gpu` 已移除(本软件不使用)
- [x] 所有 `.py` 文件中 `from PyQt6` 已替换为 `from PyQt5`
- [x] 所有 PyQt6 长形式枚举(如 `Qt.AlignmentFlag.AlignCenter`)已改为 PyQt5 短形式(如 `Qt.AlignCenter`)
- [x] `pyqtSignal`、`QThread`、`QObject` 等从 `PyQt5.QtCore` 导入
- [x] `QApplication`、`QMainWindow`、`QGraphicsView` 等从 `PyQt5.QtWidgets` 导入
- [x] `QImage`、`QPixmap`、`QPen`、`QBrush`、`QColor`、`QCursor`、`QTransform` 等从 `PyQt5.QtGui` 导入

## 纵校无边界拖拽
- [x] `PreviewGraphicsView.__init__` 设置 `sceneRect` 为大范围常量(±50000)
- [x] `PreviewGraphicsView` 持有 `_pixmap_item` 与 `_rect_item` 引用
- [x] `mouseMoveEvent` 调用 `_pixmap_item.setPos()` 平移,而非 `centerOn()`
- [x] `_rect_item` 通过 `setParentItem(_pixmap_item)` 作为子项,跟随 pixmap 一起移动
- [x] 向右拖动可让图像左边界越过视口左边界,露出灰色背景(代码逻辑验证通过,sceneRect ±50000 解除边界)
- [x] 上下方向同样无边界限制(sceneRect 同样解除上下边界)
- [x] `wheelEvent` 中 Ctrl+滚轮缩放保留可用

## 切片展示布局
- [x] `grid_container` 水平 SizePolicy 改为 `Preferred`(原为 `Expanding`)
- [x] `grid_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)` 已设置
- [x] `grid_layout.setContentsMargins(0, 0, 0, 0)` 已设置
- [x] 切片从左上角开始排列,右侧不均匀拉伸(代码逻辑验证通过)
- [x] 单行排满后正确换行(`row = page_idx // cols; col = page_idx % cols` 已正确)
- [x] 横向纵向间隙固定为 `_K_SLICE_SPACING`(8px)

## 切片图像完整放缩
- [x] `SliceItemWidget` 中 `pixmap.scaled()` 使用 `Qt.KeepAspectRatio`(非 `KeepAspectRatioByExpanding`)
- [x] `pixmap.scaled()` 使用 `Qt.SmoothTransformation`(非 `FastTransformation`)
- [x] 高瘦字符图缩放后高度填满可用高度,宽度按比例缩短(KeepAspectRatio 保证)
- [x] 宽扁字符图缩放后宽度填满可用宽度,高度按比例缩短(KeepAspectRatio 保证)
- [x] 图像不出现裁剪、不出框(KeepAspectRatio 完整装入语义保证)

## 红框严格居中
- [x] `center_on_rect` 中已移除 `abs(target_scale - current_scale) > 0.01` 阈值判断
- [x] `center_on_rect` 总是调用 `setTransform` + `centerOn(rect.center())`
- [x] `_show_line_preview` 末尾调用 `center_on_rect(rect_item.sceneBoundingRect())`
- [x] `_show_line_preview` 不再调用 `fit_to_width`(Grep 确认仅方法定义存在,无调用)
- [x] 任意拖动后点击切片,红框中心精确位于视口几何中心(center_on_rect 总是 resetTransform + centerOn)
- [x] 红框尺寸大于视口时,视图自动缩小到适配 scale,中心仍重合(target_scale = min(viewport_w/rect_w*1.4, viewport_h/rect_h*1.4))

## 启动脚本
- [x] `D:\hx\software2\run.bat` 文件存在,与 `main.py` 同级
- [x] 脚本设置 `chcp 65001` UTF-8 控制台编码
- [x] 脚本设置 `PYTHONIOENCODING=utf-8` 与 `PYTHONUTF8=1`
- [x] 脚本检测 `venv\Scripts\activate.bat` 存在则激活
- [x] 脚本启动 `python main.py`
- [x] 启动失败时 `pause` 等待按键

## 最终审校
- [x] 全部 `.py` 文件无残留 `PyQt6` 字符串(Grep 验证零匹配)
- [x] 全部枚举使用 PyQt5 短形式(Grep 验证零长形式残留)
- [x] `vertical_check_window.py` 中 `PreviewGraphicsView`、`SliceItemWidget`、`VerticalCheckWindow` 三个类逻辑自洽
- [x] `center_on_rect` 中 `rect.center()` 类型兼容 QRectF 与 QRect(L176 isinstance 判断)
- [x] `run.bat` 语法在 Win7 cmd.exe 下可执行(纯 ASCII,无 PowerShell-only 语法,无 BOM)
