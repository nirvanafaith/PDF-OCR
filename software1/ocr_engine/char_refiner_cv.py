"""纯 CV 连通域+投影法字符框精修模块。

使用 OpenCV 的连通域分析和垂直投影法，对 OCR 识别的字符框进行像素级精修。
替代 rapidocr_engine.py 中基于白像素边缘的 _optimize_char_boxes 方法。

核心思路：
1. 从页面图像裁切行图像（带 padding）
2. Otsu 二值化 + 形态学开运算去噪
3. connectedComponentsWithStats 获取连通域（粗框）
4. 合并过分割的小连通域（宽度 < avg_width / 3）
5. 垂直投影法（高斯平滑后）找字间空白（谷值），细化字符 x 边界
6. 粘连字符用 Distance Transform + Watershed 分割（投影法作为 fallback）
7. 切分数与行文本长度匹配则采用 CV 框，否则保留原 OCR 框
"""

import cv2
import numpy as np


def flatten_bbox(box):
    """将 4 角点或扁平格式转为 [x1, y1, x2, y2]。

    支持两种输入格式：
    - 4 角点格式：[[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
    - 扁平格式：[x1, y1, x2, y2]

    参数:
        box: 边界框数据

    返回:
        list: [x1, y1, x2, y2] 扁平格式；无效输入返回 [0, 0, 0, 0]
    """
    if isinstance(box, list) and len(box) == 4 and all(isinstance(p, list) for p in box):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        return [min(xs), min(ys), max(xs), max(ys)]
    elif isinstance(box, list) and len(box) == 4:
        return box
    return [0, 0, 0, 0]


def refine_chars_for_page(page_image, chars_on_page, lines_on_page):
    """对一页的所有行进行CV字符框精修。

    按 line_id 分组字符，对每行调用连通域+投影法精修字符框。
    精修成功的行其字符 box 字段被替换为 CV 框（4角点格式），
    精修失败的行保留原始 OCR 框。

    参数:
        page_image: PIL.Image 页面图像
        chars_on_page: list[dict] 该页的字符列表，每个含 char_id, line_id, char, box, page_num
        lines_on_page: list[dict] 该页的行列表，每个含 line_id, text, box, page_num

    返回:
        list[dict]: 更新后的字符列表（box字段被CV精修的替换，未精修的保留原值）
    """
    # 按 line_id 分组字符
    chars_by_line = {}
    for char in chars_on_page:
        line_id = char.get("line_id", -1)
        if line_id not in chars_by_line:
            chars_by_line[line_id] = []
        chars_by_line[line_id].append(char)

    # 构建 line_id -> line 的映射
    line_map = {}
    for line in lines_on_page:
        line_map[line.get("line_id", -1)] = line

    # 对每行进行 CV 精修
    for line_id, chars_in_line in chars_by_line.items():
        line = line_map.get(line_id)
        if line is None:
            continue

        # 按 char_id 排序，保证从左到右顺序
        chars_in_line.sort(key=lambda c: c.get("char_id", 0))

        line_text = line.get("text", "")
        line_box = line.get("box", [0, 0, 0, 0])
        line_bbox = flatten_bbox(line_box)

        # 只处理字符数与文本长度匹配的行
        if len(chars_in_line) != len(line_text):
            continue
        if len(chars_in_line) == 0:
            continue

        # 执行单行 CV 精修
        refined_boxes = _refine_single_line(page_image, line_bbox, len(line_text))

        if refined_boxes is not None and len(refined_boxes) == len(chars_in_line):
            for char, box in zip(chars_in_line, refined_boxes):
                char["box"] = box

    return chars_on_page


def _refine_single_line(page_image, line_bbox, char_count):
    """对单行进行 CV 字符框精修。

    参数:
        page_image: PIL.Image 页面图像
        line_bbox: [x1, y1, x2, y2] 行边界框（页面绝对坐标）
        char_count: 该行的字符数

    返回:
        list[[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]]: 精修后的字符框列表（页面绝对坐标），
        失败返回 None
    """
    x1, y1, x2, y2 = [int(round(v)) for v in line_bbox]

    # 加 2px padding 裁切行图像
    padding = 2
    img_w, img_h = page_image.size
    crop_x1 = max(0, x1 - padding)
    crop_y1 = max(0, y1 - padding)
    crop_x2 = min(img_w, x2 + padding)
    crop_y2 = min(img_h, y2 + padding)

    if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
        return None

    # 裁切行图像
    line_img = page_image.crop((crop_x1, crop_y1, crop_x2, crop_y2))

    # 转 numpy 数组
    img_array = np.array(line_img)

    # 灰度化
    if len(img_array.shape) == 3:
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_array

    # Otsu 二值化（THRESH_BINARY_INV：文字变白255，背景变黑0）
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 形态学开运算去噪（2x2 kernel）
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    # connectedComponentsWithStats 获取连通域
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    # 过滤小连通域（宽<3 或 高<5），跳过背景（label 0）
    components = []
    for i in range(1, num_labels):
        cx, cy, cw, ch, area = stats[i]
        if cw < 3 or ch < 5:
            continue
        components.append({
            "x1": int(cx), "y1": int(cy),
            "x2": int(cx + cw), "y2": int(cy + ch),
        })

    # 按从左到右排序
    components.sort(key=lambda c: c["x1"])

    if len(components) == 0:
        return None

    # 计算平均字符宽度 avg_width = line_width / char_count
    # line_width 取所有连通域的跨度（max_x2 - min_x1）
    min_x = min(c["x1"] for c in components)
    max_x = max(c["x2"] for c in components)
    line_width = max_x - min_x
    avg_width = line_width / char_count if char_count > 0 else line_width

    # 新增：合并过分割的小连通域（宽度 < avg_width / 3 的并入前一个）
    components = _merge_over_segmented(components, avg_width)

    # 垂直投影：col_sum = binary.sum(axis=0)
    col_sum = binary.sum(axis=0).astype(np.int32)

    # 找投影谷值（高斯平滑后找连续低值区域的中点）作为字符边界
    valleys = _find_projection_valleys(col_sum)

    # 融合：连通域给出粗框，投影法细化 x 边界
    refined_components = _refine_x_by_valleys(components, valleys, col_sum.shape[0])

    # 粘连字符处理：当连通域数 < 字符数时，用 Watershed 分割粘连字符
    if len(refined_components) < char_count:
        refined_components = _split_stuck_by_watershed(
            refined_components, binary, col_sum, char_count, avg_width
        )

    # 验证：CV 切分数 == 字符数?
    if len(refined_components) != char_count:
        return None

    # 对每个框重新计算 y 范围（基于二值图），并映射回页面绝对坐标
    result = []
    for comp in refined_components:
        # 重新计算 y 范围
        new_y1, new_y2 = _compute_y_range(binary, comp["x1"], comp["x2"])
        if new_y1 >= new_y2:
            new_y1, new_y2 = comp["y1"], comp["y2"]

        # 映射回页面绝对坐标
        abs_x1 = comp["x1"] + crop_x1
        abs_y1 = new_y1 + crop_y1
        abs_x2 = comp["x2"] + crop_x1
        abs_y2 = new_y2 + crop_y1

        # 输出 4 角点格式 [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        box = [
            [abs_x1, abs_y1],
            [abs_x2, abs_y1],
            [abs_x2, abs_y2],
            [abs_x1, abs_y2],
        ]
        result.append(box)

    return result


def _find_projection_valleys(col_sum):
    """从垂直投影列和中找谷值（连续低值区域）的中点作为字符边界。

    使用 1D 高斯平滑减少噪点导致的假谷值，再在平滑后的曲线上
    找连续低值区域（< max_val * 0.05）作为谷值。

    参数:
        col_sum: 1D 数组，每列的白像素之和

    返回:
        list[float]: 谷值中点位置列表（字符边界）
    """
    n = len(col_sum)
    if n == 0:
        return []

    # 1D 高斯平滑减少假谷值（核大小 5，基于字符宽度估算）
    col_sum_f = col_sum.astype(np.float32)
    # 转成 (1, n) 用 (5,1) 核沿水平方向平滑
    smoothed = cv2.GaussianBlur(col_sum_f.reshape(1, -1), (5, 1), 0).reshape(-1)

    max_val = smoothed.max()
    if max_val <= 0:
        return []
    # 平滑后的“0”用阈值判断（接近 0 的低值区域）
    threshold = max_val * 0.05

    valleys = []
    i = 0
    while i < n:
        if smoothed[i] < threshold:
            # 找连续低值区域的结束
            j = i
            while j < n and smoothed[j] < threshold:
                j += 1
            # 连续低值区域的中点作为边界
            mid = (i + j - 1) / 2.0
            valleys.append(mid)
            i = j
        else:
            i += 1
    return valleys


def _refine_x_by_valleys(components, valleys, img_width):
    """用投影谷值细化连通域的 x 边界。

    对相邻连通域，用它们之间的投影谷值中点作为分界；
    首尾连通域向外扩展到最近的谷值。

    参数:
        components: 连通域列表，每个含 x1, x2, y1, y2
        valleys: 谷值位置列表
        img_width: 图像宽度

    返回:
        list[dict]: 细化后的连通域列表
    """
    if not components:
        return components

    refined = []
    n = len(components)

    for i, comp in enumerate(components):
        x1, x2 = comp["x1"], comp["x2"]

        # 左侧边界
        if i == 0:
            # 第一个连通域，向左扩展到最近的谷值
            left_valleys = [v for v in valleys if v < x1]
            new_x1 = int(round(left_valleys[-1])) if left_valleys else x1
        else:
            # 与前一个连通域之间的谷值
            prev_x2 = components[i - 1]["x2"]
            between_valleys = [v for v in valleys if prev_x2 <= v <= x1]
            if between_valleys:
                # 取中间的谷值作为分界
                new_x1 = int(round(between_valleys[len(between_valleys) // 2]))
            else:
                # 无谷值（粘连），取中点
                new_x1 = (prev_x2 + x1) // 2

        # 右侧边界
        if i == n - 1:
            # 最后一个连通域，向右扩展到最近的谷值
            right_valleys = [v for v in valleys if v > x2]
            new_x2 = int(round(right_valleys[0])) if right_valleys else x2
        else:
            # 与后一个连通域之间的谷值
            next_x1 = components[i + 1]["x1"]
            between_valleys = [v for v in valleys if x2 <= v <= next_x1]
            if between_valleys:
                new_x2 = int(round(between_valleys[len(between_valleys) // 2]))
            else:
                # 无谷值（粘连），取中点
                new_x2 = (x2 + next_x1) // 2

        # 确保 x1 < x2
        if new_x1 >= new_x2:
            new_x1, new_x2 = x1, x2

        refined.append({
            "x1": new_x1, "y1": comp["y1"],
            "x2": new_x2, "y2": comp["y2"],
        })

    return refined


def _split_stuck_components(components, col_sum, char_count):
    """对宽连通域用投影法拆分，以匹配字符数。

    估算每个连通域包含的字符数（按宽度比例），对包含多个字符的连通域
    用投影谷值拆分。

    参数:
        components: 连通域列表（已排序，已细化 x 边界）
        col_sum: 垂直投影列和
        char_count: 目标字符数

    返回:
        list[dict]: 拆分后的连通域列表
    """
    if not components:
        return components

    # 计算平均字符宽度（基于总宽度和目标字符数）
    total_width = sum(c["x2"] - c["x1"] for c in components)
    avg_width = total_width / char_count if char_count > 0 else total_width

    if avg_width <= 0:
        return components

    # 估算每个连通域包含的字符数
    char_counts_per_comp = []
    for comp in components:
        w = comp["x2"] - comp["x1"]
        n = max(1, int(round(w / avg_width)))
        char_counts_per_comp.append(n)

    # 调整总数匹配 char_count
    _adjust_split_counts(char_counts_per_comp, components, char_count)

    # 对每个连通域拆分
    result = []
    for comp, n in zip(components, char_counts_per_comp):
        if n <= 1:
            result.append(comp)
        else:
            sub_parts = _split_component_by_projection(comp, col_sum, n)
            result.extend(sub_parts)

    return result


def _split_stuck_by_watershed(components, binary, col_sum, char_count, avg_width):
    """用 Watershed 优先分割粘连字符，失败时回退到投影法。

    流程：
    1. 估算每个连通域包含的字符数（按宽度 / avg_width）
    2. 调整总数匹配 char_count
    3. 对每个需拆分的连通域：先尝试 _split_by_watershed，失败则回退到
       _split_component_by_projection
    4. 若整体切分数仍不等于 char_count，最终回退到 _split_stuck_components

    参数:
        components: 连通域列表（已排序，已细化 x 边界）
        binary: 二值图（白字黑底，uint8）
        col_sum: 垂直投影列和
        char_count: 目标字符数
        avg_width: 平均字符宽度

    返回:
        list[dict]: 拆分后的连通域列表
    """
    if not components or avg_width <= 0:
        return _split_stuck_components(components, col_sum, char_count)

    # 估算每个连通域包含的字符数
    char_counts_per_comp = []
    for comp in components:
        w = comp["x2"] - comp["x1"]
        n = max(1, int(round(w / avg_width)))
        char_counts_per_comp.append(n)

    # 调整总数匹配 char_count
    _adjust_split_counts(char_counts_per_comp, components, char_count)

    # 逐连通域拆分：Watershed 优先，投影法回退
    result = []
    for comp, n in zip(components, char_counts_per_comp):
        if n <= 1:
            result.append(comp)
            continue
        sub_parts = _split_by_watershed(binary, comp, n)
        if sub_parts is None or len(sub_parts) != n:
            # Watershed 失败，回退到投影法
            sub_parts = _split_component_by_projection(comp, col_sum, n)
        result.extend(sub_parts)

    # 若整体切分数不匹配，最终回退到纯投影法整体拆分
    if len(result) != char_count:
        result = _split_stuck_components(components, col_sum, char_count)

    return result


def _adjust_split_counts(char_counts_per_comp, components, char_count):
    """调整每个连通域的拆分段数，使总数匹配 char_count。

    参数:
        char_counts_per_comp: 每个连通域的拆分段数列表（会被原地修改）
        components: 连通域列表
        char_count: 目标字符数
    """
    # 减少过多的拆分
    while sum(char_counts_per_comp) > char_count:
        # 找拆分数最多的减 1
        max_val = max(char_counts_per_comp)
        if max_val <= 1:
            break
        idx = char_counts_per_comp.index(max_val)
        char_counts_per_comp[idx] -= 1

    # 增加不足的拆分
    while sum(char_counts_per_comp) < char_count:
        # 找最宽的连通域加 1
        widths = [c["x2"] - c["x1"] for c in components]
        idx = widths.index(max(widths))
        char_counts_per_comp[idx] += 1


def _split_component_by_projection(comp, col_sum, n):
    """将一个连通域用投影谷值拆分为 n 段。

    参数:
        comp: 连通域字典，含 x1, x2, y1, y2
        col_sum: 垂直投影列和
        n: 拆分段数

    返回:
        list[dict]: 拆分后的连通域列表，每段保持原 y 范围
    """
    x1, x2 = comp["x1"], comp["x2"]
    y1, y2 = comp["y1"], comp["y2"]

    if n <= 1 or x2 <= x1:
        return [comp]

    # 在 [x1, x2) 范围内找谷值
    region_col_sum = col_sum[x1:x2]
    local_valleys = _find_projection_valleys(region_col_sum)

    if len(local_valleys) < n - 1:
        # 谷值不足，均分
        width = x2 - x1
        step = width / n
        parts = []
        for i in range(n):
            sub_x1 = int(round(x1 + i * step))
            sub_x2 = int(round(x1 + (i + 1) * step)) if i < n - 1 else x2
            parts.append({"x1": sub_x1, "y1": y1, "x2": sub_x2, "y2": y2})
        return parts

    # 选择 n-1 个谷值作为分割点（均匀选择）
    split_points = []
    if n > 1:
        # 等间隔从谷值列表中选择 n-1 个
        step = len(local_valleys) / n
        for i in range(n - 1):
            idx = int(round((i + 1) * step)) - 1
            if idx < 0:
                idx = 0
            if idx >= len(local_valleys):
                idx = len(local_valleys) - 1
            split_points.append(x1 + local_valleys[idx])

    # 生成 n 段
    split_points.sort()
    parts = []
    prev_x = x1
    for sp in split_points:
        sp_int = int(round(sp))
        if sp_int > prev_x:
            parts.append({"x1": prev_x, "y1": y1, "x2": sp_int, "y2": y2})
        prev_x = sp_int
    parts.append({"x1": prev_x, "y1": y1, "x2": x2, "y2": y2})

    return parts


def _compute_y_range(binary, x1, x2):
    """从二值图中计算 [x1, x2) 范围内的 y 范围。

    参数:
        binary: 二值图（白字黑底，uint8）
        x1, x2: x 范围

    返回:
        tuple[int, int]: (y1, y2) 顶部和底部 y 坐标；无内容返回 (0, 0)
    """
    if x2 <= x1 or x1 < 0 or x2 > binary.shape[1]:
        x1 = max(0, x1)
        x2 = min(binary.shape[1], x2)
        if x2 <= x1:
            return 0, 0

    region = binary[:, x1:x2]
    row_sum = region.sum(axis=1)
    non_zero_rows = np.where(row_sum > 0)[0]
    if len(non_zero_rows) == 0:
        return 0, 0
    return int(non_zero_rows[0]), int(non_zero_rows[-1] + 1)


def _merge_over_segmented(components, avg_width):
    """合并过小相邻连通域。

    遍历排序后的连通域列表，若某个连通域宽度 < avg_width / 3，
    则将其合并到前一个连通域（扩展前一个的 x2，同时扩展 y 范围）。

    参数:
        components: 连通域列表（已按 x1 从左到右排序），每个含 x1,y1,x2,y2
        avg_width: 平均字符宽度，用于判断“过小”

    返回:
        list[dict]: 合并后的连通域列表
    """
    if not components:
        return components

    if avg_width <= 0:
        return components

    threshold = avg_width / 3.0
    merged = [dict(components[0])]
    for comp in components[1:]:
        prev = merged[-1]
        width = comp["x2"] - comp["x1"]
        if width < threshold:
            # 合并到前一个：扩展前一个的 x2 和 y 范围
            prev["x2"] = comp["x2"]
            prev["y1"] = min(prev["y1"], comp["y1"])
            prev["y2"] = max(prev["y2"], comp["y2"])
        else:
            merged.append(dict(comp))
    return merged


def _split_by_watershed(binary, comp, n):
    """使用 Distance Transform + Watershed 算法分割粘连字符。

    流程：
    1. 从二值图中裁出该连通域 ROI（带 padding 保证存在背景）
    2. cv2.distanceTransform（DIST_L2, maskSize=5）距离变换
    3. 用 dilation 找局部峰值（dist == dilated 且高于阈值）作为种子点
    4. 用 connectedComponents 聚类相邻峰值，若峰值数 >= n 取前 n 个
    5. 构建 markers，cv2.watershed 执行分水岭分割
    6. 返回 n 个分割后的连通域（每个含 x1,y1,x2,y2）

    参数:
        binary: 二值图（白字黑底，uint8）
        comp: 连通域字典，含 x1,y1,x2,y2
        n: 需要分割成的段数

    返回:
        list[dict]: n 个分割后的连通域列表，失败返回 None
    """
    if n <= 1:
        return None

    h, w = binary.shape
    x1, y1, x2, y2 = comp["x1"], comp["y1"], comp["x2"], comp["y2"]

    # 加 padding，确保 ROI 内有背景区域供分水岭使用
    pad = 3
    rx1 = max(0, x1 - pad)
    ry1 = max(0, y1 - pad)
    rx2 = min(w, x2 + pad)
    ry2 = min(h, y2 + pad)

    if rx2 <= rx1 or ry2 <= ry1:
        return None

    roi = binary[ry1:ry2, rx1:rx2].copy()
    if roi.sum() == 0:
        return None

    # 距离变换（DIST_L2, maskSize=5）
    dist = cv2.distanceTransform(roi, cv2.DIST_L2, 5)
    max_dist = float(dist.max())
    if max_dist <= 0:
        return None

    # 找局部峰值：用 dilation 找局部最大值，dist == dilated 的点即局部最大值
    # 核大小按估算字符宽度自适应，确保每个字符区域大致产生一个峰值
    est_char_w = max(3.0, (x2 - x1) / float(n))
    ksize = max(3, int(round(est_char_w)))
    if ksize % 2 == 0:
        ksize += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    dilated = cv2.dilate(dist, kernel)
    local_max = (dist == dilated) & (dist > max_dist * 0.3)
    local_max = local_max.astype(np.uint8)

    if local_max.sum() == 0:
        return None

    # 用 connectedComponents 聚类相邻峰值点，得到独立峰值区域
    num_peaks, peak_labels = cv2.connectedComponents(local_max, connectivity=8)
    # num_peaks - 1 为实际峰值数（label 0 是背景）
    if num_peaks - 1 < n:
        # 峰值数量不足 n，返回 None 触发 fallback
        return None

    # 按峰值区域的 max distance 值排序，选取前 n 个作为种子
    peak_values = []
    for i in range(1, num_peaks):
        val = float(dist[peak_labels == i].max())
        peak_values.append((i, val))
    peak_values.sort(key=lambda x: x[1], reverse=True)
    selected_peaks = [pv[0] for pv in peak_values[:n]]

    # 构建 markers（int32）：峰值种子标记为 1..n，其余为 0(unknown)
    # 注意：不标记背景为竞争标签，否则背景会侵占前景；背景像素在提取阶段
    # 通过 (roi > 0) 掩码过滤掉，从而让 n 个种子完整划分前景
    markers = np.zeros(roi.shape, dtype=np.int32)
    for new_label, peak_id in enumerate(selected_peaks, start=1):
        markers[peak_labels == peak_id] = new_label

    # watershed 需要 8 位 3 通道图像
    roi_color = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    cv2.watershed(roi_color, markers)
    # 分割后 markers 中 -1 为分水岭边界线，1..n 为各分割区域

    # 提取 n 个分割区域（仅统计前景像素，忽略背景与边界线）
    components = []
    for label in range(1, n + 1):
        mask = (markers == label) & (roi > 0)
        if mask.sum() == 0:
            continue
        ys, xs = np.where(mask)
        components.append({
            "x1": int(rx1 + xs.min()),
            "y1": int(ry1 + ys.min()),
            "x2": int(rx1 + xs.max() + 1),
            "y2": int(ry1 + ys.max() + 1),
        })

    if len(components) != n:
        return None

    # 按从左到右排序
    components.sort(key=lambda c: c["x1"])
    return components
