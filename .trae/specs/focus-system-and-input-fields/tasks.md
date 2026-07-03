# Tasks

- [x] Task 1: 软件1画框窗口焦点系统
  - [x] SubTask 1.1: 添加 _selected_box_index 实例变量
  - [x] SubTask 1.2: 修改 _render_page 选中框用粗红边框
  - [x] SubTask 1.3: 修改 eventFilter 点击框时选中而非画新框
  - [x] SubTask 1.4: 添加 keyPressEvent 处理 Delete 键删除选中框
  - [x] SubTask 1.5: 翻页时重置 _selected_box_index

- [x] Task 2: 软件1画框窗口页码和缩放输入框
  - [x] SubTask 2.1: 替换 page_label 为 page_input (QLineEdit) + page_total_label
  - [x] SubTask 2.2: 替换 zoom_label 为 zoom_input (QLineEdit)
  - [x] SubTask 2.3: 添加 _on_page_input 和 _on_zoom_input 方法
  - [x] SubTask 2.4: 修改 _render_page 更新输入框值

- [x] Task 3: 软件2横校窗口缩放输入框
  - [x] SubTask 3.1: 替换 zoom_label 为 zoom_input (QLineEdit)
  - [x] SubTask 3.2: 添加 _on_zoom_input 方法
  - [x] SubTask 3.3: 修改 _render_page 更新 zoom_input

- [x] Task 4: 软件2精修窗口缩放输入框
  - [x] SubTask 4.1: 替换 zoom_label 为 zoom_input (QLineEdit)
  - [x] SubTask 4.2: 添加 _on_zoom_input 方法
  - [x] SubTask 4.3: 修改 _render_page 更新 zoom_input

- [x] Task 5: 测试验证
  - [x] SubTask 5.1: 运行软件1确认无error和warning
  - [x] SubTask 5.2: 运行软件2确认无error和warning

# Task Dependencies
- Task 1, 2 can be done together (same file)
- Task 3, 4 are independent
- Task 5 depends on all previous tasks
