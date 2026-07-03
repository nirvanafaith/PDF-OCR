# 实施计划：Footer框绘制 + 横校/纵校名词互换

## 概述

两个独立任务：
1. 在JSON导入环节，将 `type="footer"` 的块也画出来
2. 将软件中全部的"横校"和"纵校"名词互换

---

## 任务1：Footer框绘制

### 当前状态
- [draw_box_window.py](file:///c:/Users/E-VR/Documents/trae_projects/横校/ui/draw_box_window.py#L46) 第46行定义了白名单：
  ```python
  TEXT_BLOCK_TYPES = {"text", "title", "interline_equation"}
  ```
- "footer" 不在白名单中，导致导入JSON时footer类型的块被跳过不绘制

### 修改方案
- **文件**: `ui/draw_box_window.py`
- **修改**: 第46行，将 `"footer"` 加入 `TEXT_BLOCK_TYPES` 集合
  ```python
  TEXT_BLOCK_TYPES = {"text", "title", "interline_equation", "footer"}
  ```

---

## 任务2：横校/纵校名词互换

### 当前状态
- **横校**（HorizontalCheckWindow）：字符归类校对，按字符分组展示切片图像
- **纵校**（VerticalCheckWindow）：文本定位校正，逐页展示行切片文本与原图叠加

### 互换原则
- 横校 → 纵校，纵校 → 横校（中文名互换）
- HorizontalCheckWindow ↔ VerticalCheckWindow（类名互换）
- horizontal_check_window ↔ vertical_check_window（文件名互换）
- HorizontalCheckData ↔ VerticalCheckData（数据模型名互换）
- horiz_widget ↔ vert_widget（变量名互换）
- _on_horizontal_finished ↔ _on_vertical_finished（方法名互换）
- _on_horizontal_back ↔ _on_vertical_back（方法名互换）

### 修改文件清单

#### 1. `ui/horizontal_check_window.py` → 重命名为 `ui/vertical_check_window.py`
- 类名 `HorizontalCheckWindow` → `VerticalCheckWindow`
- 类名 `CharSliceWidget` 保持不变（内部组件，不涉及横纵命名）
- 所有注释/文档字符串中的 "横校" → "纵校"
- 内部子类 `CharSliceWidget` 的文档字符串中 "横校" → "纵校"

#### 2. `ui/vertical_check_window.py` → 重命名为 `ui/horizontal_check_window.py`
- 类名 `VerticalCheckWindow` → `HorizontalCheckWindow`
- 所有注释/文档字符串中的 "纵校" → "横校"
- 按钮文本 `"完成纵校"` → `"完成横校"`
- 对话框标题 `"确认完成纵校"` → `"确认完成横校"`

#### 3. `main.py`
- 第31行：`from ui.horizontal_check_window import HorizontalCheckWindow` → `from ui.vertical_check_window import VerticalCheckWindow`
- 第32行：`from ui.vertical_check_window import VerticalCheckWindow` → `from ui.horizontal_check_window import HorizontalCheckWindow`
- 第55行：注释中 横校↔纵校
- 第194行：注释中 横校↔纵校
- 第206-207行：注释中 HorizontalCheckWindow↔VerticalCheckWindow，横校↔纵校
- 第212行：`STAGES = ["画框", "OCR准备", "横校", "纵校", "精修"]` → `STAGES = ["画框", "OCR准备", "纵校", "横校", "精修"]`
- 第332行：注释 横校→纵校
- 第342-343行：注释互换
- 第352行：`self.horiz_widget = HorizontalCheckWindow(...)` → `self.vert_widget = VerticalCheckWindow(...)`
- 第355-356行：信号连接方法名互换
- 第361行：`_on_horizontal_finished` → `_on_vertical_finished`
- 第363-368行：注释互换
- 第371行：注释互换
- 第374-375行：注释互换
- 第384行：`self.vert_widget = VerticalCheckWindow(...)` → `self.horiz_widget = HorizontalCheckWindow(...)`
- 第387-388行：信号连接方法名互换
- 第393行：`_on_vertical_finished` → `_on_horizontal_finished`
- 第398行：注释 纵校→横校
- 第401行：注释互换
- 第451行：`_on_horizontal_back` → `_on_vertical_back`
- 第452-457行：注释互换
- 第465行：`_on_vertical_back` → `_on_horizontal_back`
- 第468行：注释互换
- 第471行：注释互换
- 第482行：注释 纵校→横校

#### 4. `ui/__init__.py`
- 第1行：`from .horizontal_check_window import HorizontalCheckWindow` → `from .vertical_check_window import VerticalCheckWindow`
- 第2行：`from .vertical_check_window import VerticalCheckWindow` → `from .horizontal_check_window import HorizontalCheckWindow`

#### 5. `models/data_models.py`
- 第150行：`class HorizontalCheckData` → `class VerticalCheckData`
- 第151行：注释 "横校" → "纵校"
- 第163行：`class VerticalCheckData` → `class HorizontalCheckData`
- 第164行：注释 "纵校" → "横校"

#### 6. `ui/styles.py`
- 第3行：注释 "横校" → "纵校"
- 第4行：注释 "横校" → "纵校"，"竖校" → "横校"
- 第20行：注释 "横校" → "纵校"
- 第27行：注释 `HorizontalCheckWindow` ↔ `VerticalCheckWindow`
- 第28行：注释 `VerticalCheckWindow` ↔ `HorizontalCheckWindow`

#### 7. `ui/ocr_prepare_window.py`
- 第178-179行：注释 "横校" → "纵校"
- 第234行：注释 "横校" → "纵校"
- 第622行：注释 "横校" → "纵校"
- 第631行：注释 "横校" → "纵校"
- 第640行：`self._append_output("准备进入横校...")` → `self._append_output("准备进入纵校...")`

#### 8. `ocr_engine/rapidocr_engine.py`
- 第427行：注释 "横校" → "纵校"

### 文件重命名步骤

由于两个文件名需要互换，使用临时文件名避免冲突：
1. `horizontal_check_window.py` → `_temp_swap.py`
2. `vertical_check_window.py` → `horizontal_check_window.py`
3. `_temp_swap.py` → `vertical_check_window.py`

---

## 实施顺序

1. **任务1**：修改 `draw_box_window.py` 第46行，添加 "footer"
2. **任务2**：
   a. 修改 `ui/horizontal_check_window.py` 内容（类名、注释）
   b. 修改 `ui/vertical_check_window.py` 内容（类名、注释、按钮文本）
   c. 重命名两个文件
   d. 修改 `main.py`（导入、STAGES、变量名、方法名、注释）
   e. 修改 `ui/__init__.py`（导入）
   f. 修改 `models/data_models.py`（类名、注释）
   g. 修改 `ui/styles.py`（注释）
   h. 修改 `ui/ocr_prepare_window.py`（注释、输出文本）
   i. 修改 `ocr_engine/rapidocr_engine.py`（注释）

---

## 验证步骤

1. 运行 `python main.py`，确认应用正常启动
2. 检查步骤指示器显示：画框 → OCR准备 → 纵校 → 横校 → 精修
3. 导入含footer的JSON文件，确认footer框被绘制
4. 全流程走一遍，确认纵校（原横校）和横校（原纵校）功能正常
5. Grep检查是否还有遗漏的未互换引用
