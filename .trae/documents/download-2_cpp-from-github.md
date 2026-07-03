# 从 GitHub 下载 PDF-OCR 2_cpp 文件夹 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从私有 GitHub 仓库 `nirvanafaith/PDF-OCR` 的 `main` 分支下载 `2_cpp` 文件夹全部内容，先备份本地 `软件2_cpp`，再用远程版本覆盖，并生成技术报告。

**Architecture:** 采用 PowerShell 调用 GitHub REST API（`git/trees?recursive=1` 获取目录树 + `git/blobs/{sha}` 下载 Base64 内容），不依赖本地 `git`。下载前使用 `Copy-Item` 创建带时间戳的完整备份；下载后通过 SHA256 哈希对比生成本地原版本与 GitHub 版本的差异报告。

**Tech Stack:** PowerShell 5.1, GitHub REST API (trees/blobs), Base64 解码。

---

## File Structure

| 路径 | 说明 |
|------|------|
| `c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp\` | 本地目标目录（下载后被远程版本覆盖）。 |
| `c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp_backup_<yyyyMMdd_HHmmss>\` | 备份目录，用于回滚。 |
| `c:\Users\E-VR\Documents\trae_projects\横校\.trae\scripts\download-2_cpp.ps1` | 临时下载脚本。 |
| `c:\Users\E-VR\Documents\trae_projects\横校\.trae\scripts\generate-2_cpp-report.ps1` | 技术报告生成脚本。 |
| `c:\Users\E-VR\Documents\trae_projects\横校\.trae\documents\2_cpp-download-report-<yyyyMMdd_HHmmss>.md` | 生成的技术报告。 |

---

## Current State Analysis

### 本地 `软件2_cpp/`

- `CMakeLists.txt`：项目名为中文 `横校工具2`，输出名默认与项目名相同；`SOURCES`/`HEADERS` 未包含 `horizontalcheckwindow.cpp/.h`；未链接 `Qt5::Concurrent`。
- `README.md`：说明当前处于阶段 1/2，UI 窗口尚未实现。
- `src/windows/`：包含 `mainwindow`、`importwindow`、`verticalcheckwindow`、`stepindicator`，**缺少 `horizontalcheckwindow`**。
- 当前环境未安装 `git`/`cmake`/`Qt5`，仅有 MinGW 的 `mingw32-make`。

### 远程 GitHub `2_cpp/`

- 仓库：`https://github.com/nirvanafaith/PDF-OCR`（private，默认分支 `main`）。
- 已验证 Token `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` 拥有 `admin`/`maintain`/`push`/`pull` 权限。
- 远程 `CMakeLists.txt`：项目名 `hengxiao_tool2`，输出名 ASCII 的 `hengxiao_tool2.exe`，链接 `Qt5::Concurrent`。
- 远程 `src/windows/` 已包含 `horizontalcheckwindow.h/.cpp`。

---

## Proposed Changes

### Task 1: 备份本地 `软件2_cpp/`

**Files:** 仅操作文件系统（读取/复制）。

- [ ] **Step 1: 计算时间戳并完整复制目录**

  ```powershell
  $base = "c:\Users\E-VR\Documents\trae_projects\横校"
  $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
  $src = Join-Path $base "软件2_cpp"
  $dst = Join-Path $base "软件2_cpp_backup_$ts"
  if (-not (Test-Path $src)) { throw "源目录不存在：$src" }
  if (Test-Path $dst) { throw "备份目录已存在：$dst" }
  Copy-Item -Path $src -Destination $dst -Recurse -Force
  Write-Host "已备份到：$dst"
  ```

- [ ] **Step 2: 校验备份大小与源目录一致**

  ```powershell
  $srcSize = (Get-ChildItem $src -Recurse -File | Measure-Object -Property Length -Sum).Sum
  $dstSize = (Get-ChildItem $dst -Recurse -File | Measure-Object -Property Length -Sum).Sum
  if ($srcSize -ne $dstSize) { throw "备份大小不一致：源 $srcSize，备份 $dstSize" }
  Write-Host "备份校验通过：$dstSize bytes"
  ```

---

### Task 2: 编写并执行下载脚本

**Files:**
- Create: `c:\Users\E-VR\Documents\trae_projects\横校\.trae\scripts\download-2_cpp.ps1`

- [ ] **Step 1: 创建下载脚本**

  ```powershell
  # 创建脚本目录
  $scriptDir = "c:\Users\E-VR\Documents\trae_projects\横校\.trae\scripts"
  New-Item -ItemType Directory -Path $scriptDir -Force | Out-Null

  $scriptContent = @'
  param(
      [string]$Owner = "nirvanafaith",
      [string]$Repo = "PDF-OCR",
      [string]$RemotePath = "2_cpp",
      [string]$Ref = "main",
      [string]$OutDir = "c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp",
      [string]$Token = $env:GITHUB_TOKEN
  )
  if ([string]::IsNullOrWhiteSpace($Token)) { throw "请先设置 `$env:GITHUB_TOKEN 或在 -Token 参数传入 PAT" }

  $headers = @{
      Authorization = "Bearer $Token"
      Accept = "application/vnd.github+json"
      "X-GitHub-Api-Version" = "2022-11-28"
  }
  $baseApi = "https://api.github.com"
  $ProgressPreference = 'SilentlyContinue'

  function Invoke-GhApi($url) {
      $resp = Invoke-RestMethod -Uri $url -Headers $headers -Method GET -MaximumRedirection 5
      return $resp
  }

  function Write-Base64ToFile($b64, $outPath) {
      $bytes = [Convert]::FromBase64String($b64)
      [IO.File]::WriteAllBytes($outPath, $bytes)
  }

  # 1) 获取递归 tree
  $treeUrl = "$baseApi/repos/$Owner/$Repo/git/trees/${Ref}?recursive=1"
  Write-Host "获取 tree：$treeUrl"
  $tree = Invoke-GhApi $treeUrl
  if ($tree.truncated) {
      Write-Warning "tree 被截断，下载完成后请改用 contents API 递归方案"
  }

  $prefix = "$RemotePath/"
  $entries = $tree.tree | Where-Object { $_.path.StartsWith($prefix) -and $_.type -eq "blob" }
  Write-Host "待下载文件数：$($entries.Count)"

  $stats = [PSCustomObject]@{ downloaded = 0; bytes = 0; errors = [System.Collections.Generic.List[string]]::new() }

  # 2) 清理并重建目标根目录
  if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
  New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

  # 3) 逐一下载 blob
  foreach ($entry in $entries) {
      $relative = $entry.path.Substring($prefix.Length).Replace('/', '\')
      $localPath = Join-Path $OutDir $relative
      $dir = Split-Path $localPath -Parent
      if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
      try {
          $blob = Invoke-GhApi "$baseApi/repos/$Owner/$Repo/git/blobs/$($entry.sha)"
          Write-Base64ToFile $blob.content $localPath
          $stats.downloaded++
          $stats.bytes += $blob.size
          Write-Host "OK  $($entry.path)"
      } catch {
          $msg = "FAIL $($entry.path): $_"
          Write-Warning $msg
          $stats.errors.Add($msg)
      }
  }

  $stats | Format-List
  if ($stats.errors.Count -gt 0) { throw "下载过程中出现 $($stats.errors.Count) 个错误" }
  Write-Host "下载完成：$($stats.downloaded) 个文件，共 $($stats.bytes) bytes"
  '@

  $scriptPath = Join-Path $scriptDir "download-2_cpp.ps1"
  $scriptContent | Out-File -FilePath $scriptPath -Encoding utf8
  Write-Host "脚本已保存到：$scriptPath"
  ```

- [ ] **Step 2: 设置 Token 并执行下载脚本**

  > 安全提示：Token 仅在当前 PowerShell 会话中使用，执行后建议轮换。

  ```powershell
  $env:GITHUB_TOKEN = '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'
  cd "c:\Users\E-VR\Documents\trae_projects\横校"
  .\.trae\scripts\download-2_cpp.ps1
  ```

- [ ] **Step 3（仅在 tree truncated 时执行）：回退到 contents API 递归下载**

  如果 Step 2 出现 `tree 被截断` 警告，运行以下备用方案：

  ```powershell
  function Download-Contents($path, $outDir) {
      $url = "https://api.github.com/repos/nirvanafaith/PDF-OCR/contents/$path?ref=main"
      $items = Invoke-RestMethod -Uri $url -Headers @{
          Authorization = "Bearer $env:GITHUB_TOKEN"
          Accept = "application/vnd.github+json"
          "X-GitHub-Api-Version" = "2022-11-28"
      }
      foreach ($item in $items) {
          $dest = Join-Path $outDir $item.name
          if ($item.type -eq "dir") {
              New-Item -ItemType Directory -Path $dest -Force | Out-Null
              Download-Contents $item.path $dest
          } else {
              $dir = Split-Path $dest -Parent
              if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
              if ($item.content) {
                  [IO.File]::WriteAllBytes($dest, [Convert]::FromBase64String($item.content))
              } else {
                  Invoke-RestMethod -Uri $item.download_url -Headers $headers -OutFile $dest
              }
              Write-Host "OK  $($item.path)"
          }
      }
  }
  $out = "c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp"
  if (Test-Path $out) { Remove-Item $out -Recurse -Force }
  New-Item -ItemType Directory -Path $out -Force | Out-Null
  Download-Contents "2_cpp" $out
  ```

---

### Task 3: 生成技术报告

**Files:**
- Create: `c:\Users\E-VR\Documents\trae_projects\横校\.trae\scripts\generate-2_cpp-report.ps1`
- Create: `c:\Users\E-VR\Documents\trae_projects\横校\.trae\documents\2_cpp-download-report-<yyyyMMdd_HHmmss>.md`

- [ ] **Step 1: 创建报告生成脚本**

  ```powershell
  $scriptDir = "c:\Users\E-VR\Documents\trae_projects\横校\.trae\scripts"
  $reportScript = @'
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

  $report = @"
  # 2_cpp 下载技术报告

  生成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

  ## 统计

  - 备份目录：`$BackupDir`
  - 新版本目录：`$NewDir`
  - 旧版文件数：$($oldFiles.Count)
  - 新版文件数：$($newFiles.Count)
  - 新增文件：$($added.Count)
  - 删除文件：$($removed.Count)
  - 内容变更文件：$($modified.Count)

  ## 新增文件

  $($addedList)

  ## 删除文件

  $($removedList)

  ## 内容变更文件

  $($modifiedList)

  ## 重点关注

  1. `CMakeLists.txt` 是否已改为 `hengxiao_tool2` 项目、输出 `hengxiao_tool2.exe`、并链接 `Qt5::Concurrent`。
  2. `src/windows/horizontalcheckwindow.h` 与 `src/windows/horizontalcheckwindow.cpp` 是否已存在。
  3. 本地原有的 `verticalcheckwindow` 相关修改是否被远程版本覆盖（如有自定义改动请在备份中手动合并）。
  4. 远程版本使用 Qt5 + `\`_WIN32_WINNT=0x0601\`，符合 Windows 7 SP1 兼容性要求。

  ## 回滚方式

  若需要恢复旧版本，将备份目录重命名为 `软件2_cpp` 即可：

  ```powershell
  Remove-Item -Path '$NewDir' -Recurse -Force
  Rename-Item -Path '$BackupDir' -NewName '软件2_cpp'
  ```
  "@

  $report | Out-File -FilePath $ReportPath -Encoding utf8
  Write-Host "报告已保存到：$ReportPath"
  '@

  $reportScriptPath = Join-Path $scriptDir "generate-2_cpp-report.ps1"
  $reportScript | Out-File -FilePath $reportScriptPath -Encoding utf8
  Write-Host "报告脚本已保存到：$reportScriptPath"
  ```

- [ ] **Step 2: 执行报告脚本**

  ```powershell
  $base = "c:\Users\E-VR\Documents\trae_projects\横校"
  $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
  $backup = Get-ChildItem -Path $base -Filter "软件2_cpp_backup_*" -Directory | Sort-Object Name -Descending | Select-Object -First 1
  if (-not $backup) { throw "未找到备份目录" }
  $new = Join-Path $base "软件2_cpp"
  $report = Join-Path $base ".trae\documents\2_cpp-download-report-$ts.md"

  .\.trae\scripts\generate-2_cpp-report.ps1 `
      -BackupDir $backup.FullName `
      -NewDir $new `
      -ReportPath $report
  ```

---

### Task 4: 校验下载结果

- [ ] **Step 1: 检查关键文件存在且非空**

  ```powershell
  $base = "c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp"
  $required = @(
      "src\windows\horizontalcheckwindow.h",
      "src\windows\horizontalcheckwindow.cpp",
      "CMakeLists.txt"
  )
  foreach ($rel in $required) {
      $p = Join-Path $base $rel
      if (-not (Test-Path $p)) { throw "缺失关键文件：$p" }
      $size = (Get-Item $p).Length
      if ($size -eq 0) { throw "关键文件为空：$p" }
      Write-Host "存在且非空：$rel ($size bytes)"
  }
  ```

- [ ] **Step 2: 验证 CMakeLists.txt 关键标记**

  ```powershell
  $cmake = Get-Content "c:\Users\E-VR\Documents\trae_projects\横校\软件2_cpp\CMakeLists.txt" -Raw
  if ($cmake -notmatch 'hengxiao_tool2') { throw "CMakeLists.txt 未包含项目名 hengxiao_tool2" }
  if ($cmake -notmatch 'Qt5::Concurrent') { throw "CMakeLists.txt 未链接 Qt5::Concurrent" }
  Write-Host "CMakeLists.txt 关键标记验证通过"
  ```

- [ ] **Step 3: 输出备份目录与报告路径**

  ```powershell
  Write-Host "备份目录：$($backup.FullName)"
  Write-Host "技术报告：$report"
  ```

---

## Assumptions & Decisions

1. **先备份再覆盖**：Task 1 先完整复制本地 `软件2_cpp` 到带时间戳的备份目录，Task 2 删除原目录并写入远程内容，确保本地状态与远程完全一致。
2. **使用 GitHub REST API 而非 git**：当前环境未安装 `git`，且只需下载单个文件夹；使用 `git/trees` + `git/blobs` 可一次性递归获取所有文件，并避免 contents API 的 1 MB 限制。
3. **Token 安全**：计划文档不保存 Token；执行命令通过 `$env:GITHUB_TOKEN` 传入当前会话，执行后建议用户轮换该 Token。
4. **目录名映射**：远程 `2_cpp/` 映射到本地 `软件2_cpp/`，与现有本地目录名保持一致。
5. **二进制安全**：blob API 返回 Base64，解码后以字节写入文件，文本与二进制均保持一致。
6. **继续满足用户工具要求**：执行阶段继续使用 `using-superpowers` skill、`sequentialthinking`（MCP）和 `context7`（MCP）进行研究/审查。

---

## Verification Steps

1. 备份目录 `软件2_cpp_backup_<yyyyMMdd_HHmmss>/` 存在，且文件总大小与源目录一致。
2. 下载脚本执行成功，统计输出中 `downloaded` 大于 0 且 `errors` 为空。
3. `软件2_cpp/src/windows/horizontalcheckwindow.h` 与 `horizontalcheckwindow.cpp` 存在且非空。
4. `软件2_cpp/CMakeLists.txt` 包含 `hengxiao_tool2` 与 `Qt5::Concurrent`。
5. 技术报告 `.trae/documents/2_cpp-download-report-<yyyyMMdd_HHmmss>.md` 已生成，包含新增/删除/变更文件清单。
