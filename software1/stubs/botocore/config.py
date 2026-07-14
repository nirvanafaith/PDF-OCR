"""botocore.config.Config 桩模块（Stub）。

为什么需要这个文件：
    MinerU 的 ``mineru.data.io.s3`` 模块使用 ``Config(s3={...}, retries={...})``
    配置 S3 客户端。本桩模块提供 ``Config`` 类以满足导入，
    实际创建实例时为空操作（不进行任何配置）。

依赖:
    无（纯 Python 桩模块）

调用关系:
    被 mineru.data.io.s3 导入（``from botocore.config import Config``）
"""

from __future__ import annotations

from typing import Any


class Config:
    """botocore 配置桩类。

    接受任意关键字参数但不进行任何实际配置。
    在打包版本中 S3 功能不可用，此桩类仅用于满足导入。
    """

    def __init__(self, **kwargs: Any) -> None:
        """接受任意配置参数（忽略）。"""
        pass
