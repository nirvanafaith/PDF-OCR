// hxnative.cpp — software1/software2 共享 C++ 热点加速扩展 (pybind11)
//
// 实现 spec: cpp-embedding-optimization
//   H1: pixmap_bytes_to_qpixmap_buffer  (跳过 PIL, fitz pixmap → QImage buffer)
//   H2: optimize_char_boxes              (整页字符边界框批量优化, 替代 numpy 逐字符切片)
//   H3: batch_crop_qimage                (批量字符裁切, 替代 PIL.Image.crop)
//
// 编译: 见同目录 CMakeLists.txt; 缺失时 Python 端自动回落, 详见 __init__.py。

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include "hxnative.h"

#include <algorithm>
#include <cstring>
#include <limits>
#include <stdexcept>

namespace py = pybind11;
using namespace hxnative;

// ============================================================================
// H1: fitz pixmap.samples → QImage 可用的紧凑像素 buffer
// ============================================================================
// 输入约定：
//   samples  : bytes / memoryview, 长度 = stride * height (或 width*n*height)
//   width    : 像素宽
//   height   : 像素高
//   n        : 通道数 (3=RGB, 4=RGBA)
//   stride   : 每行字节数 (若紧凑则 = width*n)
// 返回：紧凑 RGB888 或 RGBA8888 的 bytes, Python 端用
//       QImage(bytes, width, height, width*n, Format_RGB888/RGBA8888) 零拷贝构造。
// 当 stride == width*n 时, 我们直接返回原 samples (零拷贝)；
// 当不等时, 执行行间紧凑化拷贝。

std::string
hxnative::pixmap_bytes_to_qimage_buffer(const std::uint8_t *samples,
                                        int width, int height, int n,
                                        std::ptrdiff_t stride)
{
    if (width <= 0 || height <= 0 || (n != 3 && n != 4))
        throw std::runtime_error("hxnative: invalid pixmap dimensions or channel count");
    if (samples == nullptr)
        throw std::runtime_error("hxnative: null samples pointer");

    const std::ptrdiff_t tight = static_cast<std::ptrdiff_t>(width) * n;
    if (stride == tight) {
        // 零拷贝路径：直接以原 buffer 构造 string_view 风格的 bytes
        return std::string(reinterpret_cast<const char *>(samples),
                           static_cast<std::size_t>(tight * height));
    }
    // 行间紧凑化拷贝
    std::string out;
    out.resize(static_cast<std::size_t>(tight * height));
    char *dst = &out[0];
    const std::uint8_t *src = samples;
    for (int y = 0; y < height; ++y) {
        std::memcpy(dst + y * tight, src + y * stride,
                    static_cast<std::size_t>(tight));
    }
    return out;
}

// ============================================================================
// H2: 字符边界框批量优化
// ============================================================================
// 与 software1/ocr_engine/rapidocr_engine.py::_optimize_char_boxes 算法等价：
//   对每个字符 box (4 角点) 展平为 [xmin,ymin,xmax,ymax]，
//   裁剪到图像边界后, 对 4 条边各在 ±1/3*边长 范围内搜索,
//   找到使经过的非白像素数最少的列/行位置 (并列时取最接近原始位置的)。
// C++ 单遍：一次性把所有 char 的 4 边搜索区间收集, 在连续 mask 内存上
//   用裸指针累加, 避免每字符多次 numpy 切片启动开销。

static inline double
optimize_edge_x_inner(const std::uint8_t *mask, int H, int W,
                      double orig_x, int y1, int y2,
                      double edge_len)
{
    if (y2 <= y1) return orig_x;
    double half = edge_len / 3.0;
    int search_start = static_cast<int>(orig_x - half);
    int search_end   = static_cast<int>(orig_x + half) + 1;
    if (search_start < 0) search_start = 0;
    if (search_end > W)   search_end   = W;
    if (search_end <= search_start) return orig_x;

    const int span = search_end - search_start;
    // 行数：y2-y1, 列数：span; 逐列求和
    // mask 为 [H, W] C-contiguous, mask[y*W + x]
    std::vector<long> col_sums(span, 0);
    for (int y = y1; y < y2; ++y) {
        const std::uint8_t *row = mask + static_cast<std::ptrdiff_t>(y) * W;
        for (int k = 0; k < span; ++k) {
            col_sums[k] += row[search_start + k] ? 1 : 0;
        }
    }

    int orig_idx = static_cast<int>(std::lround(orig_x)) - search_start;
    if (orig_idx < 0) orig_idx = 0;
    else if (orig_idx >= span) orig_idx = span - 1;

    long min_count = col_sums[0];
    for (int k = 1; k < span; ++k)
        if (col_sums[k] < min_count) min_count = col_sums[k];

    if (col_sums[orig_idx] == min_count)
        return orig_x;

    // 取所有最小值位置中, 最接近 orig_idx 的
    int best_idx = orig_idx;
    int best_dist = std::numeric_limits<int>::max();
    for (int k = 0; k < span; ++k) {
        if (col_sums[k] == min_count) {
            int d = std::abs(k - orig_idx);
            if (d < best_dist) {
                best_dist = d;
                best_idx = k;
            }
        }
    }
    return static_cast<double>(search_start + best_idx);
}

static inline double
optimize_edge_y_inner(const std::uint8_t *mask, int H, int W,
                      double orig_y, int x1, int x2,
                      double edge_len)
{
    if (x2 <= x1) return orig_y;
    double half = edge_len / 3.0;
    int search_start = static_cast<int>(orig_y - half);
    int search_end   = static_cast<int>(orig_y + half) + 1;
    if (search_start < 0) search_start = 0;
    if (search_end > H)   search_end   = H;
    if (search_end <= search_start) return orig_y;

    const int span = search_end - search_start;
    std::vector<long> row_sums(span, 0);
    for (int k = 0; k < span; ++k) {
        const std::uint8_t *row = mask + static_cast<std::ptrdiff_t>(search_start + k) * W;
        long s = 0;
        for (int x = x1; x < x2; ++x)
            if (row[x]) ++s;
        row_sums[k] = s;
    }

    int orig_idx = static_cast<int>(std::lround(orig_y)) - search_start;
    if (orig_idx < 0) orig_idx = 0;
    else if (orig_idx >= span) orig_idx = span - 1;

    long min_count = row_sums[0];
    for (int k = 1; k < span; ++k)
        if (row_sums[k] < min_count) min_count = row_sums[k];

    if (row_sums[orig_idx] == min_count)
        return orig_y;

    int best_idx = orig_idx;
    int best_dist = std::numeric_limits<int>::max();
    for (int k = 0; k < span; ++k) {
        if (row_sums[k] == min_count) {
            int d = std::abs(k - orig_idx);
            if (d < best_dist) {
                best_dist = d;
                best_idx = k;
            }
        }
    }
    return static_cast<double>(search_start + best_idx);
}

// 判断竖排字符的 y 边是否需要优化：检测 y 边附近 ±2px 范围的有色像素数，
// 若 > edge_len * 0.3 判定"切到文字本体"，需要执行 y 边优化；否则保持原 y 值。
// 与 Python 端 _should_optimize_y_edge 算法等价。
static inline bool
should_optimize_y_edge_inner(const std::uint8_t *mask, int H, int W,
                             double y_edge, int x1, int x2,
                             double edge_len)
{
    if (x2 <= x1) return false;
    int y_start = std::max(0, static_cast<int>(std::lround(y_edge)) - 2);
    int y_end   = std::min(H, static_cast<int>(std::lround(y_edge)) + 3);
    if (y_end <= y_start) return false;
    long ink_count = 0;
    for (int y = y_start; y < y_end; ++y) {
        const std::uint8_t *row = mask + static_cast<std::ptrdiff_t>(y) * W;
        for (int x = x1; x < x2; ++x)
            if (row[x]) ++ink_count;
    }
    long threshold = std::max<long>(1, static_cast<long>(edge_len * 0.3));
    return ink_count > threshold;
}

std::vector<CharBoxOutput>
hxnative::optimize_char_boxes_batch(const std::uint8_t *mask, int H, int W,
                                    const std::vector<CharBoxInput> &inputs,
                                    bool is_vertical_page)
{
    std::vector<CharBoxOutput> out;
    out.reserve(inputs.size());
    if (mask == nullptr || H <= 0 || W <= 0) {
        for (const auto &c : inputs) {
            // 无法优化, 标记 invalid, 调用方保持原值
            double xmin = std::min(std::min(c.x0, c.x1), std::min(c.x2, c.x3));
            double ymin = std::min(std::min(c.y0, c.y1), std::min(c.y2, c.y3));
            double xmax = std::max(std::max(c.x0, c.x1), std::max(c.x2, c.x3));
            double ymax = std::max(std::max(c.y0, c.y1), std::max(c.y2, c.y3));
            out.push_back({xmin, ymin, xmax, ymax, false});
        }
        return out;
    }

    for (const auto &c : inputs) {
        // 展平为 [xmin,ymin,xmax,ymax]
        double xs[4] = {c.x0, c.x1, c.x2, c.x3};
        double ys[4] = {c.y0, c.y1, c.y2, c.y3};
        double xmin = *std::min_element(xs, xs + 4);
        double ymin = *std::min_element(ys, ys + 4);
        double xmax = *std::max_element(xs, xs + 4);
        double ymax = *std::max_element(ys, ys + 4);

        double w = xmax - xmin;
        double h = ymax - ymin;
        if (w <= 0 || h <= 0) {
            out.push_back({xmin, ymin, xmax, ymax, false});
            continue;
        }

        // 裁剪到图像边界
        int x1_c = std::max(0, static_cast<int>(std::lround(xmin)));
        int y1_c = std::max(0, static_cast<int>(std::lround(ymin)));
        int x2_c = std::min(W, static_cast<int>(std::lround(xmax)));
        int y2_c = std::min(H, static_cast<int>(std::lround(ymax)));

        // x 边始终优化（竖排字符的 x 边是左右边，需要紧贴墨水）
        double new_x1 = optimize_edge_x_inner(mask, H, W, xmin, y1_c, y2_c, w);
        double new_x2 = optimize_edge_x_inner(mask, H, W, xmax, y1_c, y2_c, w);
        double new_y1, new_y2;
        if (is_vertical_page) {
            // 竖排页面：y 边有条件优化
            // 检测原始 y 边是否切到文字本体（±2px 范围有色像素 > 边长 30%），
            // 若是则优化，否则保持原值（避免在空白处过度优化切到字间空白）
            if (should_optimize_y_edge_inner(mask, H, W, ymin, x1_c, x2_c, w)) {
                new_y1 = optimize_edge_y_inner(mask, H, W, ymin, x1_c, x2_c, h);
            } else {
                new_y1 = ymin;
            }
            if (should_optimize_y_edge_inner(mask, H, W, ymax, x1_c, x2_c, w)) {
                new_y2 = optimize_edge_y_inner(mask, H, W, ymax, x1_c, x2_c, h);
            } else {
                new_y2 = ymax;
            }
        } else {
            // 横排页面：保留逐字符 h>w 检查作为额外保护
            if (h > w) {
                new_y1 = ymin;
                new_y2 = ymax;
            } else {
                new_y1 = optimize_edge_y_inner(mask, H, W, ymin, x1_c, x2_c, h);
                new_y2 = optimize_edge_y_inner(mask, H, W, ymax, x1_c, x2_c, h);
            }
        }

        bool valid = (new_x1 < new_x2 && new_y1 < new_y2);
        out.push_back({new_x1, new_y1, new_x2, new_y2, valid});
    }
    return out;
}

// ============================================================================
// H3: 批量字符裁切 (整页 RGBA → 多张紧凑 RGBA 切片)
// ============================================================================

std::vector<std::string>
hxnative::batch_crop_rgba(const std::uint8_t *page_rgba, int w, int h,
                          const std::vector<CropBBox> &bboxes, int padding)
{
    std::vector<std::string> out;
    out.reserve(bboxes.size());
    if (page_rgba == nullptr || w <= 0 || h <= 0) {
        for (size_t i = 0; i < bboxes.size(); ++i)
            out.emplace_back();  // 空 bytes, Python 端跳过
        return out;
    }

    const int channels = 4;
    for (const auto &bb : bboxes) {
        int cx1 = bb.x1 - padding;
        int cy1 = bb.y1 - padding;
        int cx2 = bb.x2 + padding;
        int cy2 = bb.y2 + padding;
        if (cx1 < 0) cx1 = 0;
        if (cy1 < 0) cy1 = 0;
        if (cx2 > w) cx2 = w;
        if (cy2 > h) cy2 = h;
        int cw = cx2 - cx1;
        int ch = cy2 - cy1;
        if (cw <= 0 || ch <= 0) {
            out.emplace_back();
            continue;
        }
        std::string buf;
        buf.resize(static_cast<std::size_t>(cw) * ch * channels);
        char *dst = &buf[0];
        // 逐行拷贝
        const std::ptrdiff_t src_row = static_cast<std::ptrdiff_t>(w) * channels;
        const std::ptrdiff_t dst_row = static_cast<std::ptrdiff_t>(cw) * channels;
        for (int y = 0; y < ch; ++y) {
            const std::uint8_t *src_row_ptr =
                page_rgba + static_cast<std::ptrdiff_t>(cy1 + y) * src_row
                          + static_cast<std::ptrdiff_t>(cx1) * channels;
            std::memcpy(dst + y * dst_row, src_row_ptr,
                        static_cast<std::size_t>(dst_row));
        }
        out.push_back(std::move(buf));
    }
    return out;
}

// ============================================================================
// pybind11 绑定
// ============================================================================

PYBIND11_MODULE(_hxnative, m) {
    m.doc() = "software1/software2 共享 C++ 热点加速扩展 (pybind11)";

    // ---- H1 ----
    // 接受任意支持 buffer 协议的对象 (bytes / memoryview / bytearray)
    // 注意: 不使用 call_guard<gil_scoped_release> 因为 lambda 内访问 Python buffer 对象需要 GIL
    m.def("pixmap_bytes_to_qpixmap_buffer",
          [](py::buffer samples, int width, int height, int n,
             std::ptrdiff_t stride) -> py::bytes {
              py::buffer_info info = samples.request();
              if (info.ndim != 1)
                  throw std::runtime_error("samples must be a 1-D buffer");
              const std::uint8_t *ptr = static_cast<const std::uint8_t *>(info.ptr);
              std::ptrdiff_t given_stride = stride;
              if (given_stride <= 0)
                  given_stride = static_cast<std::ptrdiff_t>(width) * n;
              std::string out = pixmap_bytes_to_qimage_buffer(
                  ptr, width, height, n, given_stride);
              return py::bytes(out);
          },
          py::arg("samples"),
          py::arg("width"),
          py::arg("height"),
          py::arg("n"),
          py::arg("stride") = 0,
          "H1: fitz pixmap.samples -> 紧凑像素 bytes, Python 端用 QImage 零拷贝构造");

    // ---- H2 ----
    // mask: np.ndarray[uint8, 2D, C-contig] (Python 端传 (np.any(img<200,axis=2)).astype(np.uint8))
    // chars: list[dict], 每个含 box (4 角点 [[x,y],[x,y],[x,y],[x,y]])
    // 返回 list[dict] 每个 {new_x1,new_y1,new_x2,new_y2,valid, box: [[x,y],[x,y],[x,y],[x,y]]}
    // 注意: 不使用 call_guard<gil_scoped_release> 因为 lambda 内大量访问 Python dict/list 对象需要 GIL
    m.def("optimize_char_boxes",
          [](py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast> mask_arr,
             py::list chars,
             bool is_vertical_page) -> py::list {
              auto buf = mask_arr.request();
              if (buf.ndim != 2)
                  throw std::runtime_error("mask must be 2-D");
              int H = static_cast<int>(buf.shape[0]);
              int W = static_cast<int>(buf.shape[1]);
              const std::uint8_t *mask_ptr = static_cast<const std::uint8_t *>(buf.ptr);

              std::vector<CharBoxInput> inputs;
              inputs.reserve(static_cast<std::size_t>(chars.size()));
              for (auto item : chars) {
                  py::dict d = item.cast<py::dict>();
                  py::object box_obj = d["box"];
                  py::list box = box_obj.cast<py::list>();
                  if (box.size() != 4) {
                      // 非四角点格式, 跳过优化 (调用方 fallback)
                      inputs.push_back({0, 0, 0, 0, 0, 0, 0, 0});
                      continue;
                  }
                  // box 可能是 [[x,y],[x,y],[x,y],[x,y]] 或 [x1,y1,x2,y2]
                  if (box[0].cast<py::object>().ptr() != nullptr &&
                      py::isinstance<py::list>(box[0])) {
                      py::list p0 = box[0].cast<py::list>();
                      py::list p1 = box[1].cast<py::list>();
                      py::list p2 = box[2].cast<py::list>();
                      py::list p3 = box[3].cast<py::list>();
                      inputs.push_back({
                          p0[0].cast<double>(), p0[1].cast<double>(),
                          p1[0].cast<double>(), p1[1].cast<double>(),
                          p2[0].cast<double>(), p2[1].cast<double>(),
                          p3[0].cast<double>(), p3[1].cast<double>(),
                      });
                  } else {
                      // [x1,y1,x2,y2] 矩形格式
                      double a = box[0].cast<double>();
                      double b = box[1].cast<double>();
                      double c = box[2].cast<double>();
                      double d2 = box[3].cast<double>();
                      inputs.push_back({a, b, c, b, c, d2, a, d2});
                  }
              }

              // 纯 C++ 计算: 在此显式释放 GIL 以允许并行
              std::vector<CharBoxOutput> results;
              {
                  py::gil_scoped_release release;
                  results = optimize_char_boxes_batch(mask_ptr, H, W, inputs, is_vertical_page);
              }

              py::list out;
              for (size_t i = 0; i < results.size(); ++i) {
                  const auto &r = results[i];
                  py::dict d = chars[i].cast<py::dict>();
                  py::dict res;
                  res["new_x1"] = r.new_x1;
                  res["new_y1"] = r.new_y1;
                  res["new_x2"] = r.new_x2;
                  res["new_y2"] = r.new_y2;
                  res["valid"]  = r.valid;
                  if (r.valid) {
                      py::list newbox;
                      newbox.append(py::list(py::make_tuple(r.new_x1, r.new_y1)));
                      newbox.append(py::list(py::make_tuple(r.new_x2, r.new_y1)));
                      newbox.append(py::list(py::make_tuple(r.new_x2, r.new_y2)));
                      newbox.append(py::list(py::make_tuple(r.new_x1, r.new_y2)));
                      res["box"] = newbox;
                  } else {
                      // invalid 时保留原 box
                      res["box"] = d.contains("box") ? d["box"] : py::none();
                  }
                  out.append(res);
              }
              return out;
          },
          py::arg("mask"),
          py::arg("chars"),
          py::arg("is_vertical_page") = false,
          "H2: 整页字符边界框批量优化, 替代 numpy 逐字符 4 次切片求和");

    // ---- H3 ----
    // page_rgba: 1-D buffer (整页 RGBA 紧凑像素)
    // bboxes: list[[x1,y1,x2,y2], ...] (int)
    // padding: int
    // 返回 list[bytes], 每个 bytes 为一张紧凑 RGBA 切片
    // 注意: 不使用 call_guard<gil_scoped_release> 因为 lambda 内访问 Python list 对象需要 GIL
    m.def("batch_crop_qimage",
          [](py::buffer page_rgba, int w, int h,
             py::list bboxes, int padding) -> py::list {
              py::buffer_info info = page_rgba.request();
              const std::uint8_t *ptr = static_cast<const std::uint8_t *>(info.ptr);

              std::vector<CropBBox> inputs;
              inputs.reserve(static_cast<std::size_t>(bboxes.size()));
              for (auto item : bboxes) {
                  py::list bb = item.cast<py::list>();
                  if (bb.size() != 4) {
                      inputs.push_back({0, 0, 0, 0});
                      continue;
                  }
                  inputs.push_back({
                      bb[0].cast<int>(),
                      bb[1].cast<int>(),
                      bb[2].cast<int>(),
                      bb[3].cast<int>(),
                  });
              }

              // 纯 C++ 计算: 在此显式释放 GIL
              std::vector<std::string> results;
              {
                  py::gil_scoped_release release;
                  results = batch_crop_rgba(ptr, w, h, inputs, padding);
              }

              py::list out;
              for (auto &s : results) {
                  out.append(py::bytes(s));
              }
              return out;
          },
          py::arg("page_rgba"),
          py::arg("w"),
          py::arg("h"),
          py::arg("bboxes"),
          py::arg("padding"),
          "H3: 批量字符裁切, 一次返回所有切片的紧凑 RGBA bytes");

    m.def("has_native", []() { return true; },
          "检测 _hxnative 是否可用 (Python 端 __init__.py 也提供同名函数)");
}
