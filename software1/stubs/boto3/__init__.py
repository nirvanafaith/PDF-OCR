"""boto3 桩模块（Stub）。

为什么需要这个文件：
    MinerU 的 ``mineru.data.io.s3`` 模块在模块级别 ``import boto3``，
    即使软件1仅处理本地 PDF 文件（不使用 S3），导入链也会触发对 boto3 的依赖。
    包含完整 boto3/botocore 包会导致 PyInstaller 重新分类步骤耗时过长
   （botocore 有数千个 AWS 服务定义 JSON 数据文件）。

    本桩模块提供最小接口以满足导入，在实际调用 S3 功能时抛出明确的错误提示。

依赖:
    无（纯 Python 桩模块）

调用关系:
    被 mineru.data.io.s3 导入（``boto3.client``）
    被 PyInstaller 通过 pathex 优先解析（替代真实 boto3 包）
"""

from __future__ import annotations

from typing import Any


class _S3ClientStub:
    """S3 客户端桩对象，任何方法调用均抛出 RuntimeError。"""

    _ERROR_MSG = (
        "S3 功能不可用：软件1 打包时未包含 boto3 完整运行时。"
        "如需 S3 支持，请安装完整版 boto3（pip install boto3）。"
    )

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(self._ERROR_MSG)


def client(service_name: str = "s3", **kwargs: Any) -> _S3ClientStub:
    """创建 S3 客户端桩对象。

    返回的桩对象在任何方法调用时抛出 RuntimeError，
    提示用户 S3 功能在打包版本中不可用。
    """
    return _S3ClientStub()


def resource(service_name: str, **kwargs: Any) -> _S3ClientStub:
    """创建 AWS 资源桩对象（与 client 行为一致）。"""
    return _S3ClientStub()


def setup_default_session(**kwargs: Any) -> None:
    """桩函数：设置默认会话（空操作）。"""
    pass


class Session:
    """boto3.session.Session 桩类。"""

    def __init__(self, **kwargs: Any) -> None:
        pass

    def client(self, service_name: str = "s3", **kwargs: Any) -> _S3ClientStub:
        return _S3ClientStub()
