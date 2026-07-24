"""集中式 CUDA DLL 路径管理模块。

将 nvidia pip 包扫描、torch/lib、CUDA_PATH/bin 三处 DLL 路径设置统一到此模块，
供 main.py、测试脚本和其他入口点共同使用，避免 DLL 路径管理分散导致的不一致问题。

用法:
    # 任何需要 CUDA DLL 的脚本在导入其他模块前调用：
    from cuda_dll_setup import setup_cuda_dll_paths
    setup_cuda_dll_paths()

    # 或者直接导入此模块（导入时自动执行一次）：
    import cuda_dll_setup  # noqa: F401
"""

import os
import site
import sys

_initialized = False


def setup_cuda_dll_paths():
    """设置 CUDA DLL 搜索路径。

    依次将以下目录添加到 os.add_dll_directory 和 PATH 环境变量：
    1. nvidia pip 包的 bin 目录（cublas、cudnn、cuda_runtime 等，分散在 nvidia/*/bin/）
    2. torch 捆绑的 CUDA DLL 路径（包含 nvrtc、cudnn、cublas 等，不在 nvidia pip 包中）
    3. CUDA_PATH/bin（通过 junction 指向 torch/lib，供 lmdeploy turbomind 使用）

    幂等设计：多次调用不会重复添加路径。
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    # 1. 扫描 nvidia CUDA pip 包的 bin 目录（可能在系统或用户 site-packages 中）
    _nvidia_search_dirs = [os.path.join(d, 'nvidia') for d in site.getsitepackages()]
    _nvidia_search_dirs.append(os.path.join(site.getusersitepackages(), 'nvidia'))
    for nvidia_base in _nvidia_search_dirs:
        if os.path.exists(nvidia_base):
            for pkg_name in os.listdir(nvidia_base):
                bin_dir = os.path.join(nvidia_base, pkg_name, 'bin')
                if os.path.isdir(bin_dir):
                    _add_dll_dir(bin_dir)

    # 2. 添加 torch 捆绑的 CUDA DLL 路径（包含 nvrtc、cudnn、cublas 等，不在 nvidia pip 包中）
    try:
        import torch as _torch
        _torch_lib = os.path.join(os.path.dirname(_torch.__file__), 'lib')
        if os.path.isdir(_torch_lib):
            _add_dll_dir(_torch_lib)
    except (ImportError, OSError):
        pass

    # 3. 添加 CUDA_PATH/bin（通过 junction 指向 torch/lib，供 lmdeploy turbomind 使用）
    _cuda_path = os.environ.get('CUDA_PATH', '')
    if _cuda_path:
        _cuda_bin = os.path.join(_cuda_path, 'bin')
        if os.path.isdir(_cuda_bin):
            _add_dll_dir(_cuda_bin)

    # 4. 添加 TensorRT lib 路径（pip 包 + 系统安装两处检测）
    #    pip tensorrt 包：DLL 可能在 site-packages/tensorrt/ 或同级 tensorrt_libs/
    #    系统安装：C:\Program Files\NVIDIA GPU Computing Toolkit\TensorRT\lib
    try:
        import tensorrt as _trt
        _trt_dir = os.path.dirname(_trt.__file__)
        if os.path.isdir(_trt_dir):
            _add_dll_dir(_trt_dir)
            # 较新版本 tensorrt 将 DLL 拆到独立的 tensorrt_libs 包中
            _trt_libs_dir = os.path.join(os.path.dirname(_trt_dir), 'tensorrt_libs')
            if os.path.isdir(_trt_libs_dir):
                _add_dll_dir(_trt_libs_dir)
    except (ImportError, OSError):
        pass
    # 系统级 TensorRT SDK 安装路径（独立于 pip 包，非必须存在）
    _trt_sys_dir = r'C:\Program Files\NVIDIA GPU Computing Toolkit\TensorRT\lib'
    if os.path.isdir(_trt_sys_dir):
        _add_dll_dir(_trt_sys_dir)


def _add_dll_dir(dir_path):
    """将目录添加到 DLL 搜索路径和 PATH 环境变量。

    同时使用 os.add_dll_directory（Win32 API AddDllDirectory）和修改 PATH 环境变量，
    因为不同的 DLL 加载方式（LoadLibrary vs AddDllDirectory）依赖不同的搜索机制。

    参数:
        dir_path: 要添加的目录绝对路径
    """
    try:
        os.add_dll_directory(dir_path)
    except OSError:
        pass
    os.environ['PATH'] = dir_path + os.pathsep + os.environ.get('PATH', '')


# 模块导入时自动执行一次，确保任何导入此模块的脚本都能获得正确的 DLL 路径
if sys.platform == 'win32':
    setup_cuda_dll_paths()
