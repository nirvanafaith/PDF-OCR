# Tasks

- [x] Task 1: 项目初始化与数据模型定义
  - [x] SubTask 1.1: 创建项目目录结构和requirements.txt（surya-ocr, PyQt6, pdf2image, reportlab, Pillow）
  - [x] SubTask 1.2: 创建数据模型模块 models/data_models.py，使用dataclasses定义OCRResult、TextLine、CharSlice、CorrectedChar等核心数据结构
  - [x] SubTask 1.3: 验证数据模型可被正确导入和使用

- [x] Task 2: PDF输入与预处理模块
  - [x] SubTask 2.1: 创建 pdf_processor/pdf_loader.py，实现PDFProcessor类，提供convert_to_images(pdf_path)方法
  - [x] SubTask 2.2: 添加错误处理（文件不存在、非PDF文件、加密PDF等）
  - [x] SubTask 2.3: 验证PDF转图像功能正常工作

- [x] Task 3: OCR识别模块
  - [x] SubTask 3.1: 创建 ocr_engine/surya_engine.py，实现OCREngine类，提供recognize(images, langs)方法
  - [x] SubTask 3.2: 实现模型加载逻辑（load_det_model/load_rec_model），支持首次运行自动下载
  - [x] SubTask 3.3: 实现OCR结果解析，将行级结果拆分为字符级，按文字文本分组
  - [x] SubTask 3.4: 添加异常处理（模型加载失败、图像格式不支持等）
  - [x] SubTask 3.5: 验证OCR识别和结果解析功能

- [x] Task 4: 横校界面模块
  - [x] SubTask 4.1: 创建 ui/horizontal_check_window.py，实现HorizontalCheckWindow类（QMainWindow）
  - [x] SubTask 4.2: 实现左侧文字标签列表控件（LabelListWidget），按编码顺序排列，显示文字和出现次数
  - [x] SubTask 4.3: 实现右侧切片网格展示控件（SliceViewerWidget），网格布局展示切片图片，标注页码和坐标
  - [x] SubTask 4.4: 实现右键菜单"重定位"功能，弹出对话框输入正确文字，执行切片移动
  - [x] SubTask 4.5: 实现"下一步"按钮逻辑，切换文字标签或进入纵校
  - [x] SubTask 4.6: 实现键盘快捷键（Space选中下一个、Enter下一步、Esc关闭对话框）
  - [x] SubTask 4.7: 验证横校界面完整交互流程

- [x] Task 5: 纵校界面模块
  - [x] SubTask 5.1: 创建 ui/vertical_check_window.py，实现VerticalCheckWindow类（QMainWindow）
  - [x] SubTask 5.2: 实现主视图区，在白色背景上按坐标绘制文字层（使用QPainter或QGraphicsScene）
  - [x] SubTask 5.3: 实现翻页导航控件（上一页/下一页按钮、页码输入框）
  - [x] SubTask 5.4: 实现缩放功能（鼠标滚轮或工具栏按钮）
  - [x] SubTask 5.5: 实现悬浮提示功能，鼠标悬停显示原PDF裁剪图片
  - [x] SubTask 5.6: 实现右键菜单（修改文字、调整位置、忽略/删除）
  - [x] SubTask 5.7: 实现"完成纵校"按钮和确认对话框
  - [x] SubTask 5.8: 验证纵校界面完整交互流程

- [x] Task 6: PDF输出模块
  - [x] SubTask 6.1: 创建 pdf_processor/pdf_output.py，实现PDFOutputGenerator类
  - [x] SubTask 6.2: 实现双层PDF生成逻辑：原PDF页面图像作为背景 + reportlab Canvas绘制文字层
  - [x] SubTask 6.3: 实现坐标转换（OCR像素坐标 → reportlab坐标系，原点从左上角转左下角）
  - [x] SubTask 6.4: 实现中文字体嵌入（使用TrueType字体如微软雅黑）
  - [x] SubTask 6.5: 验证双层PDF输出正确（可搜索、可复制、视觉一致）

- [x] Task 7: 主程序入口与流程串联
  - [x] SubTask 7.1: 创建 main.py，实现程序入口，初始化各模块
  - [x] SubTask 7.2: 实现PDF文件选择对话框
  - [x] SubTask 7.3: 串联完整流程：PDF转图像 → OCR识别 → 结果解析分组 → 横校 → 纵校 → 双层PDF输出
  - [x] SubTask 7.4: 实现OCR处理进度提示
  - [x] SubTask 7.5: 验证端到端完整流程可执行

- [x] Task 8: UI样式与体验优化
  - [x] SubTask 8.1: 实现统一QSS样式表（主色调#0D6EFD，浅灰/白背景，深灰/黑文字）
  - [x] SubTask 8.2: 添加操作反馈（按钮点击高亮、加载进度提示、错误提示）
  - [x] SubTask 8.3: 验证界面风格一致性和交互流畅性

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 1, Task 3]
- [Task 5] depends on [Task 1, Task 4]
- [Task 6] depends on [Task 1, Task 5]
- [Task 7] depends on [Task 2, Task 3, Task 4, Task 5, Task 6]
- [Task 8] depends on [Task 4, Task 5]
