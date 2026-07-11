#pragma once

// hxnative.h — 内部 C++ 辅助声明 (不导出 Python，仅当前编译单元复用)
//
// 本扩展为 software1 (PyQt6) 与 software2 (PyQt5) 共享的热点加速模块。
// 设计原则：
//   1. 不链接 Qt；只处理裸像素 buffer 与 numpy 数组。
//   2. 所有热点函数释放 GIL (py::call_guard<py::gil_scoped_release>)。
//   3. 缺失时由 Python 层 software_common/native/__init__.py 自动回落。

#include <cstdint>
#include <cstddef>
#include <string>
#include <vector>

namespace hxnative {

// ---- H1: fitz pixmap -> QPixmap 直通 ----------------------------------------
// 输入 fitz pixmap.samples (RGB 或 RGBA, 紧凑或带 stride)，
// 输出 QImage 可直接使用的紧凑像素 bytes (Python 端用 Format_RGB888 / RGBA8888 构造)。
// 当 stride == width * n 时为无拷贝路径：直接返回原 buffer 的 view。
// 当 stride != width * n 时执行行间紧凑拷贝。
std::string pixmap_bytes_to_qimage_buffer(const std::uint8_t *samples,
                                          int width, int height, int n,
                                          std::ptrdiff_t stride);

// ---- H2: 字符边界框批量优化 --------------------------------------------------
// 输入整页 mask (uint8, 0/1, C-contiguous, shape [H, W])，
// 输入 chars 列表 (每个含 box 4 角点 + bbox 边界)。
// 在 C++ 内单遍遍历所有 char, 对 4 条边在连续 mask 内存上求和，
// 取最小且最接近原始位置的候选；原地更新 char.box 为 4 角点格式。
// 逻辑与 software1/ocr_engine/rapidocr_engine.py::_optimize_char_boxes 字节级一致。
struct CharBoxInput {
    // 原始 4 角点 [x0,y0],[x1,y1],[x2,y2],[x3,y3] (来自 rapidocr)
    double x0, y0, x1, y1, x2, y2, x3, y3;
};
struct CharBoxOutput {
    double new_x1, new_y1, new_x2, new_y2;  // 优化后 [xmin,ymin,xmax,ymax]
    bool   valid;                            // false 表示无法优化 (保持原值)
};
std::vector<CharBoxOutput>
optimize_char_boxes_batch(const std::uint8_t *mask, int H, int W,
                          const std::vector<CharBoxInput> &inputs);

// ---- H3: 批量字符裁切 -------------------------------------------------------
// 输入整页 RGBA 紧凑像素 (page_rgba, w, h) 与一组 bbox [x1,y1,x2,y2]，
// padding 为四周扩展像素。返回每张切片的紧凑 RGBA bytes (Python 端 QImage 构造)。
struct CropBBox { int x1, y1, x2, y2; };
std::vector<std::string>
batch_crop_rgba(const std::uint8_t *page_rgba, int w, int h,
                const std::vector<CropBBox> &bboxes, int padding);

}  // namespace hxnative
