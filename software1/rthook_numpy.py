"""PyInstaller 运行时钩：在任何其他模块导入之前初始化 numpy。

原因：
    numpy 2.x 的 C 扩展 _multiarray_umath 有"每进程仅加载一次"的保护。
    当 torch 的 C++ 运行时（torch_cpu.dll）通过 LoadLibrary 加载 numpy 的
    _multiarray_umath.dll 后，numpy 的 Python __init__.py 再尝试导入该模块时
    会触发 "cannot load module more than once per process" 错误。

    本钩子在主脚本执行前（但 bootloader 初始化后）导入 numpy，确保 numpy 的
    Python __init__.py 先于 torch 的 LoadLibrary 运行，从而正确初始化 C 扩展。
"""

import numpy  # noqa: F401
