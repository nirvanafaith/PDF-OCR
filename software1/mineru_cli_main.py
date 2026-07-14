"""MinerU CLI 入口脚本（供 PyInstaller 打包为独立 mineru_cli.exe）。

为什么需要这个文件：
    PyInstaller 打包后，sys.executable 指向 hengxiao_tool1.exe（GUI 入口），
    无法通过 `sys.executable -m mineru.cli` 方式启动 MinerU CLI
    （exe 不是 Python 解释器，-m 参数不会被解释）。
    因此需要独立的 mineru_cli.exe，由本脚本作为入口。

调用方式：
    mineru_cli.exe -p <pdf_path> -o <output_dir> -b hybrid-auto-engine --method ocr --lang ch

依赖:
    cuda_dll_setup: CUDA DLL 路径设置（必须在 mineru 导入前执行）
    mineru.cli.client.main: Click 命令对象，自动读取 sys.argv[1:]

调用关系:
    被 ui.draw_box_window.DrawBoxWindow._on_mineru_recognize 通过 subprocess 调用
"""

import sys

# 必须在 torch/onnxruntime 之前导入 numpy，否则 numpy 2.x 的 C 扩展
# _multiarray_umath 会被 torch 的 C++ 运行时通过 LoadLibrary 预加载，
# 导致 numpy 的 Python __init__.py 报 "cannot load module more than once per process"
import numpy  # noqa: F401

# 在 mineru 导入前设置 CUDA DLL 路径（torch/lib 中的 CUDA DLLs）
try:
    from cuda_dll_setup import setup_cuda_dll_paths
    setup_cuda_dll_paths()
except ImportError:
    pass

from mineru.cli.client import main

if __name__ == "__main__":
    # Click 的 main() 自动使用 sys.argv[1:] 作为参数
    # standalone_mode=True（默认）会在命令结束时调用 sys.exit()
    main()
