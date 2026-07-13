"""文字对齐算法模块。

提供文字掩码与背景墨迹掩码的对齐能力，用于在精修流程中
将渲染文字与原始扫描背景中的墨迹进行最佳匹配对齐。
"""

from alignment.text_aligner import align_text_to_background

__all__ = ["align_text_to_background"]
