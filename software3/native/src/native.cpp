// native.cpp — software3 OCR 流水线 C++ 热点加速扩展 (pybind11)
//
// 实现 spec: cpp-embedding-optimization (software3)
//   D.2 longest_true_run_batch: 1D 布尔数组最长连续 True 长度批量计算
//   D.3 pixmap_to_binary_u8:    fitz.Pixmap samples → 二值化 uint8 数组
//   D.4 compute_iou_batch:      批量计算 mask 对的 IoU
//
// 编译: 见同目录 CMakeLists.txt; 缺失时 Python 端自动回落, 详见 __init__.py。

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include "native.h"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <utility>
#include <vector>

namespace py = pybind11;
using namespace native;

// ============================================================================
// D.2: 1D 布尔数组最长连续 True 长度批量计算
// ============================================================================
// 对每个数组用裸指针遍历，单遍累计 max_run。
// bool 数组在 numpy 中以 1 字节存储（0 或 1），可直接按 uint8_t 处理。
// 可选 AVX2 加速：用 _mm256_movemask_epi8 提取 32 字节为一个掩码后用 popcnt
// 统计连续 1，但简单标量循环在分支预测良好的小数组上已足够快；
// 实测 5000 元素以下标量版本性能已超过 numpy，故此处保持简洁实现。

std::vector<int>
native::longest_true_run_batch_impl(const std::vector<const std::uint8_t*>& arrays,
                                     const std::vector<std::size_t>& lengths)
{
    std::vector<int> results;
    results.reserve(arrays.size());
    for (std::size_t i = 0; i < arrays.size(); ++i) {
        const std::uint8_t* p = arrays[i];
        const std::size_t n = lengths[i];
        int max_run = 0;
        int cur = 0;
        for (std::size_t k = 0; k < n; ++k) {
            if (p[k]) {
                ++cur;
                if (cur > max_run) max_run = cur;
            } else {
                cur = 0;
            }
        }
        results.push_back(max_run);
    }
    return results;
}

// ============================================================================
// D.3: fitz.Pixmap samples → 二值化 uint8 数组
// ============================================================================
// 输入：紧凑像素 buffer (samples)，宽，高，通道数 (3=RGB, 4=RGBA)
// 输出：紧凑 uint8 数组 (shape=[height, width])，255=黑色像素, 0=白色像素
// 算法：灰度 = (R+G+B)/3，gray < 128 → 255（黑），否则 0（白）
//       RGBA 时跳过 alpha 通道
//
// 注意：与 Python _pixmap_to_binary 中 np.mean(axis=2) 略有差异：
//   Python 使用 mean，C++ 使用 (R+G+B)/3（整数除法截断）。
//   两者在 (R+G+B) % 3 != 0 时可能差 1，但阈值 128 足够宽容，差异可忽略。
//   若需严格对齐，可改用 (R+G+B+1)/3 (rounding) 或浮点除法。

std::string
native::pixmap_to_binary_u8_impl(const std::uint8_t* samples,
                                   int width, int height, int n)
{
    if (samples == nullptr || width <= 0 || height <= 0 || (n != 3 && n != 4))
        throw std::runtime_error("pixmap_to_binary_u8: invalid arguments");

    const std::size_t out_size = static_cast<std::size_t>(width) * height;
    std::string out;
    out.resize(out_size);

    char* dst = &out[0];
    const int channels = (n == 4) ? 3 : 3;  // 仅 RGB 三通道参与灰度计算
    // RGBA 时跳过 alpha：每像素 n 字节，灰度公式只用前 3 字节
    for (int y = 0; y < height; ++y) {
        const std::uint8_t* row = samples + static_cast<std::ptrdiff_t>(y) * width * n;
        char* dst_row = dst + static_cast<std::ptrdiff_t>(y) * width;
        for (int x = 0; x < width; ++x) {
            const std::uint8_t* px = row + static_cast<std::ptrdiff_t>(x) * n;
            // 灰度 = (R + G + B) / 3
            int gray = (px[0] + px[1] + px[2]) / 3;
            dst_row[x] = (gray < 128) ? '\xFF' : '\x00';
            (void)channels;  // channels 仅用于文档说明，未直接使用
        }
    }
    return out;
}

// ============================================================================
// D.4: 批量计算 mask 对的 IoU
// ============================================================================
// 输入：多对 mask，每个 mask 为 uint8 数组（非零视为前景）
// 输出：每个 mask 对的 IoU 值
// 实现：单遍遍历两 mask 字节，统计 intersection（两字节都非零）
//       与 union（至少一字节非零）像素数，IoU = intersection / union

std::vector<double>
native::compute_iou_batch_impl(const std::vector<const std::uint8_t*>& masks1,
                                const std::vector<const std::uint8_t*>& masks2,
                                const std::vector<int>& widths,
                                const std::vector<int>& heights)
{
    std::vector<double> results;
    results.reserve(masks1.size());
    for (std::size_t i = 0; i < masks1.size(); ++i) {
        const std::uint8_t* m1 = masks1[i];
        const std::uint8_t* m2 = masks2[i];
        int w = widths[i];
        int h = heights[i];
        if (m1 == nullptr || m2 == nullptr || w <= 0 || h <= 0) {
            results.push_back(0.0);
            continue;
        }
        const std::size_t n = static_cast<std::size_t>(w) * h;
        long long intersection = 0;
        long long union_count = 0;
        for (std::size_t k = 0; k < n; ++k) {
            bool a = m1[k] != 0;
            bool b = m2[k] != 0;
            if (a && b) {
                ++intersection;
                ++union_count;
            } else if (a || b) {
                ++union_count;
            }
        }
        if (union_count == 0) {
            results.push_back(0.0);
        } else {
            results.push_back(static_cast<double>(intersection) /
                              static_cast<double>(union_count));
        }
    }
    return results;
}

// ============================================================================
// D.5: 批量计算多对 pixmap 的 IoU（含二值化 + 居中 pad + 形态学膨胀）
// ============================================================================
// 对每对 (red_samples, orig_samples)：
//   1. 二值化：(R+G+B)/3 < 128 → 1（前景），否则 0（背景）；RGBA 时跳过 alpha
//   2. 居中 pad：将两 mask 居中 pad 到 max_h × max_w（pad 值 0）
//   3. 形态学膨胀：3x3 全 1 结构元素，迭代 dilate_radius 次
//      （与 scipy.ndimage.generate_binary_structure(2,2) + binary_dilation 等价）
//   4. IoU = intersection / union（非零视为前景）
//
// 注意：单次调用处理整页所有字符，避免 Python 循环 + 多次跨语言调用开销。

std::vector<double>
native::batch_compute_iou_with_dilate_impl(const std::vector<const std::uint8_t*>& red_samples,
                                             const std::vector<int>& red_w,
                                             const std::vector<int>& red_h,
                                             const std::vector<int>& red_n,
                                             const std::vector<const std::uint8_t*>& orig_samples,
                                             const std::vector<int>& orig_w,
                                             const std::vector<int>& orig_h,
                                             const std::vector<int>& orig_n,
                                             int dilate_radius)
{
    std::vector<double> results;
    const std::size_t M = red_samples.size();
    results.reserve(M);

    for (std::size_t i = 0; i < M; ++i) {
        const std::uint8_t* red_p = red_samples[i];
        const std::uint8_t* orig_p = orig_samples[i];
        int rw = red_w[i], rh = red_h[i], rn = red_n[i];
        int ow = orig_w[i], oh = orig_h[i], on = orig_n[i];

        if (red_p == nullptr || orig_p == nullptr ||
            rw <= 0 || rh <= 0 || (rn != 3 && rn != 4) ||
            ow <= 0 || oh <= 0 || (on != 3 && on != 4)) {
            results.push_back(0.0);
            continue;
        }

        // 1. 二值化为 mask（uint8 0/1）
        std::vector<std::uint8_t> red_mask(static_cast<std::size_t>(rw) * rh, 0);
        std::vector<std::uint8_t> orig_mask(static_cast<std::size_t>(ow) * oh, 0);

        for (int y = 0; y < rh; ++y) {
            const std::uint8_t* row = red_p + static_cast<std::ptrdiff_t>(y) * rw * rn;
            std::uint8_t* dst = red_mask.data() + static_cast<std::ptrdiff_t>(y) * rw;
            for (int x = 0; x < rw; ++x) {
                const std::uint8_t* px = row + static_cast<std::ptrdiff_t>(x) * rn;
                int gray = (px[0] + px[1] + px[2]) / 3;
                dst[x] = (gray < 128) ? 1 : 0;
            }
        }
        for (int y = 0; y < oh; ++y) {
            const std::uint8_t* row = orig_p + static_cast<std::ptrdiff_t>(y) * ow * on;
            std::uint8_t* dst = orig_mask.data() + static_cast<std::ptrdiff_t>(y) * ow;
            for (int x = 0; x < ow; ++x) {
                const std::uint8_t* px = row + static_cast<std::ptrdiff_t>(x) * on;
                int gray = (px[0] + px[1] + px[2]) / 3;
                dst[x] = (gray < 128) ? 1 : 0;
            }
        }

        // 2. 居中 pad 到 max_h × max_w
        int max_h = std::max(rh, oh);
        int max_w = std::max(rw, ow);
        std::vector<std::uint8_t> red_padded(static_cast<std::size_t>(max_h) * max_w, 0);
        std::vector<std::uint8_t> orig_padded(static_cast<std::size_t>(max_h) * max_w, 0);

        // red 居中 pad
        {
            int pad_top = (max_h - rh) / 2;
            int pad_left = (max_w - rw) / 2;
            for (int y = 0; y < rh; ++y) {
                std::memcpy(
                    red_padded.data() + static_cast<std::ptrdiff_t>(y + pad_top) * max_w + pad_left,
                    red_mask.data() + static_cast<std::ptrdiff_t>(y) * rw,
                    static_cast<std::size_t>(rw)
                );
            }
        }
        // orig 居中 pad
        {
            int pad_top = (max_h - oh) / 2;
            int pad_left = (max_w - ow) / 2;
            for (int y = 0; y < oh; ++y) {
                std::memcpy(
                    orig_padded.data() + static_cast<std::ptrdiff_t>(y + pad_top) * max_w + pad_left,
                    orig_mask.data() + static_cast<std::ptrdiff_t>(y) * ow,
                    static_cast<std::size_t>(ow)
                );
            }
        }

        // 3. 形态学膨胀：3x3 全 1 结构元素，迭代 dilate_radius 次
        if (dilate_radius > 0) {
            std::vector<std::uint8_t> buf(static_cast<std::size_t>(max_h) * max_w);
            for (int it = 0; it < dilate_radius; ++it) {
                // 膨胀 red_padded
                std::fill(buf.begin(), buf.end(), 0);
                for (int y = 0; y < max_h; ++y) {
                    int y0 = std::max(0, y - 1);
                    int y1 = std::min(max_h - 1, y + 1);
                    for (int x = 0; x < max_w; ++x) {
                        if (red_padded[static_cast<std::size_t>(y) * max_w + x]) {
                            int x0 = std::max(0, x - 1);
                            int x1 = std::min(max_w - 1, x + 1);
                            for (int yy = y0; yy <= y1; ++yy) {
                                for (int xx = x0; xx <= x1; ++xx) {
                                    buf[static_cast<std::size_t>(yy) * max_w + xx] = 1;
                                }
                            }
                        }
                    }
                }
                std::swap(red_padded, buf);

                // 膨胀 orig_padded
                std::fill(buf.begin(), buf.end(), 0);
                for (int y = 0; y < max_h; ++y) {
                    int y0 = std::max(0, y - 1);
                    int y1 = std::min(max_h - 1, y + 1);
                    for (int x = 0; x < max_w; ++x) {
                        if (orig_padded[static_cast<std::size_t>(y) * max_w + x]) {
                            int x0 = std::max(0, x - 1);
                            int x1 = std::min(max_w - 1, x + 1);
                            for (int yy = y0; yy <= y1; ++yy) {
                                for (int xx = x0; xx <= x1; ++xx) {
                                    buf[static_cast<std::size_t>(yy) * max_w + xx] = 1;
                                }
                            }
                        }
                    }
                }
                std::swap(orig_padded, buf);
            }
        }

        // 4. IoU = intersection / union
        long long intersection = 0;
        long long union_count = 0;
        const std::size_t total = static_cast<std::size_t>(max_h) * max_w;
        for (std::size_t k = 0; k < total; ++k) {
            bool a = red_padded[k] != 0;
            bool b = orig_padded[k] != 0;
            if (a && b) {
                ++intersection;
                ++union_count;
            } else if (a || b) {
                ++union_count;
            }
        }
        if (union_count == 0) {
            results.push_back(0.0);
        } else {
            results.push_back(static_cast<double>(intersection) /
                              static_cast<double>(union_count));
        }
    }
    return results;
}

// ============================================================================
// D.6: 批量计算单对 pixmap 在多个像素平移下的 IoU
// ============================================================================
// 与 D.5 的二值化/pad/dilate 逻辑完全一致，但只处理一对 pixmap，
// 且对膨胀后的 orig 做多个像素平移，每个平移计算一次 IoU。
// shift 方向：shifted(y,x) = orig_dilated(y+dy_px, x+dx_px) if in bounds else 0
// （原字形在临时页面内平移 (-dx_pt,-dy_pt)，像素空间为 (-dx_px,-dy_px)，
//   取位置 (y,x) 的值需查 orig_dilated(y+dy_px, x+dx_px)）

std::vector<double>
native::compute_iou_with_shifts_impl(
    const std::uint8_t* red_samples, int red_w, int red_h, int red_n,
    const std::uint8_t* orig_samples, int orig_w, int orig_h, int orig_n,
    const std::vector<std::pair<int,int>>& shifts,
    int dilate_radius)
{
    if (red_samples == nullptr || orig_samples == nullptr ||
        red_w <= 0 || red_h <= 0 || (red_n != 3 && red_n != 4) ||
        orig_w <= 0 || orig_h <= 0 || (orig_n != 3 && orig_n != 4)) {
        return std::vector<double>(shifts.size(), 0.0);
    }

    // 1. 二值化为 mask（uint8 0/1）
    std::vector<std::uint8_t> red_mask(static_cast<std::size_t>(red_w) * red_h, 0);
    std::vector<std::uint8_t> orig_mask(static_cast<std::size_t>(orig_w) * orig_h, 0);

    for (int y = 0; y < red_h; ++y) {
        const std::uint8_t* row = red_samples + static_cast<std::ptrdiff_t>(y) * red_w * red_n;
        std::uint8_t* dst = red_mask.data() + static_cast<std::ptrdiff_t>(y) * red_w;
        for (int x = 0; x < red_w; ++x) {
            const std::uint8_t* px = row + static_cast<std::ptrdiff_t>(x) * red_n;
            int gray = (px[0] + px[1] + px[2]) / 3;
            dst[x] = (gray < 128) ? 1 : 0;
        }
    }
    for (int y = 0; y < orig_h; ++y) {
        const std::uint8_t* row = orig_samples + static_cast<std::ptrdiff_t>(y) * orig_w * orig_n;
        std::uint8_t* dst = orig_mask.data() + static_cast<std::ptrdiff_t>(y) * orig_w;
        for (int x = 0; x < orig_w; ++x) {
            const std::uint8_t* px = row + static_cast<std::ptrdiff_t>(x) * orig_n;
            int gray = (px[0] + px[1] + px[2]) / 3;
            dst[x] = (gray < 128) ? 1 : 0;
        }
    }

    // 2. 居中 pad 到 max_h × max_w
    int max_h = std::max(red_h, orig_h);
    int max_w = std::max(red_w, orig_w);
    std::vector<std::uint8_t> red_padded(static_cast<std::size_t>(max_h) * max_w, 0);
    std::vector<std::uint8_t> orig_padded(static_cast<std::size_t>(max_h) * max_w, 0);

    {
        int pad_top = (max_h - red_h) / 2;
        int pad_left = (max_w - red_w) / 2;
        for (int y = 0; y < red_h; ++y) {
            std::memcpy(
                red_padded.data() + static_cast<std::ptrdiff_t>(y + pad_top) * max_w + pad_left,
                red_mask.data() + static_cast<std::ptrdiff_t>(y) * red_w,
                static_cast<std::size_t>(red_w)
            );
        }
    }
    {
        int pad_top = (max_h - orig_h) / 2;
        int pad_left = (max_w - orig_w) / 2;
        for (int y = 0; y < orig_h; ++y) {
            std::memcpy(
                orig_padded.data() + static_cast<std::ptrdiff_t>(y + pad_top) * max_w + pad_left,
                orig_mask.data() + static_cast<std::ptrdiff_t>(y) * orig_w,
                static_cast<std::size_t>(orig_w)
            );
        }
    }

    // 3. 形态学膨胀：3x3 全 1 结构元素，迭代 dilate_radius 次
    if (dilate_radius > 0) {
        std::vector<std::uint8_t> buf(static_cast<std::size_t>(max_h) * max_w);
        for (int it = 0; it < dilate_radius; ++it) {
            // 膨胀 red_padded
            std::fill(buf.begin(), buf.end(), 0);
            for (int y = 0; y < max_h; ++y) {
                int y0 = std::max(0, y - 1);
                int y1 = std::min(max_h - 1, y + 1);
                for (int x = 0; x < max_w; ++x) {
                    if (red_padded[static_cast<std::size_t>(y) * max_w + x]) {
                        int x0 = std::max(0, x - 1);
                        int x1 = std::min(max_w - 1, x + 1);
                        for (int yy = y0; yy <= y1; ++yy) {
                            for (int xx = x0; xx <= x1; ++xx) {
                                buf[static_cast<std::size_t>(yy) * max_w + xx] = 1;
                            }
                        }
                    }
                }
            }
            std::swap(red_padded, buf);

            // 膨胀 orig_padded
            std::fill(buf.begin(), buf.end(), 0);
            for (int y = 0; y < max_h; ++y) {
                int y0 = std::max(0, y - 1);
                int y1 = std::min(max_h - 1, y + 1);
                for (int x = 0; x < max_w; ++x) {
                    if (orig_padded[static_cast<std::size_t>(y) * max_w + x]) {
                        int x0 = std::max(0, x - 1);
                        int x1 = std::min(max_w - 1, x + 1);
                        for (int yy = y0; yy <= y1; ++yy) {
                            for (int xx = x0; xx <= x1; ++xx) {
                                buf[static_cast<std::size_t>(yy) * max_w + xx] = 1;
                            }
                        }
                    }
                }
            }
            std::swap(orig_padded, buf);
        }
    }

    // 4. 对每个 shift 计算 IoU
    // shifted(y,x) = orig_padded(y+dy_px, x+dx_px) if in bounds else 0
    std::vector<double> results;
    results.reserve(shifts.size());
    for (const auto& shift : shifts) {
        int dx_px = shift.first;
        int dy_px = shift.second;
        long long intersection = 0;
        long long union_count = 0;
        for (int y = 0; y < max_h; ++y) {
            for (int x = 0; x < max_w; ++x) {
                bool a = red_padded[static_cast<std::size_t>(y) * max_w + x] != 0;
                int sy = y + dy_px;
                int sx = x + dx_px;
                bool b = (sy >= 0 && sy < max_h && sx >= 0 && sx < max_w)
                             ? (orig_padded[static_cast<std::size_t>(sy) * max_w + sx] != 0)
                             : false;
                if (a && b) {
                    ++intersection;
                    ++union_count;
                } else if (a || b) {
                    ++union_count;
                }
            }
        }
        if (union_count == 0) {
            results.push_back(0.0);
        } else {
            results.push_back(static_cast<double>(intersection) /
                              static_cast<double>(union_count));
        }
    }
    return results;
}

// ============================================================================
// pybind11 绑定
// ============================================================================

PYBIND11_MODULE(_native, m) {
    m.doc() = "software3 OCR 流水线 C++ 热点加速扩展 (pybind11)";

    // ---- D.2: longest_true_run_batch ----
    // arrays: list[np.ndarray[bool, 1D]]（bool 数组在 numpy 中以 1 字节存储）
    // 返回 list[int]，每个数组的最长连续 True 长度
    // 注意：lambda 内需访问 Python list/numpy 对象，故 request() 在 GIL 持有时完成；
    //       随后手动释放 GIL 执行纯 C++ 计算。
    m.def("longest_true_run_batch",
          [](std::vector<py::array_t<bool>> arrays) -> std::vector<int> {
              std::vector<const std::uint8_t*> ptrs;
              std::vector<std::size_t> lengths;
              ptrs.reserve(arrays.size());
              lengths.reserve(arrays.size());
              for (auto& arr : arrays) {
                  auto buf = arr.request();
                  if (buf.ndim != 1)
                      throw std::runtime_error("longest_true_run_batch: arrays must be 1-D");
                  ptrs.push_back(static_cast<const std::uint8_t*>(buf.ptr));
                  lengths.push_back(static_cast<std::size_t>(buf.shape[0]));
              }
              std::vector<int> results;
              {
                  py::gil_scoped_release release;
                  results = native::longest_true_run_batch_impl(ptrs, lengths);
              }
              return results;
          },
          py::arg("arrays"),
          "D.2: 批量计算 1D 布尔数组的最长连续 True 长度");

    // ---- D.3: pixmap_to_binary_u8 ----
    // samples: bytes (fitz.Pixmap.samples)，width, height, n (3=RGB, 4=RGBA)
    // 返回 np.ndarray[uint8, 2D (height, width)]，255=黑色, 0=白色
    // 注意：lambda 内构造 numpy 数组需 GIL，故仅将中间 C++ 计算释放 GIL。
    m.def("pixmap_to_binary_u8",
          [](py::bytes samples, int width, int height, int n) -> py::array_t<std::uint8_t> {
              std::string s = samples;
              const std::size_t expected = static_cast<std::size_t>(width) *
                                           static_cast<std::size_t>(height) *
                                           static_cast<std::size_t>(n);
              if (s.size() < expected) {
                  throw std::runtime_error(
                      "pixmap_to_binary_u8: samples too small (got " +
                      std::to_string(s.size()) + " bytes, need " +
                      std::to_string(expected) + " bytes for " +
                      std::to_string(width) + "x" + std::to_string(height) +
                      "x" + std::to_string(n) + ")");
              }
              const std::uint8_t* ptr =
                  reinterpret_cast<const std::uint8_t*>(s.data());
              std::string out;
              {
                  py::gil_scoped_release release;
                  out = native::pixmap_to_binary_u8_impl(ptr, width, height, n);
              }
              // 零拷贝构造 numpy 数组：将 std::string 的内容移入 capsule 管理的 buffer
              std::size_t out_size = out.size();
              char* buf = new char[out_size];
              std::memcpy(buf, out.data(), out_size);
              py::capsule free_cap(buf, [](void* p) {
                  delete[] static_cast<char*>(p);
              });
              py::array_t<std::uint8_t> result(
                  {height, width},
                  {width, 1},
                  reinterpret_cast<std::uint8_t*>(buf),
                  free_cap
              );
              return result;
          },
          py::arg("samples"),
          py::arg("width"),
          py::arg("height"),
          py::arg("n"),
          "D.3: fitz.Pixmap samples -> 二值化 uint8 数组 (255=黑, 0=白)");

    // ---- D.4: compute_iou_batch ----
    // mask_pairs: list[(mask1_bytes, mask2_bytes, width, height)]
    // 每个 mask 为 uint8 数组（非零视为前景），shape = (height, width)
    // 返回 list[float]，每个 mask 对的 IoU 值
    m.def("compute_iou_batch",
          [](std::vector<std::tuple<py::bytes, py::bytes, int, int>> mask_pairs)
          -> std::vector<double> {
              std::vector<std::string> m1_storage;
              std::vector<std::string> m2_storage;
              std::vector<const std::uint8_t*> masks1;
              std::vector<const std::uint8_t*> masks2;
              std::vector<int> widths;
              std::vector<int> heights;
              m1_storage.reserve(mask_pairs.size());
              m2_storage.reserve(mask_pairs.size());
              masks1.reserve(mask_pairs.size());
              masks2.reserve(mask_pairs.size());
              widths.reserve(mask_pairs.size());
              heights.reserve(mask_pairs.size());
              for (auto& pair : mask_pairs) {
                  std::string s1 = std::get<0>(pair);
                  std::string s2 = std::get<1>(pair);
                  int w = std::get<2>(pair);
                  int h = std::get<3>(pair);
                  const std::size_t expected =
                      static_cast<std::size_t>(w) * static_cast<std::size_t>(h);
                  if (s1.size() < expected || s2.size() < expected) {
                      throw std::runtime_error(
                          "compute_iou_batch: mask bytes too small (expected " +
                          std::to_string(expected) + " bytes for " +
                          std::to_string(w) + "x" + std::to_string(h) + ")");
                  }
                  m1_storage.push_back(std::move(s1));
                  m2_storage.push_back(std::move(s2));
                  widths.push_back(w);
                  heights.push_back(h);
              }
              for (std::size_t i = 0; i < m1_storage.size(); ++i) {
                  masks1.push_back(
                      reinterpret_cast<const std::uint8_t*>(m1_storage[i].data()));
                  masks2.push_back(
                      reinterpret_cast<const std::uint8_t*>(m2_storage[i].data()));
              }
              std::vector<double> results;
              {
                  py::gil_scoped_release release;
                  results = native::compute_iou_batch_impl(masks1, masks2, widths, heights);
              }
              return results;
          },
          py::arg("mask_pairs"),
          "D.4: 批量计算 mask 对的 IoU（intersection / union）");

    // ---- D.5: batch_compute_iou_with_dilate ----
    // pairs: list[(red_samples, red_w, red_h, red_n, orig_samples, orig_w, orig_h, orig_n)]
    // red_samples/orig_samples: bytes (fitz.Pixmap.samples)
    // 返回 list[float]，每对的 IoU 值
    m.def("batch_compute_iou_with_dilate",
          [](std::vector<std::tuple<py::bytes, int, int, int,
                                     py::bytes, int, int, int>> pairs,
             int dilate_radius) -> std::vector<double> {
              std::vector<std::string> red_storage;
              std::vector<std::string> orig_storage;
              std::vector<const std::uint8_t*> red_ptrs;
              std::vector<const std::uint8_t*> orig_ptrs;
              std::vector<int> red_w, red_h, red_n, orig_w, orig_h, orig_n;
              red_storage.reserve(pairs.size());
              orig_storage.reserve(pairs.size());
              red_ptrs.reserve(pairs.size());
              orig_ptrs.reserve(pairs.size());
              red_w.reserve(pairs.size());
              red_h.reserve(pairs.size());
              red_n.reserve(pairs.size());
              orig_w.reserve(pairs.size());
              orig_h.reserve(pairs.size());
              orig_n.reserve(pairs.size());
              for (auto& p : pairs) {
                  std::string rs = std::get<0>(p);
                  std::string os = std::get<4>(p);
                  red_storage.push_back(std::move(rs));
                  orig_storage.push_back(std::move(os));
                  red_w.push_back(std::get<1>(p));
                  red_h.push_back(std::get<2>(p));
                  red_n.push_back(std::get<3>(p));
                  orig_w.push_back(std::get<5>(p));
                  orig_h.push_back(std::get<6>(p));
                  orig_n.push_back(std::get<7>(p));
              }
              for (std::size_t i = 0; i < red_storage.size(); ++i) {
                  red_ptrs.push_back(
                      reinterpret_cast<const std::uint8_t*>(red_storage[i].data()));
                  orig_ptrs.push_back(
                      reinterpret_cast<const std::uint8_t*>(orig_storage[i].data()));
              }
              std::vector<double> results;
              {
                  py::gil_scoped_release release;
                  results = native::batch_compute_iou_with_dilate_impl(
                      red_ptrs, red_w, red_h, red_n,
                      orig_ptrs, orig_w, orig_h, orig_n,
                      dilate_radius);
              }
              return results;
          },
          py::arg("pairs"),
          py::arg("dilate_radius") = 3,
          "D.5: 批量计算多对 pixmap 的 IoU（含二值化 + 居中 pad + 形态学膨胀）");

    // ---- D.6: compute_iou_with_shifts ----
    // red_samples/orig_samples: bytes (fitz.Pixmap.samples)
    // shifts: list[(dx_px, dy_px)] 像素平移列表
    // 返回 list[float]，每个平移下的 IoU 值
    m.def("compute_iou_with_shifts",
          [](py::bytes red_samples, int red_w, int red_h, int red_n,
             py::bytes orig_samples, int orig_w, int orig_h, int orig_n,
             std::vector<std::pair<int,int>> shifts,
             int dilate_radius) -> std::vector<double> {
              std::string rs = red_samples;
              std::string os = orig_samples;
              const std::size_t red_expected =
                  static_cast<std::size_t>(red_w) *
                  static_cast<std::size_t>(red_h) *
                  static_cast<std::size_t>(red_n);
              const std::size_t orig_expected =
                  static_cast<std::size_t>(orig_w) *
                  static_cast<std::size_t>(orig_h) *
                  static_cast<std::size_t>(orig_n);
              if (rs.size() < red_expected) {
                  throw std::runtime_error(
                      "compute_iou_with_shifts: red_samples too small (got " +
                      std::to_string(rs.size()) + " bytes, need " +
                      std::to_string(red_expected) + " bytes for " +
                      std::to_string(red_w) + "x" + std::to_string(red_h) +
                      "x" + std::to_string(red_n) + ")");
              }
              if (os.size() < orig_expected) {
                  throw std::runtime_error(
                      "compute_iou_with_shifts: orig_samples too small (got " +
                      std::to_string(os.size()) + " bytes, need " +
                      std::to_string(orig_expected) + " bytes for " +
                      std::to_string(orig_w) + "x" + std::to_string(orig_h) +
                      "x" + std::to_string(orig_n) + ")");
              }
              const std::uint8_t* red_ptr =
                  reinterpret_cast<const std::uint8_t*>(rs.data());
              const std::uint8_t* orig_ptr =
                  reinterpret_cast<const std::uint8_t*>(os.data());
              std::vector<double> results;
              {
                  py::gil_scoped_release release;
                  results = native::compute_iou_with_shifts_impl(
                      red_ptr, red_w, red_h, red_n,
                      orig_ptr, orig_w, orig_h, orig_n,
                      shifts, dilate_radius);
              }
              return results;
          },
          py::arg("red_samples"),
          py::arg("red_w"), py::arg("red_h"), py::arg("red_n"),
          py::arg("orig_samples"),
          py::arg("orig_w"), py::arg("orig_h"), py::arg("orig_n"),
          py::arg("shifts"),
          py::arg("dilate_radius") = 3,
          "D.6: 批量计算单对 pixmap 在多个像素平移下的 IoU（含二值化+pad+膨胀）");

    // 检测函数：Python 端 __init__.py 可调用此判断 native 是否真实可用
    m.def("has_native", []() { return true; },
          "检测 _native 模块是否可用");
}
