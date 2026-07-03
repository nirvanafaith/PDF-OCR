# Tasks

- [x] Task 1: 将 OCRPrepareWindow 从 QMainWindow 改为 QWidget
  - [x] 将类继承从 QMainWindow 改为 QWidget
  - [x] 将 setCentralWidget 改为直接设置布局
  - [x] 将 setWindowTitle 移除（由 MainWindow 统一管理）
  - [x] 保留 finished_signal 和所有业务逻辑不变

- [x] Task 2: 将 HorizontalCheckWindow 从 QMainWindow 改为 QWidget
  - [x] 将类继承从 QMainWindow 改为 QWidget
  - [x] 将 setCentralWidget 改为直接设置布局
  - [x] 保留 finished_signal 和所有业务逻辑不变

- [x] Task 3: 将 VerticalCheckWindow 从 QMainWindow 改为 QWidget
  - [x] 将类继承从 QMainWindow 改为 QWidget
  - [x] 将 addToolBar(toolbar) 改为布局内嵌 toolbar
  - [x] 将 setCentralWidget(self.view) 改为布局内嵌
  - [x] 添加首次渲染自动适合宽度逻辑

- [x] Task 4: 将 RefineWindow 从 QMainWindow 改为 QWidget
  - [x] 将类继承从 QMainWindow 改为 QWidget
  - [x] 将 addToolBar(toolbar) 改为布局内嵌 toolbar
  - [x] 将 setCentralWidget(self.view) 改为布局内嵌
  - [x] 添加首次渲染自动适合宽度逻辑

- [x] Task 5: 重写 MainWindow 使用 QStackedWidget
  - [x] 添加进度条组件（4步骤标签+高亮）
  - [x] 使用 QStackedWidget 管理四个阶段页面
  - [x] 阶段切换时更新进度条和 QStackedWidget 当前页
  - [x] 精修完成后重置回 OCR 准备阶段

# Task Dependencies
- Task 5 depends on Task 1, 2, 3, 4
- Task 1, 2, 3, 4 can run in parallel
