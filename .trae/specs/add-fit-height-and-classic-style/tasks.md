# Tasks

- [x] Task 1: 软件1画框窗口添加"适合高度"按钮
  - [x] SubTask 1.1: 在工具栏"适合宽度"按钮后添加"适合高度"按钮
  - [x] SubTask 1.2: 实现 _on_fit_height 方法

- [x] Task 2: 软件2横校窗口添加"适合高度"按钮
  - [x] SubTask 2.1: 在工具栏"适合宽度"按钮后添加"适合高度"按钮
  - [x] SubTask 2.2: 实现 _on_fit_height 方法

- [x] Task 3: 软件2精修窗口添加"适合高度"按钮
  - [x] SubTask 3.1: 在工具栏"适合宽度"按钮后添加"适合高度"按钮
  - [x] SubTask 3.2: 实现 _on_fit_height 方法

- [x] Task 4: 修改软件1的样式为经典银灰风格
  - [x] SubTask 4.1: 重写 软件1/ui/styles.py 为经典银灰方形风格
  - [x] SubTask 4.2: 修改 软件1/main.py 的 app.setStyle 为 "Windows"

- [x] Task 5: 修改软件2的样式为经典银灰风格
  - [x] SubTask 5.1: 重写 软件2/ui/styles.py 为经典银灰方形风格
  - [x] SubTask 5.2: 修改 软件2/main.py 的 app.setStyle 为 "Windows"

- [x] Task 6: 测试验证
  - [x] SubTask 6.1: 运行软件1确认无error和warning
  - [x] SubTask 6.2: 运行软件2确认无error和warning

# Task Dependencies
- Task 1, 2, 3 are independent (can be parallelized)
- Task 4, 5 are independent (can be parallelized)
- Task 6 depends on all previous tasks
