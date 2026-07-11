# `_hxnative` — software1 / software2 共享 C++ 热点加速扩展

本扩展为 `software1` (PyQt6) 与 `software2` (PyQt5) 提供四个热点环节的 C++ 加速：
- **H1** `pixmap_bytes_to_qpixmap_buffer` — fitz pixmap → QImage 直通，跳过 PIL
- **H2** `optimize_char_boxes` — 整页字符边界框批量优化，替代 numpy 逐字符切片
- **H3** `batch_crop_qimage` — 批量字符裁切，替代 `PIL.Image.crop`
- **H4** 通过 H1 间接实现统一 `_pil_to_pixmap`

缺失 `.pyd` 时，Python 端 `native/__init__.py` 自动回落到现有实现，
应用功能与外观完全不变。

## 依赖

- Windows 10/11 x64（开发机）；Windows 7 SP1 x64（software2 部署目标，需启用兼容模式）
- CMake ≥ 3.18
- MSVC 2019/2022（推荐）
- Python 3.8+（与两个软件使用的解释器一致）
- pybind11 v2.13.6（由 CMake FetchContent 自动获取，无需预装）

## 构建（3 步）

在仓库根目录 `d:\hx` 下打开「x64 Native Tools Command Prompt for VS」：

```bat
cd e:\hx\software2\native
cmake -S . -B build -A x64
cmake --build build --config Release
```

构建成功后，`_hxnative.pyd` 会输出到 `native/` 目录，
Python 端 `from native import has_native` 即可使用。

## Windows 7 SP1 兼容模式（software2 部署用）

```bat
cmake -S . -B build -A x64 -DHXNATIVE_WIN7_COMPAT=ON
cmake --build build --config Release
```

启用后会定义 `_WIN32_WINNT=0x0601 WINVER=0x0601`，避免误用 Win8+ 专属 API。

## 验证

```python
from native import has_native, native_status
print(native_status())
assert has_native()
```

## 回退行为

任何原因导致 `_hxnative` 加载失败时，所有公共函数返回 `None`，
调用方（`pdf_loader.py`、`rapidocr_engine.py`、`parse_and_group`/`build_line_data`
以及各窗口的 `_pil_to_pixmap`）会透明回落到原 Python/numpy/PIL/reportlab 实现。
