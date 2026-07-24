#pragma once

// native.h — software3 OCR 流水线 C++ 热点加速模块
//
// 本扩展为 software3/ocr_engine/vector_pdf_ocr.py 中三个性能热点提供加速：
//   D.2 longest_true_run_batch: 1D 布尔数组最长连续 True 长度批量计算
//   D.3 pixmap_to_binary_u8:    fitz.Pixmap samples → 二值化 uint8 数组
//   D.4 compute_iou_batch:      批量计算 mask 对的 IoU
//
// 设计原则（继承 software2/native/hxnative.h）：
//   1. 不依赖 fitz / numpy C-API，只处理裸像素 buffer 与 numpy 数组
//   2. 所有热点函数在 lambda 内手动释放 GIL（request() 仍在 GIL 内完成）
//   3. 缺失时由 Python 层 native/__init__.py 自动回落到纯 Python 实现

#include <cstdint>
#include <cstddef>
#include <string>
#include <utility>
#include <vector>

namespace native {

// ---- D.2: 1D 布尔数组最长连续 True 长度批量计算 ----------------------------
// 输入：多个 1D 布尔 numpy 数组（每个数组元素非零视为 True）
// 输出：每个数组的最长连续 True 长度列表
// 实现：对每个数组用裸指针遍历，单遍累计 max_run
std::vector<int>
longest_true_run_batch_impl(const std::vector<const std::uint8_t*>& arrays,
                            const std::vector<std::size_t>& lengths);

// ---- D.3: fitz.Pixmap samples → 二值化 uint8 数组 -------------------------
// 输入：紧凑像素 buffer (samples)，宽，高，通道数 (3=RGB, 4=RGBA)
// 输出：紧凑 uint8 数组 (shape=[height, width])，255=黑色像素, 0=白色像素
// 算法：灰度 = (R+G+B)/3，gray < 128 → 255（黑），否则 0（白）
//       RGBA 时跳过 alpha 通道
std::string
pixmap_to_binary_u8_impl(const std::uint8_t* samples,
                          int width, int height, int n);

// ---- D.4: 批量计算 mask 对的 IoU -----------------------------------------
// 输入：多个 (mask1_bytes, mask2_bytes, width, height) 元组
//       每个 mask 为 uint8 数组，非零视为前景
// 输出：每个 mask 对的 IoU 值（intersection / union，union=0 时返回 0.0）
// 实现：单遍遍历两 mask 字节，统计 intersection 与 union 像素数
std::vector<double>
compute_iou_batch_impl(const std::vector<const std::uint8_t*>& masks1,
                       const std::vector<const std::uint8_t*>& masks2,
                       const std::vector<int>& widths,
                       const std::vector<int>& heights);

// D.5: 批量计算多对 pixmap 的 IoU（含二值化 + 居中 pad + 形态学膨胀）
// 输入：多对 pixmap 的原始 samples + 尺寸 + 通道数
// 输出：每对的 IoU 值
std::vector<double>
batch_compute_iou_with_dilate_impl(const std::vector<const std::uint8_t*>& red_samples,
                                     const std::vector<int>& red_w,
                                     const std::vector<int>& red_h,
                                     const std::vector<int>& red_n,
                                     const std::vector<const std::uint8_t*>& orig_samples,
                                     const std::vector<int>& orig_w,
                                     const std::vector<int>& orig_h,
                                     const std::vector<int>& orig_n,
                                     int dilate_radius);

// ---- D.6: 批量计算单对 pixmap 在多个像素平移下的 IoU ---------------------
// 输入：一对 pixmap 的原始 samples + 尺寸 + 通道数 + N 个像素平移 (dx_px, dy_px)
// 输出：每个平移下的 IoU 值
// 算法：二值化 → 居中 pad → 形态学膨胀（仅一次）→ 对每个 shift 平移 orig_dilated 计算 IoU
// shift 方向：shifted(y,x) = orig_dilated(y+dy_px, x+dx_px) if in bounds else 0
std::vector<double>
compute_iou_with_shifts_impl(const std::uint8_t* red_samples, int red_w, int red_h, int red_n,
                             const std::uint8_t* orig_samples, int orig_w, int orig_h, int orig_n,
                             const std::vector<std::pair<int,int>>& shifts,
                             int dilate_radius);

}  // namespace native
