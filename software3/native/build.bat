@echo off
cd /d "%~dp0"

REM 创建 build 子目录
if not exist build mkdir build
cd build

REM 配置 CMake
cmake .. -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=Release

REM 编译
cmake --build . --config Release

REM 复制 .pyd 到 native/ 目录
copy Release\_native.* ..\

echo Build complete.
