# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 横校工具1 (hengxiao_tool1) - 软件1 完整 OCR 管线。

打包命令（Python 3.12 环境中执行）：
    cd d:\\hx\\software1
    pyinstaller hengxiao_tool1.spec --noconfirm --distpath d:\\hx\\dist --workpath d:\\hx\\build_pyinstaller1

产物（onedir 模式，两个 exe 共享 _internal/）：
    d:\\hx\\dist\\hengxiao_tool1\\hengxiao_tool1.exe   (GUI 入口)
    d:\\hx\\dist\\hengxiao_tool1\\mineru_cli.exe       (MinerU CLI 入口)
    d:\\hx\\dist\\hengxiao_tool1\\_internal\\           (依赖与数据)
        ├─ native\\_hxnative.cp312-win_amd64.pyd  (C++ H1-H3 加速)
        ├─ rapidocr\\models\\                      (PP-OCRv6 模型)
        ├─ onnxruntime\\cudnn\\                    (CUDA provider)
        ├─ torch\\lib\\                            (CUDA DLLs)
        ├─ mineru\\                                (MinerU 包)
        ├─ models_cache\\hub\\models\\             (MinerU 模型缓存，打包后手动复制)
        ├─ PyQt6\\Qt6\\plugins\\platforms\\        (Qt 平台插件，由内置 hook 收集)
        ├─ fitz\\mupdfcpp64.dll                    (PDF 渲染)
        └─ PIL\\                                   (图像插件)

优化说明：
    - 不使用 collect_all('PyQt6')：该调用收集 3638 entries（Qt6/translations、Qt6/qml 等），
      改为依赖 PyInstaller 内置 hook（hook-PyQt6.QtCore/QtGui/QtWidgets.py）自动收集必需插件。
    - 不使用 collect_all('nvidia')：torch/lib 已包含 CUDA DLLs，nvidia pip 包冗余。
    - 模型缓存不通过 datas 打包（会导致 reclassification 过慢），改为打包后手动复制。
"""

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

# ----------------------------------------------------------------------------
# 1. 收集第三方依赖（data + binaries + hiddenimports）
# ----------------------------------------------------------------------------
datas = []
binaries = []
hiddenimports = []

# PyQt6: 依赖 PyInstaller 内置 hook 自动收集 Qt 插件和 DLLs
# 不使用 collect_all('PyQt6')（会收集 3638 个不必要 entries）
# 内置 hook hook-PyQt6.QtCore/QtGui/QtWidgets.py 会被 import 语句触发
hiddenimports += [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',           # QIcon 渲染 SVG 需要
]

# PyMuPDF (fitz): mupdfcpp64.dll + Python 绑定
d, b, h = collect_all('fitz')
datas += d
binaries += b
hiddenimports += h

# RapidOCR: OCR 引擎 + 内置 PP-OCRv6 模型文件
d, b, h = collect_all('rapidocr')
datas += d
binaries += b
hiddenimports += h

# ONNX Runtime GPU: CUDAExecutionProvider + cudnn DLLs
d, b, h = collect_all('onnxruntime')
datas += d
binaries += b
hiddenimports += h

# PyTorch: 仅收集 torch/lib 下的 CUDA DLLs 和 torch 共享库（.pyd/.dll）
# 不使用 collect_all('torch') 以避免收集数千个不必要的 Python 模块
# torch 的 Python 模块通过 collect_submodules('torch') 收集
import torch as _torch_mod
_torch_pkg_dir = os.path.dirname(_torch_mod.__file__)
# 1. torch/lib/*.dll（CUDA 运行时 DLLs：cublas、cudnn、cusparse 等）
_torch_lib = os.path.join(_torch_pkg_dir, 'lib')
if os.path.isdir(_torch_lib):
    for _f in os.listdir(_torch_lib):
        if _f.endswith('.dll'):
            binaries += [(os.path.join(_torch_lib, _f), os.path.join('torch', 'lib'))]
# 2. torch 根目录的 .pyd 和 .dll 文件
for _f in os.listdir(_torch_pkg_dir):
    _fp = os.path.join(_torch_pkg_dir, _f)
    if os.path.isfile(_fp) and (_f.endswith('.pyd') or _f.endswith('.dll')):
        binaries += [(_fp, 'torch')]
# 3. torch 的版本和元数据文件
for _f in ['_version.py', 'version.py', '__init__.py']:
    _fp = os.path.join(_torch_pkg_dir, _f)
    if os.path.isfile(_fp):
        datas += [(_fp, 'torch')]

# MinerU: PDF 解析工具包
d, b, h = collect_all('mineru')
datas += d
binaries += b
hiddenimports += h

# magika: MinerU 文件类型检测依赖，包含模型数据文件 standard_v3_3
# 注意：不使用 collect_data_files('magika')，因为 model.onnx (3MB) 会触发
# reclassification 卡死。改为打包后手动复制 magika/models 和 magika/config 到 dist
# 手动复制位置：d:\hx\dist\hengxiao_tool1\_internal\magika\
#
# === 打包后需手动复制的依赖 ===
# 以下依赖因 reclassification 卡死或 excludes 排除原因，需打包后手动复制到
# d:\hx\dist\hengxiao_tool1\_internal\ 目录下：
#
# 1. magika/models/standard_v3_3/ 和 magika/config/
#    来源：site-packages/magika/models/ 和 site-packages/magika/config/
#    原因：collect_data_files('magika') 的 model.onnx 触发 reclassification 卡死
#
# 2. boto3/ 和 botocore/（桩模块）
#    来源：d:/hx/software1/stubs/boto3/ 和 d:/hx/software1/stubs/botocore/
#    原因：完整 botocore 有数千个 AWS 服务定义 JSON，导致 reclassification 卡死
#    已通过 datas 添加，无需额外手动复制
#
# 3. reportlab/（部分模块）
#    来源：site-packages/reportlab/
#    原因：被 mineru.utils.draw_bbox 导入，但完整 reportlab 过大
#    仅复制必要的 lib/ 子模块
#
# 4. pandas/（部分模块）
#    来源：site-packages/pandas/
#    原因：被 mineru.backend.utils.office_chart 导入，在 excludes 中排除完整包
#    仅复制必要的 core/、io/、_libs/ 子模块
#
# 5. openpyxl/、et_xmlfile/
#    来源：site-packages/openpyxl/ 和 site-packages/et_xmlfile/
#    原因：pandas.io.excel 依赖，在 excludes 中排除
#
# 6. tqdm/、requests/、idna/、pydantic/、annotated_types/、packaging/
#    来源：各自 site-packages/ 目录
#    原因：MinerU 运行时依赖，未被 collect_all 自动收集
#
# 7. six.py、dateutil/、unittest/
#    来源：各自 site-packages/ 目录
#    原因：被 torch._dispatch.python 和 dateutil.tz.tz 导入
#
# 8. models_cache/（ModelScope hub，约2.2GB）
#    来源：~/.cache/modelscope/hub/
#    原因：MinerU 模型缓存，不通过 datas 打包（reclassification 过慢）
#    复制到：_internal/models_cache/hub/

# Pillow (PIL): 图像插件
d, b, h = collect_all('PIL')
datas += d
binaries += b
hiddenimports += h

# certifi: SSL 证书（MinerU 下载模型需要）
try:
    d, b, h = collect_all('certifi')
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass

# numpy: 使用 collect_submodules 收集所有 Python 子模块（包括 _exceptions 等）
# 不使用 collect_all（会触发 paddle DLL 依赖扫描瓶颈）
# mineru_cli_main.py 中 `import numpy` 在 cuda_dll_setup（torch）前执行，
# 解决 numpy 2.x "cannot load module more than once per process" 问题
hiddenimports += collect_submodules('numpy')

# ----------------------------------------------------------------------------
# 2. 添加 _hxnative C++ 加速扩展（.pyd）
# ----------------------------------------------------------------------------
_hxnative_pyd = 'd:/hx/software1/native/_hxnative.cp312-win_amd64.pyd'
binaries += [(_hxnative_pyd, 'native')]

# ----------------------------------------------------------------------------
# 3. MinerU 模型缓存（ModelScope hub，约2.2GB）
# ----------------------------------------------------------------------------
# 注意：模型缓存不通过 PyInstaller datas 打包（会导致 reclassification 步骤
# 耗时过长，因为需要逐个检查数千个模型文件）。
# 打包完成后，手动复制模型缓存到 dist/hengxiao_tool1/_internal/models_cache/
# 运行时通过 MODELSCOPE_CACHE 环境变量指向该目录。
_modelscope_cache = os.path.expanduser('~/.cache/modelscope/hub')
_modelscope_cache_source = os.path.dirname(_modelscope_cache) if os.path.isdir(_modelscope_cache) else None

# ----------------------------------------------------------------------------
# 4. 显式 hiddenimports（动态导入/延迟加载兜底）
# ----------------------------------------------------------------------------
hiddenimports += [
    'native',
    'native._hxnative',
    'cuda_dll_setup',
    # MinerU CLI 入口
    'mineru.cli',
    'mineru.cli.common',
    'mineru.cli.client',
    'mineru.cli.output_paths',
    # RapidOCR 模型加载
    'rapidocr.models',
    # ONNX Runtime CUDA provider
    'onnxruntime.capi._pybind_state',
]

# 收集 native 所有子模块
hiddenimports += collect_submodules('native')

# 收集 mineru 所有子模块（确保 CLI 完整）
hiddenimports += collect_submodules('mineru')

# 收集 torch 所有子模块（MinerU 子进程需要 torch 进行模型推理）
hiddenimports += collect_submodules('torch')

# boto3/botocore: 使用 stubs/ 桩模块替代完整包
# MinerU 的 mineru.data.io.s3 在模块级别 import boto3，需要满足导入
# 完整 botocore 包有数千个 AWS 服务定义 JSON，会导致 reclassification 卡死
# 桩模块作为 datas 添加到 _internal/boto3/ 和 _internal/botocore/
# 运行时 frozen importer 返回 None（在 excludes 中），标准导入从 _internal/ 查找
datas += [
    ('d:/hx/software1/stubs/boto3/__init__.py', 'boto3'),
    ('d:/hx/software1/stubs/botocore/__init__.py', 'botocore'),
    ('d:/hx/software1/stubs/botocore/config.py', 'botocore'),
]

# ----------------------------------------------------------------------------
# 5. Analysis
# ----------------------------------------------------------------------------
a = Analysis(
    ['d:/hx/software1/main.py'],
    pathex=['d:/hx/software1/stubs', 'd:/hx/software1'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 排除测试/构建期依赖
        'pytest',
        'cmake',
        'pybind11',
        'tkinter',
        'unittest',
        'pydoc',
        # 排除未使用的库
        'matplotlib',
        'pandas',
        'scipy',
        'tensorflow',
        # boto3/botocore/jmespath/s3transfer: 排除真实包（使用 stubs/ 桩模块替代）
        # 桩模块通过 datas 添加到 _internal/，不通过 PYZ 收集
        # 排除真实包可防止 hook-boto3.py 触发 botocore 数据文件扫描瓶颈
        'boto3',
        'botocore',
        'jmespath',
        's3transfer',
        'openpyxl',
        'pygments',
        'jinja2',
        'six',
        'win32com',
        'pythoncom',
        'pywintypes',
        'fsspec',
        'wcwidth',
        'shelve',
        'importlib_resources',
        'gi',
        'PyQt5',      # 软件1用 PyQt6，排除 PyQt5
        'reportlab',
        # 排除 torch 生态中不必要的大型包
        'tensorboard',
        'torchvision',
        'torchaudio',
        # 排除 nvidia pip 包（torch/lib 已包含 CUDA DLLs）
        'nvidia',
        # 排除不需要的 PyQt6 模块（减少内置 hook 触发）
        'PyQt6.QtBluetooth',
        'PyQt6.QtDBus',
        'PyQt6.QtDesigner',
        'PyQt6.QtHelp',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtNetwork',
        'PyQt6.QtNfc',
        'PyQt6.QtOpenGL',
        'PyQt6.QtOpenGLWidgets',
        'PyQt6.QtPdf',
        'PyQt6.QtPdfWidgets',
        'PyQt6.QtPositioning',
        'PyQt6.QtPrintSupport',
        'PyQt6.QtQml',
        'PyQt6.QtQuick',
        'PyQt6.QtQuick3D',
        'PyQt6.QtQuickWidgets',
        'PyQt6.QtRemoteObjects',
        'PyQt6.QtSensors',
        'PyQt6.QtSerialPort',
        'PyQt6.QtSpatialAudio',
        'PyQt6.QtSql',
        'PyQt6.QtSvgWidgets',
        'PyQt6.QtTest',
        'PyQt6.QtTextToSpeech',
        'PyQt6.QtWebChannel',
        'PyQt6.QtWebSockets',
        'PyQt6.QtXml',
        'PyQt6.QAxContainer',
        # 排除网络/服务器库
        'uvicorn',
        'websockets',
        'gevent',
        'zope',
        'IPython',
        'notebook',
        'jupyter',
        # 排除不必要的科学计算库
        'skimage',
        'sklearn',
        'sympy',
        # 排除其他不必要的依赖
        'pydoc_data',
        'ensurepip',
        'venv',
        'turtle',
        'turtledemo',
    ],
    noarchive=False,
)

# ----------------------------------------------------------------------------
# 6. PYZ
# ----------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ----------------------------------------------------------------------------
# 7. EXE 1: hengxiao_tool1（GUI 主程序）
# ----------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='hengxiao_tool1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # GUI 应用
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ----------------------------------------------------------------------------
# 8. EXE 2: mineru_cli（MinerU CLI 入口，共享同一 PYZ 和 _internal/）
# ----------------------------------------------------------------------------
# mineru_cli.exe 被 draw_box_window.py 的 _on_mineru_recognize 通过 subprocess 调用
# 入口脚本 mineru_cli_main.py 调用 mineru.cli.client.main（Click 命令）
# 两个 EXE 共享同一 PYZ（包含所有 Python 模块）和 _internal/（包含所有二进制依赖）
_mineru_script_path = os.path.normpath('d:/hx/software1/mineru_cli_main.py')
_mineru_scripts = [('mineru_cli_main.py', _mineru_script_path, 'PYSOURCE')]
exe_mineru = EXE(
    pyz,
    _mineru_scripts,
    [],
    exclude_binaries=True,
    name='mineru_cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,               # CLI 工具，需要控制台输出
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ----------------------------------------------------------------------------
# 9. COLLECT（onedir：两个 exe 共享 _internal/）
# ----------------------------------------------------------------------------
coll = COLLECT(
    exe,
    exe_mineru,
    a.binaries,
    a.zipfiles,
    a.datas,
    a.scripts,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='hengxiao_tool1',
)
