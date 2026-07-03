# 为软件每个函数添加专业注释的计划

## 项目概述

本项目是一个"图片PDF文字识别与人工校正系统"，基于 PyQt6 构建 GUI，使用 RapidOCR 进行 OCR 识别，通过四个阶段（OCR准备 → 横校 → 纵校 → 精修）完成 PDF 文字的识别与校正，最终生成双层 PDF。

## 注释规范

为每个函数/方法添加以下格式的 docstring：

```python
def func_name(param1, param2):
    """函数功能的简明描述。

    功能详述（如需要）。

    参数:
        param1 (type): 参数说明
        param2 (type): 参数说明

    返回:
        type: 返回值说明

    调用关系:
        - 被调用者: 哪些函数调用了本函数
        - 调用: 本函数调用了哪些函数

    依赖:
        - 依赖的库/模块
    """
```

## 需要注释的文件和函数清单

### 1. `new.py`（2个函数）

| 函数 | 说明 |
|------|------|
| `convert_ocr_result_to_json(result)` | 已有简单 docstring，需补充参数、返回值、调用关系、依赖 |
| `main()` | 无 docstring，需添加完整注释 |

### 2. `models/data_models.py`（1个函数 + 9个数据类）

| 函数/类 | 说明 |
|---------|------|
| `TextLine` | dataclass，需添加类注释 |
| `OCRPageResult` | dataclass，需添加类注释 |
| `OCRResult` | dataclass，需添加类注释 |
| `CharSlice` | dataclass，需添加类注释 |
| `LineSlice` | dataclass，需添加类注释 |
| `CorrectedChar` | dataclass，需添加类注释 |
| `CorrectedLine` | dataclass，需添加类注释 |
| `HorizontalCheckData` | dataclass，需添加类注释 |
| `VerticalCheckData` | dataclass，需添加类注释 |
| `FinalCharList` | dataclass，需添加类注释 |
| `RefineTextItem` | dataclass，需添加类注释 |
| `flatten_bbox(bbox)` | 需添加完整 docstring |

### 3. `ocr_engine/rapidocr_engine.py`（OCREngine 类，5个方法）

| 方法 | 说明 |
|------|------|
| `__init__(use_cuda)` | 需添加完整 docstring |
| `_recognize_page(page_image, page_idx, output_callback)` | 已有简单 docstring，需补充参数类型、调用关系、依赖 |
| `run_ocr(pdf_path, output_dir, output_callback)` | 已有简单 docstring，需补充参数类型、调用关系、依赖 |
| `load_results_from_file(lines_json_path, chars_json_path)` | 已有简单 docstring，需补充调用关系、依赖 |
| `parse_and_group(results, page_images)` | 已有简单 docstring，需补充参数类型、调用关系、依赖 |
| `build_line_data(results, page_images, char_slices)` | 已有简单 docstring，需补充参数类型、调用关系、依赖 |

### 4. `pdf_processor/pdf_loader.py`（2个类，5个方法）

| 方法 | 说明 |
|------|------|
| `PDFProcessor.convert_to_images(pdf_path, dpi)` | 需添加完整 docstring |
| `PDFProcessor.get_lazy_loader(pdf_path, dpi)` | 需添加完整 docstring |
| `PDFProcessor.get_page_count(pdf_path)` | 需添加完整 docstring |
| `LazyPageLoader.__init__(pdf_path, dpi)` | 需添加完整 docstring |
| `LazyPageLoader.get_page(page_num)` | 需添加完整 docstring |
| `LazyPageLoader.get_page_size(page_num)` | 需添加完整 docstring |
| `LazyPageLoader.close()` | 需添加完整 docstring |

### 5. `pdf_processor/pdf_output.py`（1个类，1个方法 + 模块级代码）

| 方法/代码 | 说明 |
|-----------|------|
| 模块级字体注册代码 | 需添加注释说明 |
| `PDFOutputGenerator.generate(corrected_chars, page_images, output_path, pdf_path)` | 需添加完整 docstring |

### 6. `ui/styles.py`（1个函数 + 模块级常量）

| 函数/常量 | 说明 |
|-----------|------|
| `MAIN_STYLESHEET` | 需添加注释说明 |
| `get_stylesheet()` | 需添加完整 docstring |

### 7. `main.py`（2个类，10个方法）

| 方法 | 说明 |
|------|------|
| `StepIndicator.__init__(steps, parent)` | 需添加完整 docstring |
| `StepIndicator._init_ui()` | 需添加完整 docstring |
| `StepIndicator._set_active_style(label)` | 需添加完整 docstring |
| `StepIndicator._set_done_style(label)` | 需添加完整 docstring |
| `StepIndicator._set_inactive_style(label)` | 需添加完整 docstring |
| `StepIndicator._set_arrow_style(label)` | 需添加完整 docstring |
| `StepIndicator.set_current(index)` | 需添加完整 docstring |
| `MainWindow.__init__()` | 需添加完整 docstring |
| `MainWindow._init_ui()` | 需添加完整 docstring |
| `MainWindow._setup_prepare_stage()` | 需添加完整 docstring |
| `MainWindow._on_prepare_finished(page_images, ocr_results, char_slices)` | 需添加完整 docstring |
| `MainWindow._on_horizontal_finished(updated_char_slices, updated_ocr_results)` | 需添加完整 docstring |
| `MainWindow._on_vertical_finished(corrected_lines)` | 需添加完整 docstring |
| `MainWindow._on_refine_save(corrected_chars, page_images, output_path)` | 需添加完整 docstring |
| `MainWindow._on_refine_finished()` | 需添加完整 docstring |

### 8. `ui/horizontal_check_window.py`（2个类，11个方法）

| 方法 | 说明 |
|------|------|
| `SliceItemWidget.__init__(pixmap, index, parent)` | 需添加完整 docstring |
| `SliceItemWidget._show_context_menu(pos)` | 需添加完整 docstring |
| `HorizontalCheckWindow.__init__(char_slices, page_images, ocr_results, parent)` | 需添加完整 docstring |
| `HorizontalCheckWindow._init_ui()` | 需添加完整 docstring |
| `HorizontalCheckWindow._on_label_selected(current, previous)` | 需添加完整 docstring |
| `HorizontalCheckWindow._update_slice_display(char_text)` | 需添加完整 docstring |
| `HorizontalCheckWindow._on_relocate(slice_index)` | 需添加完整 docstring |
| `HorizontalCheckWindow._on_delete_slice(slice_index)` | 需添加完整 docstring |
| `HorizontalCheckWindow._update_ocr_results_char(char_slice, new_text)` | 需添加完整 docstring |
| `HorizontalCheckWindow._on_next_step()` | 需添加完整 docstring |
| `HorizontalCheckWindow._refresh_label_list()` | 需添加完整 docstring |
| `HorizontalCheckWindow._pil_to_pixmap(pil_image)` | 需添加完整 docstring |
| `HorizontalCheckWindow.keyPressEvent(event)` | 需添加完整 docstring |

### 9. `ui/vertical_check_window.py`（1个类，15个方法）

| 方法 | 说明 |
|------|------|
| `VerticalCheckWindow.__init__(page_lines, page_images, parent)` | 需添加完整 docstring |
| `VerticalCheckWindow._init_ui()` | 需添加完整 docstring |
| `VerticalCheckWindow._render_page()` | 需添加完整 docstring |
| `VerticalCheckWindow._remove_hover_pixmap()` | 需添加完整 docstring |
| `VerticalCheckWindow.eventFilter(obj, event)` | 需添加完整 docstring |
| `VerticalCheckWindow._make_slice_pixmap(ls)` | 需添加完整 docstring |
| `VerticalCheckWindow._on_context_menu(pos)` | 需添加完整 docstring |
| `VerticalCheckWindow._on_modify_text(item)` | 需添加完整 docstring |
| `VerticalCheckWindow._on_ignore_line(item)` | 需添加完整 docstring |
| `VerticalCheckWindow._on_hand_tool_toggle()` | 需添加完整 docstring |
| `VerticalCheckWindow._on_prev_page()` | 需添加完整 docstring |
| `VerticalCheckWindow._on_next_page()` | 需添加完整 docstring |
| `VerticalCheckWindow._on_goto_page(page_num)` | 需添加完整 docstring |
| `VerticalCheckWindow._on_zoom_in()` | 需添加完整 docstring |
| `VerticalCheckWindow._on_zoom_out()` | 需添加完整 docstring |
| `VerticalCheckWindow._on_fit_width()` | 需添加完整 docstring |
| `VerticalCheckWindow._on_finish()` | 需添加完整 docstring |
| `VerticalCheckWindow._pil_to_pixmap(pil_image)` | 需添加完整 docstring |
| `VerticalCheckWindow._build_corrected_lines()` | 需添加完整 docstring |

### 10. `ui/refine_window.py`（2个类，24个方法）

| 方法 | 说明 |
|------|------|
| `MovableTextItem.__init__(text_item_data, zoom_level)` | 需添加完整 docstring |
| `MovableTextItem.activate()` | 需添加完整 docstring |
| `MovableTextItem.deactivate()` | 需添加完整 docstring |
| `MovableTextItem._center_text()` | 需添加完整 docstring |
| `MovableTextItem._create_handles()` | 需添加完整 docstring |
| `MovableTextItem._position_handles()` | 需添加完整 docstring |
| `MovableTextItem._update_selection_visual()` | 需添加完整 docstring |
| `MovableTextItem.setSelected(selected)` | 需添加完整 docstring |
| `MovableTextItem.isSelected()` | 需添加完整 docstring |
| `MovableTextItem._handle_at(scene_pos)` | 需添加完整 docstring |
| `MovableTextItem.mousePressEvent(event)` | 需添加完整 docstring |
| `MovableTextItem.mouseMoveEvent(event)` | 需添加完整 docstring |
| `MovableTextItem.mouseReleaseEvent(event)` | 需添加完整 docstring |
| `MovableTextItem.mouseDoubleClickEvent(event)` | 需添加完整 docstring |
| `MovableTextItem.contextMenuEvent(event)` | 需添加完整 docstring |
| `MovableTextItem._edit_text()` | 需添加完整 docstring |
| `MovableTextItem.update_zoom(new_zoom)` | 需添加完整 docstring |
| `RefineWindow.__init__(page_lines, page_images, parent)` | 需添加完整 docstring |
| `RefineWindow._convert_chars()` | 需添加完整 docstring |
| `RefineWindow._init_ui()` | 需添加完整 docstring |
| `RefineWindow._render_page()` | 需添加完整 docstring |
| `RefineWindow._sync_current_page()` | 需添加完整 docstring |
| `RefineWindow._on_hand_tool_toggle()` | 需添加完整 docstring |
| `RefineWindow._on_drag_toggle()` | 需添加完整 docstring |
| `RefineWindow._on_add_text_toggle()` | 需添加完整 docstring |
| `RefineWindow.eventFilter(obj, event)` | 需添加完整 docstring |
| `RefineWindow._on_context_menu(pos)` | 需添加完整 docstring |
| `RefineWindow._add_text_at(scene_pos)` | 需添加完整 docstring |
| `RefineWindow._get_avg_font_size()` | 需添加完整 docstring |
| `RefineWindow.keyPressEvent(event)` | 需添加完整 docstring |
| `RefineWindow._on_prev_page()` | 需添加完整 docstring |
| `RefineWindow._on_next_page()` | 需添加完整 docstring |
| `RefineWindow._on_goto_page(page_num)` | 需添加完整 docstring |
| `RefineWindow._on_zoom_in()` | 需添加完整 docstring |
| `RefineWindow._on_zoom_out()` | 需添加完整 docstring |
| `RefineWindow._on_fit_width()` | 需添加完整 docstring |
| `RefineWindow._on_output()` | 需添加完整 docstring |
| `RefineWindow._build_corrected_chars()` | 需添加完整 docstring |
| `RefineWindow._pil_to_pixmap(pil_image)` | 需添加完整 docstring |
| `RefineWindow.cleanup()` | 需添加完整 docstring |

### 11. `ui/ocr_prepare_window.py`（3个类，16个方法）

| 方法 | 说明 |
|------|------|
| `OCRWorker.__init__(pdf_path, output_dir, ocr_engine)` | 需添加完整 docstring |
| `OCRWorker.run()` | 需添加完整 docstring |
| `DataLoadWorker.__init__(pdf_path, lines_path, chars_path, ocr_engine, pdf_processor)` | 需添加完整 docstring |
| `DataLoadWorker.run()` | 需添加完整 docstring |
| `OCRPrepareWindow.__init__(pdf_path, parent)` | 需添加完整 docstring |
| `OCRPrepareWindow._init_ui()` | 需添加完整 docstring |
| `OCRPrepareWindow._on_pdf_path_changed(text)` | 需添加完整 docstring |
| `OCRPrepareWindow._on_browse_pdf()` | 需添加完整 docstring |
| `OCRPrepareWindow._on_browse_lines()` | 需添加完整 docstring |
| `OCRPrepareWindow._on_browse_chars()` | 需添加完整 docstring |
| `OCRPrepareWindow._check_next_enabled()` | 需添加完整 docstring |
| `OCRPrepareWindow._on_run_ocr()` | 需添加完整 docstring |
| `OCRPrepareWindow._on_ocr_finished(results, output_dir)` | 需添加完整 docstring |
| `OCRPrepareWindow._on_ocr_error(error_msg)` | 需添加完整 docstring |
| `OCRPrepareWindow._append_output(text)` | 需添加完整 docstring |
| `OCRPrepareWindow._on_next()` | 需添加完整 docstring |
| `OCRPrepareWindow._on_data_loaded(page_images, results, char_slices)` | 需添加完整 docstring |
| `OCRPrepareWindow._on_data_error(error_msg)` | 需添加完整 docstring |
| `OCRPrepareWindow._cleanup_data_thread()` | 需添加完整 docstring |
| `OCRPrepareWindow.cleanup()` | 需添加完整 docstring |

## 实施步骤

按文件逐一添加注释，每个文件完成后标记为完成：

1. **`models/data_models.py`** — 数据模型层，被所有模块引用，优先注释
2. **`pdf_processor/pdf_loader.py`** — PDF处理层
3. **`pdf_processor/pdf_output.py`** — PDF输出层
4. **`ocr_engine/rapidocr_engine.py`** — OCR引擎层
5. **`ui/styles.py`** — UI样式层
6. **`ui/horizontal_check_window.py`** — 横校窗口
7. **`ui/vertical_check_window.py`** — 纵校窗口
8. **`ui/refine_window.py`** — 精修窗口
9. **`ui/ocr_prepare_window.py`** — OCR准备窗口
10. **`main.py`** — 主窗口入口
11. **`new.py`** — 独立测试脚本

## 注释示例

以 `flatten_bbox` 为例展示最终注释风格：

```python
def flatten_bbox(bbox):
    """将四点坐标格式的边界框转换为 [x1, y1, x2, y2] 格式。

    输入可以是 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] 的四点格式，
    输出为 [min_x, min_y, max_x, max_y] 的轴对齐矩形格式。
    如果输入格式不符合预期，则原样返回或返回 [0,0,0,0]。

    参数:
        bbox (list): 边界框坐标，支持四点格式或 [x1,y1,x2,y2] 格式

    返回:
        list: [x1, y1, x2, y2] 格式的轴对齐边界框坐标

    调用关系:
        - 被调用者: OCREngine.parse_and_group, OCREngine.build_line_data
        - 调用: 无

    依赖:
        - 无外部依赖
    """
```

## 统计

- 总计文件数：11
- 总计函数/方法数：约 90+
- 总计数据类：11
