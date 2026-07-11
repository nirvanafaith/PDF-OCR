"""PyInstaller runtime hook: 捕获 native 加载状态到日志文件。

在 windowed 模式 (console=False) 下，sys.stderr 默认是黑洞流，应用诊断信息丢失。
本 hook 在 main.py 之前运行：
  1. 将 stderr 重定向到 %LOCALAPPDATA%\\hengxiao_tool2\\logs\\native_diag.log
  2. 直接导入 native 并写入 native_status() (避免 print 缓冲问题)
  3. flush 确保内容落盘

日志文件每次启动覆盖，避免无限增长。
"""

import os
import sys

try:
    # 日志目录：与 C++ 版 hengxiao_tool2 保持一致的日志路径约定
    log_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                           "hengxiao_tool2", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "native_diag.log")

    # 覆盖模式 + 行缓冲，确保内容及时落盘
    _stderr_file = open(log_path, "w", encoding="utf-8", buffering=1)
    sys.stderr = _stderr_file

    # 直接导入并写入 native_status (不依赖 main.py 的 print)
    # 此时 sys._MEIPASS 已由 bootloader 设置，native 在 PYZ 中可导入
    try:
        # 确保 _MEIPASS 在 sys.path 中
        _root = getattr(sys, "_MEIPASS", None)
        if _root and _root not in sys.path:
            sys.path.insert(0, _root)
        from native import native_status
        _stderr_file.write(native_status() + "\n")
    except Exception as _e:
        _stderr_file.write(f"native: runtime_hook import failed ({_e})\n")

    _stderr_file.flush()
except Exception:
    # 任何失败都不影响应用启动
    pass
