# 画框阶段PDF加载优化计划

## 问题分析

`DrawBoxWindow._on_browse_pdf` 在主线程中调用 `PDFProcessor.convert_to_images`，该方法一次性将PDF所有页面渲染为图像列表。对于大型PDF（如100页），这会导致UI冻结数秒。

## 根因

画框阶段用户一次只看一页，但当前实现一次性加载所有页面图像到内存中，既浪费时间又占用内存。

## 优化方案

使用项目已有的 `LazyPageLoader` 替代 `convert_to_images`，改为按需加载单页图像。

### 具体修改

**文件**：`ui/draw_box_window.py`

1. **修改 `_on_browse_pdf`**：
   - 不再调用 `convert_to_images`
   - 改为创建 `LazyPageLoader` 实例
   - 只加载第一页图像用于显示
   - 获取总页数用于页码显示

2. **修改 `__init__`**：
   - 将 `self.page_images = []` 改为 `self._lazy_loader = None`
   - 保留 `self.page_images` 作为当前页面的缓存（只存当前页）

3. **修改 `_render_page`**：
   - 从 `_lazy_loader.get_page` 获取当前页图像，而不是从 `page_images` 列表

4. **修改翻页方法**：
   - `_on_prev_page`/`_on_next_page` 中从 `_lazy_loader` 获取页面

5. **修改 `_on_finish`**：
   - 发射信号时仍传递 `pdf_path` 和 `boxes`
   - 不需要传递所有页面图像（OCR准备阶段会自己加载）

6. **新增 `cleanup` 方法**：
   - 关闭 `_lazy_loader` 释放资源

### 性能对比

| 场景 | 优化前 | 优化后 |
|------|--------|--------|
| 100页PDF加载 | ~10秒UI冻结 | ~100ms（只加载1页） |
| 内存占用 | 所有页面图像 | 最多5页（LRU缓存） |
| 翻页 | 即时（已加载） | ~100ms（按需渲染） |

### 注意事项

- `_render_page` 中的 `SmoothTransformation` 缩放对大图像也可能较慢，改为 `FastTransformation` 进一步优化
- `LazyPageLoader` 的 LRU 缓存上限为5页，足够覆盖前后翻页场景
