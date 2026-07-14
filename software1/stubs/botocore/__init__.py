"""botocore 桩模块（Stub）。

为什么需要这个文件：
    MinerU 的 ``mineru.data.io.s3`` 模块在模块级别 ``from botocore.config import Config``，
    需要 botocore 包存在以完成导入。本桩模块提供空的 botocore 包结构。

依赖:
    无（纯 Python 桩模块）

调用关系:
    被 mineru.data.io.s3 导入（``from botocore.config import Config``）
    被 PyInstaller 通过 pathex 优先解析（替代真实 botocore 包）
"""

from __future__ import annotations
