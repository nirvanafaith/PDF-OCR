# 2_cpp 下载技术报告

生成时间：2026-06-22 08:43:24

## 统计

- 备份目录：`c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp_backup_20260622_083249`
- 新版本目录：`c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp`
- 旧版文件数：27
- 新版文件数：32
- 新增文件：5
- 删除文件：0
- 内容变更文件：13

## 新增文件

- build.bat
- deploy.bat
- start.bat
- src\windows\horizontalcheckwindow.cpp
- src\windows\horizontalcheckwindow.h

## 删除文件



## 内容变更文件

- CMakeLists.txt
- resources\styles.qss
- src\main.cpp
- src\models\datamodels.h
- src\processors\lazy_page_loader.cpp
- src\processors\pdf_output_generator.cpp
- src\processors\pdf_processor.cpp
- src\windows\importwindow.cpp
- src\windows\mainwindow.cpp
- src\windows\mainwindow.h
- src\windows\stepindicator.cpp
- src\windows\verticalcheckwindow.cpp
- src\windows\verticalcheckwindow.h

## 重点关注

1. `CMakeLists.txt` 是否已改为 `hengxiao_tool2` 项目、输出 `hengxiao_tool2.exe`、并链接 `Qt5::Concurrent`。
2. `src/windows/horizontalcheckwindow.h` 与 `src/windows/horizontalcheckwindow.cpp` 是否已存在。
3. 本地原有的 `verticalcheckwindow` 相关修改是否被远程版本覆盖（如有自定义改动请在备份中手动合并）。
4. 远程版本使用 Qt5 + `_WIN32_WINNT=0x0601`，符合 Windows 7 SP1 兼容性要求。

## 回滚方式

若需要恢复旧版本，将备份目录重命名为 `软件2_cpp` 即可：

```powershell
Remove-Item -Path '$NewDir' -Recurse -Force
Rename-Item -Path '$BackupDir' -NewName '软件2_cpp'
```
