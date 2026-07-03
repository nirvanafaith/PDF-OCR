param(
    [Parameter(Mandatory=$true)]
    [string]$BackupDir,
    [Parameter(Mandatory=$true)]
    [string]$NewDir,
    [Parameter(Mandatory=$true)]
    [string]$ReportPath
)

function Get-Rel($file, $root) {
    return $file.FullName.Substring($root.Length).TrimStart('\')
}

$oldFiles = Get-ChildItem $BackupDir -Recurse -File | ForEach-Object {
    [PSCustomObject]@{
        Rel = Get-Rel $_ $BackupDir
        Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    }
}
$newFiles = Get-ChildItem $NewDir -Recurse -File | ForEach-Object {
    [PSCustomObject]@{
        Rel = Get-Rel $_ $NewDir
        Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    }
}

$oldDict = @{}
$oldFiles | ForEach-Object { $oldDict[$_.Rel] = $_.Hash }
$newDict = @{}
$newFiles | ForEach-Object { $newDict[$_.Rel] = $_.Hash }

$added = $newFiles | Where-Object { -not $oldDict.ContainsKey($_.Rel) }
$removed = $oldFiles | Where-Object { -not $newDict.ContainsKey($_.Rel) }
$modified = $newFiles | Where-Object {
    $oldDict.ContainsKey($_.Rel) -and $oldDict[$_.Rel] -ne $_.Hash
}

$addedList = ($added | ForEach-Object { "- $($_.Rel)" }) -join "`n"
$removedList = ($removed | ForEach-Object { "- $($_.Rel)" }) -join "`n"
$modifiedList = ($modified | ForEach-Object { "- $($_.Rel)" }) -join "`n"

$lines = @(
    "# 2_cpp 下载技术报告",
    "",
    "生成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "",
    "## 统计",
    "",
    "- 备份目录：``$BackupDir``",
    "- 新版本目录：``$NewDir``",
    "- 旧版文件数：$($oldFiles.Count)",
    "- 新版文件数：$($newFiles.Count)",
    "- 新增文件：$($added.Count)",
    "- 删除文件：$($removed.Count)",
    "- 内容变更文件：$($modified.Count)",
    "",
    "## 新增文件",
    "",
    $addedList,
    "",
    "## 删除文件",
    "",
    $removedList,
    "",
    "## 内容变更文件",
    "",
    $modifiedList,
    "",
    "## 重点关注",
    "",
    "1. ``CMakeLists.txt`` 是否已改为 ``hengxiao_tool2`` 项目、输出 ``hengxiao_tool2.exe``、并链接 ``Qt5::Concurrent``。",
    "2. ``src/windows/horizontalcheckwindow.h`` 与 ``src/windows/horizontalcheckwindow.cpp`` 是否已存在。",
    "3. 本地原有的 ``verticalcheckwindow`` 相关修改是否被远程版本覆盖（如有自定义改动请在备份中手动合并）。",
    "4. 远程版本使用 Qt5 + ``_WIN32_WINNT=0x0601``，符合 Windows 7 SP1 兼容性要求。",
    "",
    "## 回滚方式",
    "",
    "若需要恢复旧版本，将备份目录重命名为 ``软件2_cpp`` 即可：",
    "",
    '```powershell',
    'Remove-Item -Path ''$NewDir'' -Recurse -Force',
    'Rename-Item -Path ''$BackupDir'' -NewName ''软件2_cpp''',
    '```'
)

$report = $lines -join "`n"
$report | Out-File -FilePath $ReportPath -Encoding utf8
Write-Host "Report saved to: $ReportPath"
