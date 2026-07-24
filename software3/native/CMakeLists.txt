cmake_minimum_required(VERSION 3.18...4.0)
project(native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# 用户可配置：通过 FetchContent 拉取 pybind11（与 software2/native 保持一致）
option(NATIVE_PYBIND11_FETCH "Fetch pybind11 via FetchContent" ON)

if(NATIVE_PYBIND11_FETCH)
    include(FetchContent)
    set(PYBIND11_FINDPYTHON ON CACHE BOOL "" FORCE)
    FetchContent_Declare(
        pybind11_src
        GIT_REPOSITORY https://github.com/pybind/pybind11.git
        GIT_TAG        v2.13.6
    )
    FetchContent_MakeAvailable(pybind11_src)
else()
    find_package(pybind11 CONFIG REQUIRED)
endif()

# pybind11 已经处理 Python 解释器/Extension 开发组件检索
# (PYBIND11_FINDPYTHON=ON 时使用 CMake 现代 FindPython)

pybind11_add_module(_native
    src/native.cpp
)

target_include_directories(_native PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_compile_definitions(_native PRIVATE
    NOMINMAX
    WIN32_LEAN_AND_MEAN
    UNICODE
    _UNICODE
)

# software3 不需要兼容 Win7，可启用 AVX2（MSVC: /arch:AVX2, GCC/Clang: -mavx2）
# 当前实现为标量版本（足够快），如需启用 AVX2 取消下行注释：
# if(MSVC)
#     target_compile_options(_native PRIVATE /arch:AVX2)
# elseif(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
#     target_compile_options(_native PRIVATE -mavx2)
# endif()

# 将 .pyd 直接输出到当前目录 (native/)，
# 使 Python 端可以 `from native._native import ...`。
set_target_properties(_native PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY         ${CMAKE_CURRENT_SOURCE_DIR}
    RUNTIME_OUTPUT_DIRECTORY         ${CMAKE_CURRENT_SOURCE_DIR}
    LIBRARY_OUTPUT_DIRECTORY_DEBUG   ${CMAKE_CURRENT_SOURCE_DIR}
    LIBRARY_OUTPUT_DIRECTORY_RELEASE ${CMAKE_CURRENT_SOURCE_DIR}
)

if(MSVC)
    target_compile_options(_native PRIVATE /W3 /utf-8)
endif()

# MinGW-w64: 静态链接运行时库 (libgcc/libstdc++/libwinpthread)，
# 避免分发时 .pyd 找不到 MinGW DLL
if(MINGW OR CMAKE_CXX_COMPILER_ID MATCHES "GNU")
    target_link_options(_native PRIVATE -static-libgcc -static-libstdc++ -static)
    target_compile_options(_native PRIVATE -static-libgcc -static-libstdc++)
endif()
