# Tasks

- [x] Task 1: 在DrawBoxWindow工具栏添加"导入JSON"按钮
  - [x] SubTask 1.1: 在_init_ui方法中，"选择PDF"按钮后添加"导入JSON"按钮，连接到_on_import_json方法
- [x] Task 2: 实现JSON解析和坐标转换核心逻辑
  - [x] SubTask 2.1: 新增_on_import_json方法，包含文件选择对话框、JSON解析、坐标转换、框数据合并
  - [x] SubTask 2.2: 实现PDF点坐标到图像像素坐标的转换（scale_x = rendered_width / pdf_width, scale_y = rendered_height / pdf_height）
  - [x] SubTask 2.3: 实现文本框扩展逻辑（四边各扩展2像素，参考P2X的EXPAND_BBOX_PIXELS）
  - [x] SubTask 2.4: 仅提取type为"text"的para_blocks，忽略其他类型
  - [x] SubTask 2.5: 导入框追加到self.boxes，不覆盖已有框
- [x] Task 3: 添加LazyPageLoader获取PDF原始页面尺寸的方法
  - [x] SubTask 3.1: 在LazyPageLoader中添加get_pdf_page_size方法，返回PDF页面的原始点坐标尺寸
- [x] Task 4: 导入完成后刷新显示并提示
  - [x] SubTask 4.1: 导入完成后调用_render_page刷新当前页面
  - [x] SubTask 4.2: 弹出提示框显示导入了多少个框
- [x] Task 5: 测试验证
  - [x] SubTask 5.1: 使用示例PDF和JSON文件测试导入功能
  - [x] SubTask 5.2: 验证框位置正确框住文字
  - [x] SubTask 5.3: 验证手动绘制框与导入框可以共存

# Task Dependencies
- Task 2 depends on Task 3（需要PDF原始页面尺寸做坐标转换）
- Task 4 depends on Task 2
- Task 5 depends on Task 1, Task 2, Task 3, Task 4
