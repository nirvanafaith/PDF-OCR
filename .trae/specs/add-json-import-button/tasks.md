# Tasks

- [x] Task 1: 在 DrawBoxWindow 工具栏中添加"录入JSON"按钮
  - [x] SubTask 1.1: 在 `_init_ui` 方法中，在"选择PDF"按钮后添加"录入JSON"按钮
  - [x] SubTask 1.2: 连接按钮点击信号到 `_on_import_json` 方法
- [x] Task 2: 实现 JSON 文件解析与框数据导入逻辑
  - [x] SubTask 2.1: 实现 `_on_import_json` 方法，包含文件选择对话框
  - [x] SubTask 2.2: 实现 JSON 解析逻辑，提取 `pdf_info` → `para_blocks` 中 `type == "text"` 的 `bbox`
  - [x] SubTask 2.3: 按 `page_idx` 将 bbox 添加到 `self.boxes`，与已有框合并
  - [x] SubTask 2.4: 处理边界情况（未加载PDF、JSON格式错误、页码越界）
- [x] Task 3: 验证导入功能
  - [x] SubTask 3.1: 使用示例 JSON 文件测试导入，确认框正确显示在对应页面上
  - [x] SubTask 3.2: 验证导入的框可被右键删除
  - [x] SubTask 3.3: 验证导入框与手动绘制框可共存

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
