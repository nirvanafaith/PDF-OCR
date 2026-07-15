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
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <utility>

namespace py = pybind11;
using namespace hxnative;

// ---------------------------------------------------------------------------
// 可移植 popcount: MSVC 用 __popcnt64, GCC/Clang 用 __builtin_popcountll
// ---------------------------------------------------------------------------
#if defined(_MSC_VER)
#include <intrin.h>
static inline int hx_popcount64(std::uint64_t x) {
    return static_cast<int>(__popcnt64(x));
}
#else
static inline int hx_popcount64(std::uint64_t x) {
    return __builtin_popcountll(x);
}
#endif

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
//   裁剪到图像边界后, 对 4 条边各在 ±0.5*边长 范围内搜索,
//   找到使经过的非白像素数最少的列/行位置 (并列时取最接近原始位置的)。
// C++ 单遍：一次性把所有 char 的 4 边搜索区间收集, 在连续 mask 内存上
//   用裸指针累加, 避免每字符多次 numpy 切片启动开销。

static inline double
optimize_edge_x_inner(const std::uint8_t *mask, int H, int W,
                      double orig_x, int y1, int y2,
                      double edge_len)
{
    if (y2 <= y1) return orig_x;
    double half = edge_len * 0.5;
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
    double half = edge_len * 0.5;
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

std::vector<CharBoxOutput>
hxnative::optimize_char_boxes_batch(const std::uint8_t *mask, int H, int W,
                                    const std::vector<CharBoxInput> &inputs)
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

        // 优化 4 条边 (与 Python 版参数顺序一致)
        double new_x1 = optimize_edge_x_inner(mask, H, W, xmin, y1_c, y2_c, w);
        double new_x2 = optimize_edge_x_inner(mask, H, W, xmax, y1_c, y2_c, w);
        double new_y1 = optimize_edge_y_inner(mask, H, W, ymin, x1_c, x2_c, h);
        double new_y2 = optimize_edge_y_inner(mask, H, W, ymax, x1_c, x2_c, h);

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
// H4: PIL Image 像素 → QImage 可用的紧凑 RGBA bytes
// ============================================================================
// 输入：原始像素 buffer + 源模式("RGB"或"RGBA") + 尺寸 + stride
// 输出：紧凑 RGBA bytes，Python 端用 QImage(bytes, w, h, w*4, Format_RGBA8888) 构造
// 当源为 RGBA 且 stride==width*4 时零拷贝；当源为 RGB 时扩展为 RGBA(alpha=255)

std::string
hxnative::pil_to_qimage_buffer_impl(const std::uint8_t *samples,
                                     int width, int height,
                                     const std::string &mode,
                                     std::ptrdiff_t stride)
{
    if (width <= 0 || height <= 0)
        throw std::runtime_error("hxnative: invalid dimensions");
    if (samples == nullptr)
        throw std::runtime_error("hxnative: null samples pointer");

    const std::ptrdiff_t rgba_stride = static_cast<std::ptrdiff_t>(width) * 4;

    if (mode == "RGBA") {
        if (stride == rgba_stride) {
            // 零拷贝路径
            return std::string(reinterpret_cast<const char *>(samples),
                               static_cast<std::size_t>(rgba_stride * height));
        }
        // 行间紧凑化拷贝
        std::string out;
        out.resize(static_cast<std::size_t>(rgba_stride * height));
        char *dst = &out[0];
        for (int y = 0; y < height; ++y) {
            std::memcpy(dst + y * rgba_stride,
                        samples + y * stride,
                        static_cast<std::size_t>(rgba_stride));
        }
        return out;
    }

    if (mode == "RGB") {
        // RGB → RGBA 扩展 (alpha=255)
        std::string out;
        out.resize(static_cast<std::size_t>(rgba_stride * height));
        char *dst = &out[0];
        const std::ptrdiff_t rgb_stride = static_cast<std::ptrdiff_t>(width) * 3;
        const std::ptrdiff_t src_stride = (stride > 0) ? stride : rgb_stride;
        for (int y = 0; y < height; ++y) {
            const std::uint8_t *src_row = samples + y * src_stride;
            char *dst_row = dst + y * rgba_stride;
            for (int x = 0; x < width; ++x) {
                dst_row[x * 4]     = static_cast<char>(src_row[x * 3]);
                dst_row[x * 4 + 1] = static_cast<char>(src_row[x * 3 + 1]);
                dst_row[x * 4 + 2] = static_cast<char>(src_row[x * 3 + 2]);
                dst_row[x * 4 + 3] = static_cast<char>(255);
            }
        }
        return out;
    }

    throw std::runtime_error("hxnative: unsupported mode '" + mode + "' (only RGB/RGBA)");
}

// ============================================================================
// H6: 批量字号档位匹配
// ============================================================================
// 字号档位：1=26pt, 2=22pt, 3=16pt, 4=14pt, 5=10.5pt
// 五号放宽：line_height_pt < 15.0 时归五号

std::vector<int>
hxnative::batch_match_font_grade(const std::vector<double>& line_heights_pt)
{
    // 字号档位表（与 Python FONT_SIZE_GRADES 一致）
    static const double grades[] = {26.0, 22.0, 16.0, 14.0, 10.5};
    static const int grade_ids[] = {1, 2, 3, 4, 5};

    std::vector<int> result;
    result.reserve(line_heights_pt.size());

    for (double h : line_heights_pt) {
        if (h <= 0) {
            result.push_back(5);
            continue;
        }
        // 五号放宽：上界 15.0pt
        if (h < 15.0) {
            result.push_back(5);
            continue;
        }
        // 最近邻匹配
        int best_grade = 5;
        double best_diff = -1;
        for (int i = 0; i < 5; ++i) {
            double diff = std::abs(h - grades[i]);
            if (best_diff < 0 || diff < best_diff) {
                best_diff = diff;
                best_grade = grade_ids[i];
            }
        }
        result.push_back(best_grade);
    }
    return result;
}

// ============================================================================
// H7: 文字掩码与墨迹掩码最佳偏移搜索
// ============================================================================
// 与 alignment/text_aligner.py::find_best_offset 字节级等价：
//   遍历 (dx,dy) ∈ [-r,r]，对每个偏移取 ink_mask 的对应窗口与 text_mask 求交集，
//   返回使交集最大的 (dx,dy)；全零 ink_mask 返回 (0,0)；平局取首个（最小 dy、最小 dx）。

std::pair<int, int>
hxnative::find_best_offset(const std::uint8_t *text_mask, int th, int tw,
                            const std::uint8_t *ink_mask, int ih, int iw,
                            int radius)
{
    if (text_mask == nullptr || ink_mask == nullptr ||
        th <= 0 || tw <= 0 || ih <= 0 || iw <= 0 || radius < 0)
        return {0, 0};

    // 全零 ink_mask 检查（等价 numpy ink_mask.sum()==0）
    bool ink_has_any = false;
    for (std::size_t i = 0, n = static_cast<std::size_t>(ih) * iw; i < n; ++i) {
        if (ink_mask[i]) { ink_has_any = true; break; }
    }
    if (!ink_has_any)
        return {0, 0};

    // 预计算每行可批量处理的 uint64 段数与尾部字节数
    // 假定 text_mask / ink_mask 值为 0 或 1 (来自 numpy bool -> uint8 转换)，
    // 因此 uint64_t AND 后 popcount 直接统计两字节同时为 1 的位置数。
    const int tw_bytes = tw;
    const int n_full = tw_bytes / 8;   // 完整 uint64 段数
    const int n_tail = tw_bytes % 8;   // 尾部剩余字节数

    // 使用 long long 避免Windows平台 long(32位) 在大 mask (>46340x46340) 时溢出
    long long best_overlap = -1;
    int best_dx = 0, best_dy = 0;

    // 迭代序：外层 dy=-r..r，内层 dx=-r..r（与 numpy 一致）
    for (int dy = -radius; dy <= radius; ++dy) {
        int oy = radius + dy;
        if (oy < 0) continue;
        if (oy + th > ih) continue;
        for (int dx = -radius; dx <= radius; ++dx) {
            int ox = radius + dx;
            if (ox < 0) continue;
            if (ox + tw > iw) continue;
            // 计算交集：text_mask[y*tw+x] 与 ink_mask[(oy+y)*iw + (ox+x)] 都非零
            long long overlap = 0;
            const std::uint8_t *trow = text_mask;
            const std::uint8_t *irow = ink_mask + static_cast<std::ptrdiff_t>(oy) * iw + ox;
            for (int y = 0; y < th; ++y) {
                // 内层循环按 uint64_t 批量处理 (8 字节/次)
                // 用 memcpy 安全处理非对齐访问 (x86 上编译器优化为单条 mov 指令)
                int x = 0;
                for (int k = 0; k < n_full; ++k, x += 8) {
                    std::uint64_t t, i;
                    std::memcpy(&t, trow + x, 8);
                    std::memcpy(&i, irow + x, 8);
                    overlap += hx_popcount64(t & i);
                }
                // 尾部不足 8 字节逐字节处理
                for (int k = 0; k < n_tail; ++k, ++x) {
                    if (trow[x] && irow[x]) ++overlap;
                }
                trow += tw;
                irow += iw;
            }
            // 严格 >，首个最大值胜出（与 numpy if overlap > best_overlap 一致）
            if (overlap > best_overlap) {
                best_overlap = overlap;
                best_dx = dx;
                best_dy = dy;
            }
        }
    }
    return {best_dx, best_dy};
}

// ============================================================================
// H8: 从图像像素数据裁切 bbox 扩展 radius 的区域并二值化
// ============================================================================
// 与 alignment/text_aligner.py::extract_ink_mask 字节级等价:
//   1. 计算裁切区域 [x1-radius, y1-radius, x2+radius, y2+radius]
//   2. 裁剪到图像边界 [0, img_w) x [0, img_h)
//   3. 对每个像素用 PIL 'L' 模式等价灰度公式 L=(R*19595+G*38470+B*7471)>>16,
//      非白判定 L < 200 → 1, 否则 0
//   4. 返回紧凑 mask buffer + 裁切区域宽高 (不含 padding, Python 端自行补齐)

std::string
hxnative::extract_ink_mask_fast(const std::uint8_t *img_data,
                                int img_w, int img_h, int img_n,
                                const int *bbox, int bbox_len,
                                int radius,
                                int *out_w, int *out_h)
{
    if (img_data == nullptr || bbox == nullptr || bbox_len < 4 ||
        img_w <= 0 || img_h <= 0 || (img_n != 3 && img_n != 4) ||
        out_w == nullptr || out_h == nullptr || radius < 0)
        throw std::runtime_error("extract_ink_mask_fast: invalid arguments");

    // 与 Python int(x1 - radius) 等价 (bbox 已为 int, radius 为 int)
    int x1 = bbox[0] - radius;
    int y1 = bbox[1] - radius;
    int x2 = bbox[2] + radius;
    int y2 = bbox[3] + radius;

    // 裁剪到图像边界 (与 Python max(0, ...) / min(img_w, ...) 一致)
    if (x1 < 0) x1 = 0;
    if (y1 < 0) y1 = 0;
    if (x2 > img_w) x2 = img_w;
    if (y2 > img_h) y2 = img_h;

    int w = x2 - x1;
    int h = y2 - y1;
    if (w <= 0 || h <= 0) {
        *out_w = 0;
        *out_h = 0;
        return "";
    }

    std::string mask;
    mask.resize(static_cast<std::size_t>(w) * h);

    // PIL 'L' 模式灰度公式: L = (R*19595 + G*38470 + B*7471) >> 16
    // 阈值 200: L < 200 → 非白(墨迹)=1, 否则=0
    for (int y = 0; y < h; ++y) {
        const std::uint8_t *row =
            img_data + (static_cast<std::ptrdiff_t>(y1 + y) * img_w + x1) * img_n;
        char *dst = &mask[static_cast<std::size_t>(y) * w];
        for (int x = 0; x < w; ++x) {
            const std::uint8_t *px = row + static_cast<std::ptrdiff_t>(x) * img_n;
            int L = (px[0] * 19595 + px[1] * 38470 + px[2] * 7471) >> 16;
            dst[x] = (L < 200) ? 1 : 0;
        }
    }

    *out_w = w;
    *out_h = h;
    return mask;
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
             py::list chars) -> py::list {
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
                  results = optimize_char_boxes_batch(mask_ptr, H, W, inputs);
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

    // ---- H4 ----
    // 接受 buffer + mode 字符串 + 尺寸
    // 返回紧凑 RGBA bytes
    m.def("pil_to_qimage_buffer",
          [](py::buffer samples, int width, int height,
             const std::string &mode, std::ptrdiff_t stride) -> py::bytes {
              py::buffer_info info = samples.request();
              if (info.ndim != 1)
                  throw std::runtime_error("samples must be a 1-D buffer");
              const std::uint8_t *ptr = static_cast<const std::uint8_t *>(info.ptr);
              std::ptrdiff_t given_stride = stride;
              if (given_stride <= 0) {
                  given_stride = (mode == "RGBA") ? static_cast<std::ptrdiff_t>(width) * 4
                                                   : static_cast<std::ptrdiff_t>(width) * 3;
              }
              std::string out = pil_to_qimage_buffer_impl(
                  ptr, width, height, mode, given_stride);
              return py::bytes(out);
          },
          py::arg("samples"),
          py::arg("width"),
          py::arg("height"),
          py::arg("mode"),
          py::arg("stride") = 0,
          "H4: PIL pixel buffer -> 紧凑 RGBA bytes (RGB→RGBA 扩展, RGBA 行间紧凑化)");

    // ---- H6 ----
    // line_heights_pt: list[float] 行框高度（磅值）
    // 返回 list[int] 档位号（1-5），含五号放宽（< 15.0pt 归五号）
    m.def("batch_match_font_grade", &hxnative::batch_match_font_grade,
          py::call_guard<py::gil_scoped_release>(),
          "H6: 批量字号档位匹配");

    // ---- H7 ----
    // text_mask / ink_mask: np.ndarray[uint8, 2D, C-contig] (bool 数组会自动转换)
    // 返回 (dx, dy) 使 text_mask 与 ink_mask 对应窗口交集最大。
    // 注意: 不用 call_guard，因为 request() 需要 GIL；在 lambda 内手动释放 GIL。
    m.def("find_best_offset",
        [](py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast> text_mask,
           py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast> ink_mask,
           int radius) -> std::pair<int, int> {
            auto tb = text_mask.request();
            auto ib = ink_mask.request();
            if (tb.ndim != 2 || ib.ndim != 2)
                throw std::runtime_error("hxnative: masks must be 2-D arrays");
            // request() 在 GIL 持有时完成；以下释放 GIL 执行纯 C++ 搜索
            py::gil_scoped_release release;
            return hxnative::find_best_offset(
                static_cast<const std::uint8_t *>(tb.ptr),
                static_cast<int>(tb.shape[0]), static_cast<int>(tb.shape[1]),
                static_cast<const std::uint8_t *>(ib.ptr),
                static_cast<int>(ib.shape[0]), static_cast<int>(ib.shape[1]),
                radius);
        },
        py::arg("text_mask"), py::arg("ink_mask"), py::arg("radius"),
        "H7: 文字掩码与墨迹掩码最佳偏移搜索 (释放 GIL, uint64_t 批量 popcount)");

    // ---- H8 ----
    // img: np.ndarray[uint8, 3D (H,W,C), C-contig], RGB(3) 或 RGBA(4)
    // bbox: list[int] = [x1, y1, x2, y2]
    // radius: int, 四周扩展半径
    // 返回 (mask_bytes: bytes, out_w: int, out_h: int)
    //   mask_bytes 为紧凑 uint8 数组 (0=白, 1=非白), 形状 (out_h, out_w)
    //   二值化阈值与 Python extract_ink_mask 一致 (PIL L 灰度 < 200)
    m.def("extract_ink_mask_fast",
        [](py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast> img,
           std::vector<int> bbox, int radius) -> std::tuple<std::string, int, int> {
            auto buf = img.request();
            if (buf.ndim != 3)
                throw std::runtime_error("extract_ink_mask_fast: img must be 3D (H,W,C)");
            int img_h = static_cast<int>(buf.shape[0]);
            int img_w = static_cast<int>(buf.shape[1]);
            int img_n = static_cast<int>(buf.shape[2]);
            if (img_n != 3 && img_n != 4)
                throw std::runtime_error("extract_ink_mask_fast: img channels must be 3 (RGB) or 4 (RGBA)");
            if (bbox.size() < 4)
                throw std::runtime_error("extract_ink_mask_fast: bbox must have 4 elements [x1,y1,x2,y2]");
            int out_w = 0, out_h = 0;
            std::string mask;
            {
                // request() 在 GIL 持有时完成；以下释放 GIL 执行纯 C++ 计算
                py::gil_scoped_release release;
                mask = hxnative::extract_ink_mask_fast(
                    static_cast<const std::uint8_t *>(buf.ptr),
                    img_w, img_h, img_n,
                    bbox.data(), static_cast<int>(bbox.size()), radius,
                    &out_w, &out_h);
            }
            return std::make_tuple(mask, out_w, out_h);
        },
        py::arg("img"), py::arg("bbox"), py::arg("radius"),
        "H8: 从图像区域 (bbox 扩展 radius) 提取墨迹掩码 (PIL L 灰度 < 200 二值化, 释放 GIL)");

    m.def("has_native", []() { return true; },
          "检测 _hxnative 是否可用 (Python 端 __init__.py 也提供同名函数)");
}
