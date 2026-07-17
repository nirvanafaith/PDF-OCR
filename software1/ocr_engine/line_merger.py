"""行合并后处理模块。

使用 DBSCAN 聚类算法对同基线的行进行合并，
修复 OCR 检测阶段因行中间空格导致的行分割问题。

合并策略:
- 按页分组，依据 bbox 高宽比判定页面方向（横排/竖排）
- 横排页: DBSCAN(eps=median_height*0.3) 按 y 中心聚类，同簇按 x 排序
- 竖排页: DBSCAN(eps=median_width*0.3) 按 x 中心聚类，同簇按 y 排序
- 合并: bbox 取并集, text 用空格连接
- 合并后 line_id/char_id 从 0 全局连续重映射
"""

import numpy as np
from sklearn.cluster import DBSCAN
from models.data_models import flatten_bbox


def _is_vertical_page(bboxes):
    """判断页面是否为竖排方向。

    通过统计高度大于宽度的 bbox 数量来判定页面方向：竖排页中
    绝大多数字符 bbox 呈"高瘦"形态（h > w）。

    Args:
        bboxes: 扁平 bbox 列表 [[x1, y1, x2, y2], ...]

    Returns:
        bool: 竖排 bbox 占多数（>50%）返回 True，否则 False；空列表返回 False
    """
    if not bboxes:
        return False
    vert_count = 0
    for b in bboxes:
        h = b[3] - b[1]
        w = b[2] - b[0]
        if h > w:
            vert_count += 1
    return vert_count > len(bboxes) * 0.5


def merge_lines(lines, chars):
    """合并同基线的行。

    Args:
        lines: 行列表，每个 dict 含 line_id/page_num/text/box/score
        chars: 字符列表，每个 dict 含 char_id/line_id/page_num/char/box/score

    Returns:
        (merged_lines, merged_chars): 合并后的行列表和字符列表（新对象，不修改输入）
    """
    # 空输入直接返回
    if not lines:
        return [], []

    # 按 page_num 分组行
    lines_by_page = {}
    for line in lines:
        page_num = line.get("page_num", 0)
        lines_by_page.setdefault(page_num, []).append(line)

    merged_lines = []
    # old_line_id -> new_line_id 的映射
    old_to_new_line_id = {}
    # new_line_id -> 该行所属页面是否竖排 的映射（供 chars 排序选择轴）
    line_id_to_vertical = {}

    # 按页顺序处理
    for page_num in sorted(lines_by_page.keys()):
        page_lines = lines_by_page[page_num]

        # 提取每行的扁平 bbox 及几何信息
        bboxes = [flatten_bbox(line.get("box", [0, 0, 0, 0])) for line in page_lines]
        y_centers = np.array([(b[1] + b[3]) / 2.0 for b in bboxes])
        heights = np.array([(b[3] - b[1]) for b in bboxes], dtype=float)
        x_centers = np.array([(b[0] + b[2]) / 2.0 for b in bboxes])

        # 判断页面方向：竖排页按列方向（x 中心）聚类，横排页按基线（y 中心）聚类
        is_vertical = _is_vertical_page(bboxes)

        if is_vertical:
            # 竖排页：以中位宽度作为 eps 基准；为 0 时用默认值避免退化
            widths = np.array([(b[2] - b[0]) for b in bboxes], dtype=float)
            median_width = float(np.median(widths)) if len(widths) > 0 else 0.0
            eps = median_width * 0.3 if median_width > 0 else 5.0
            cluster_centers = x_centers
            # 竖排从上到下阅读，簇内按 y 中心升序
            sort_centers = y_centers
        else:
            # 横排页：中位高度作为 eps 基准；为 0 时用默认值避免退化
            median_height = float(np.median(heights)) if len(heights) > 0 else 0.0
            eps = median_height * 0.3 if median_height > 0 else 5.0
            cluster_centers = y_centers
            # 横排从左到右阅读，簇内按 x 中心升序
            sort_centers = x_centers

        # DBSCAN 聚类（min_samples=1 保证单行也能成簇）
        dbscan = DBSCAN(eps=eps, min_samples=1)
        labels = dbscan.fit_predict(cluster_centers.reshape(-1, 1))

        # 按簇分组行的原始索引
        clusters = {}
        for idx, label in enumerate(labels):
            clusters.setdefault(int(label), []).append(idx)

        # 对每个簇按阅读序排序合并
        for indices in clusters.values():
            indices_sorted = sorted(indices, key=lambda i: sort_centers[i])
            cluster_lines = [page_lines[i] for i in indices_sorted]

            # bbox 取并集 (min x1/y1, max x2/y2)
            min_x1 = min(bboxes[i][0] for i in indices_sorted)
            min_y1 = min(bboxes[i][1] for i in indices_sorted)
            max_x2 = max(bboxes[i][2] for i in indices_sorted)
            max_y2 = max(bboxes[i][3] for i in indices_sorted)

            # text 用空格连接（全部补空格）
            text = ' '.join(line.get("text", "") for line in cluster_lines)

            # score 按字符数（文本长度）加权平均
            weights = [len(line.get("text", "")) for line in cluster_lines]
            total_weight = sum(weights)
            if total_weight > 0:
                score = sum(
                    line.get("score", 0.0) * w
                    for line, w in zip(cluster_lines, weights)
                ) / total_weight
            else:
                score = sum(line.get("score", 0.0) for line in cluster_lines) / len(cluster_lines)

            # 新行对象，bbox 保持 4 角点格式
            new_line = {
                "text": text,
                "box": [[min_x1, min_y1], [max_x2, min_y1], [max_x2, max_y2], [min_x1, max_y2]],
                "score": score,
                "page_num": page_num,
            }
            new_line_id = len(merged_lines)
            merged_lines.append(new_line)
            # 记录新行所属页面方向，供后续 chars 排序选择轴
            line_id_to_vertical[new_line_id] = is_vertical

            # 记录该簇内所有旧行 id 到新行 id 的映射
            for line in cluster_lines:
                old_to_new_line_id[line.get("line_id")] = new_line_id

    # 全局 line_id 从 0 连续重映射
    for new_id, line in enumerate(merged_lines):
        line["line_id"] = new_id

    # chars 的 line_id 按映射更新（构造新对象，不修改输入）
    merged_chars = []
    for char in chars:
        old_line_id = char.get("line_id")
        new_line_id = old_to_new_line_id.get(old_line_id)
        if new_line_id is None:
            # 找不到对应行映射的字符跳过（正常数据不应发生）
            continue
        new_char = dict(char)
        new_char["line_id"] = new_line_id
        merged_chars.append(new_char)

    # 同新行内按阅读序排序：竖排页按 y 中心升序，横排页按 x 中心升序
    def _char_sort_key(c):
        b = flatten_bbox(c.get("box", [0, 0, 0, 0]))
        if line_id_to_vertical.get(c["line_id"], False):
            # 竖排：从上到下，按 y 中心升序
            return (b[1] + b[3]) / 2.0
        # 横排：从左到右，按 x 中心升序
        return (b[0] + b[2]) / 2.0

    merged_chars.sort(key=lambda c: (c["line_id"], _char_sort_key(c)))

    # char_id 从 0 连续重映射
    for new_id, char in enumerate(merged_chars):
        char["char_id"] = new_id

    return merged_lines, merged_chars
