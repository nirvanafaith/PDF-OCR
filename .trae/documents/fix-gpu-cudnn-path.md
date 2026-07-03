# 修复 RapidOCR GPU 加速：cuDNN DLL 路径未注册

## 问题诊断

### 诊断结果

通过实际运行诊断脚本，发现以下关键事实：

1. **onnxruntime-gpu 已安装**：`onnxruntime-gpu 1.26.0`，`CUDAExecutionProvider` 在可用列表中
2. **CUDA 13.2 已安装**：nvidia-smi 显示 CUDA 13.2，驱动 595.79
3. **cuDNN 9.9.0.52 已通过 pip 安装**：`nvidia-cudnn-cu12` 包已安装
4. **❌ 但 cuDNN DLL 不在系统 PATH 中**：`cudnn64_9.dll` 存在于 `site-packages\nvidia\cudnn\bin\` 目录，但该目录不在 PATH 环境变量中

### 错误信息

```
Failed to create CUDAExecutionProvider. Require cuDNN 9.* and CUDA 12.*
Error loading "onnxruntime_providers_cuda.dll" which depends on "cudnn64_9.dll" which is missing. (Error 126)
```

### 根本原因

onnxruntime-gpu 的 `onnxruntime_providers_cuda.dll` 依赖 `cudnn64_9.dll`，但 pip 安装的 `nvidia-cudnn-cu12` 包将 DLL 放在 Python site-packages 目录下（`C:\Users\E-VR\AppData\Local\Programs\Python\Python312\Lib\site-packages\nvidia\cudnn\bin\`），而不是系统 PATH 中。因此 onnxruntime 在运行时找不到 cuDNN DLL，导致 CUDA Provider 初始化失败，静默回退到 CPU。

### 验证证据

- RapidOCR 的 Det/Cls/Rec 三个 session 实际 providers 均为 `['CPUExecutionProvider']`
- 直接创建 CUDA session 也失败，回退到 CPU
- cuDNN DLL 文件存在于 pip 包目录但不在 PATH 中

## 修复方案

### 方案：在应用启动时动态添加 cuDNN 路径到 PATH

在 `main.py` 的最开头（所有 import 之前），添加以下代码，将 pip 安装的 nvidia 库的 bin 目录添加到系统 PATH：

```python
import os
import site

site_dir = site.getsitepackages()[1]  # Lib\site-packages
nvidia_bin_dirs = [
    os.path.join(site_dir, 'nvidia', 'cudnn', 'bin'),
    os.path.join(site_dir, 'nvidia', 'cuda_runtime', 'bin'),
    os.path.join(site_dir, 'nvidia', 'cufft', 'bin'),
    os.path.join(site_dir, 'nvidia', 'curand', 'bin'),
    os.path.join(site_dir, 'nvidia', 'nvrtc', 'bin'),
]
for d in nvidia_bin_dirs:
    if os.path.exists(d):
        os.add_dll_directory(d)
        os.environ['PATH'] = d + os.pathsep + os.environ['PATH']
```

关键点：
1. **必须在所有 import 之前执行**：因为 onnxruntime 的 CUDA provider 在 import 时就会尝试加载 DLL
2. **使用 `os.add_dll_directory`**：Windows 下 DLL 搜索路径需要通过此 API 注册
3. **同时更新 PATH 环境变量**：确保子进程也能找到 DLL

### 修改文件

- `main.py`：在文件最开头添加 cuDNN 路径注册代码

### 验证计划

1. 启动应用，检查 RapidOCR session 的 providers 是否包含 `CUDAExecutionProvider`
2. 执行 OCR 识别，观察 GPU 利用率是否提升
3. 观察 CPU 占用率是否下降
