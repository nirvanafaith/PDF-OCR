# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 横校工具2 (hengxiao_tool2).

打包命令（在 venv_py38 中执行）：
    cd d:\\hx\\software2
    d:\\hx\\software2\\native\\venv_py38\\Scripts\\pyinstaller.exe ^
        hengxiao_tool2.spec --noconfirm --distpath d:\\hx\\dist

产物：
    d:\\hx\\dist\\hengxiao_tool2\\hengxiao_tool2.exe   (GUI 入口)
    d:\\hx\\dist\\hengxiao_tool2\\_internal\\           (依赖与数据)
        ├─ native\\_hxnative.cp38-win_amd64.pyd  (C++ 加速)
        ├─ PyQt5\\Qt5\\plugins\\platforms\\qwindows.dll           (Qt 平台插件)
        ├─ fitz\\mupdfcpp64.dll                                   (PDF 渲染)
        └─ reportlab\\fonts\\                                     (PDF 输出字体)
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules

# ----------------------------------------------------------------------------
# 1. 收集第三方依赖（data + binaries + hiddenimports）
# ----------------------------------------------------------------------------
datas = []
binaries = []
hiddenimports = []

# PyQt5: Qt5 DLLs、plugins（platforms/qwindows.dll 必需）、translations
d, b, h = collect_all('PyQt5')
datas += d
binaries += b
hiddenimports += h

# PyMuPDF (fitz): mupdfcpp64.dll + Python 绑定
d, b, h = collect_all('fitz')
datas += d
binaries += b
hiddenimports += h

# reportlab: 字体数据 + 子模块
d, b, h = collect_all('reportlab')
datas += d
binaries += b
hiddenimports += h

# Pillow (PIL): 图像插件
d, b, h = collect_all('PIL')
datas += d
binaries += b
hiddenimports += h

# numpy: 核心数学库
d, b, h = collect_all('numpy')
datas += d
binaries += b
hiddenimports += h

# ----------------------------------------------------------------------------
# 2. 添加 _hxnative C++ 加速扩展（.pyd）
# ----------------------------------------------------------------------------
# Python 3.8 ABI 的 .pyd 必须放到 bundle 内的 native/ 下，
# 与 native/__init__.py 的 `importlib.import_module("._hxnative", __package__)` 路径一致。
_hxnative_pyd = 'd:/hx/software2/native/_hxnative.cp38-win_amd64.pyd'
binaries += [(_hxnative_pyd, 'native')]

# ----------------------------------------------------------------------------
# 3. 显式 hiddenimports（动态导入/延迟加载兜底）
# ----------------------------------------------------------------------------
hiddenimports += [
    'native',
    'native._hxnative',
    # PyQt5 常见动态加载模块
    'PyQt5.sip',
]

# 收集 native 所有子模块（确保 tests/ 之外的 .py 全部纳入）
hiddenimports += collect_submodules('native')

# ----------------------------------------------------------------------------
# 4. Analysis
# ----------------------------------------------------------------------------
a = Analysis(
    ['d:/hx/software2/main.py'],
    pathex=['d:/hx/software2'],  # 让 native 包可被发现
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=['d:/hx/software2/runtime_hook_stderr.py'],
    excludes=[
        # 排除测试/构建期依赖，减小体积
        'pytest',
        'cmake',
        'pybind11',
        'tkinter',
        'unittest',
        'pydoc',
    ],
    noarchive=False,
)

# ----------------------------------------------------------------------------
# 5. PYZ（Python 字节码压缩归档）
# ----------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ----------------------------------------------------------------------------
# 6. EXE（onedir 模式：exclude_binaries=True，binaries 由 COLLECT 收集）
# ----------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='hengxiao_tool2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX 压缩易被杀软误报，关闭
    console=False,              # GUI 应用，不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ----------------------------------------------------------------------------
# 7. COLLECT（onedir：所有文件收集到 hengxiao_tool2/ 文件夹）
# ----------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    [a.scripts[0]] if False else a.scripts,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='hengxiao_tool2',
)
