# Tasks

- [x] Task 1: 修改纵校窗口切片显示方式 - 从跟随鼠标改为固定在行文字正上方
  - [x] 移除 ImageTooltip 浮动窗口类
  - [x] 改用 QGraphicsPixmapItem 在 scene 中显示切片，定位在行文字正上方
  - [x] 鼠标进入行时显示切片，离开时隐藏

- [x] Task 2: 新增精修窗口数据模型
  - [x] 在 data_models.py 中添加 RefineTextItem 数据类（text, bbox, page_num, font_size, ignored）

- [x] Task 3: 创建精修窗口 ui/refine_window.py
  - [x] 实现 RefineWindow 类，继承 QMainWindow
  - [x] 实现双层 PDF 显示：底层页面图像 + 上层可编辑文字项
  - [x] 实现 MovableTextItem 类：可选中、可拖动移动、四角缩放手柄
  - [x] 实现双击编辑文字功能
  - [x] 实现右键添加文字功能
  - [x] 实现翻页、缩放工具栏
  - [x] 实现"输出"按钮：生成双层 PDF 并保存

- [x] Task 4: 修改主流程 main.py
  - [x] 纵校完成后进入精修环节而非直接生成 PDF
  - [x] 精修输出后回到 OCR 准备环节（循环工作流）

- [x] Task 5: 更新 ui/__init__.py 导出
  - [x] 添加 RefineWindow 导出

# Task Dependencies
- Task 2 依赖无
- Task 3 依赖 Task 2
- Task 1 依赖无（可与 Task 2/3 并行）
- Task 4 依赖 Task 3
- Task 5 依赖 Task 3
