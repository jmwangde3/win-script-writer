---
name: win-script-writer
description: 在中文 Windows（zh-CN / 代码页 936 / GBK）上写或改脚本、或遇到 PowerShell 中文乱码时使用；也用于排查 encoding、BOM、Out-File、chcp 936、中文路径、引号被拆散等问题。覆盖 Windows PowerShell 5.1 与 PowerShell 7 双版本，提供编码检测、按编码落盘、编码无关执行与环境自检四个工具。触发词：写脚本、生成脚本、ps1、PowerShell 脚本、bat、cmd 批处理、脚本编码、中文乱码、UTF-8 BOM、run_ps.py。
---

# 中文 Windows 写脚本规范

适用环境：Windows 10/11 简体中文（ANSI 代码页 936）、Windows PowerShell 5.1、
PowerShell 7.4+、未开启系统级 UTF-8；Git Bash / MSYS2 侧为 UTF-8。

## 0. 三步走通

1. **看清这台机器**：`scripts/Get-WinScriptEnvironment.ps1`。一次报出 ACP、
   OEMCP、控制台代码页、`$OutputEncoding`、`[Encoding]::Default`、CP936 是否
   可用、当前是 5.1 还是 7。这些是**四个不同的设置**，混为一谈必然误判。
2. **读一份参考**：按下表只读与当前任务相关的那一份，不要全量加载。
3. **交付前自检**：`scripts/Test-ScriptEncoding.ps1 -Path <文件>` 必须
   `VERDICT=OK`、退出码 0。它是字节级判定，不是风格检查。

## 1. 路由表

| 你要做的事 | 读这一份 |
| --- | --- |
| 查「哪种文件该存哪种编码」的总表 | `references/encoding-matrix.md` |
| 写或调 Windows PowerShell 5.1 脚本 | `references/powershell-51.md` |
| 写或调 PowerShell 7 脚本 | `references/powershell-7.md` |
| 一个脚本要同时跑在 5.1 和 7 | `references/dual-version-compatibility.md` |
| 写 `.bat` / `.cmd`，或改已有批处理 | `references/cmd-bat.md` |
| 写 Python，或在 Python 里调外部程序 | `references/python.md` |
| 用 Git Bash / MSYS2 做事 | `references/git-bash.md` |
| 决定怎么把脚本跑起来（含中文参数） | `references/execution.md` |
| 关心默认开关、提权、脱敏、沙箱边界 | `references/security.md` |
| 已经乱了，要一条命令修好 | `references/troubleshooting.md` |

## 2. 四条硬规则

违反任一条都要返工，细节见对应参考页。

1. **`.ps1` 出现非 ASCII → 存 UTF-8 with BOM。** 5.1 对无 BOM 文件按 ANSI
   代码页（936）解析，UTF-8 中文变乱码；7 按 UTF-8 解析。带 BOM 两边都对、别的
   工具也读得懂（UTF-16 带 BOM 也能跑，但只它一家认）。纯 ASCII 存无 BOM 即可。
2. **不要用 `>`、`>>`、`Out-File`、`Set-Content` 写文件。** 5.1 下它们产出
   UTF-16LE + BOM 或 ANSI，Python、Node、git 读进来就是乱码。改
   `[System.IO.File]::WriteAllText($p, $s, $utf8NoBom)`，写前读回校验。
3. **中文与嵌套引号不要手拼命令行。** argv 列表调用时命令行本身是 Unicode，
   不丢字；丢字发生在字节层：GBK 的 `.bat` 里写的命令、Shell 重新拼参数字符串、
   把 stdout 按错的代码页解码。要稳就走文件：`-File` 或 `scripts/run_ps.py`；
   需要 `$PSScriptRoot` 语义用它的 `--invoke-file`。
4. **不要假设 profile 生效。** agent 宿主普遍以
   `-NoProfile -NonInteractive` 启动，`$PROFILE` 不会被加载。需要编码
   兜底就在脚本开头显式写，不要依赖用户配置。

## 3. 工具

四个工具只依赖 5.1 自带的 .NET 与 Python 标准库，不装模块、不要管理员。

- `scripts/Get-WinScriptEnvironment.ps1` —— 只读自检。`-Output Json` 出机器
  可读报告，`WARNING=` 行只在条件真的成立时出现。
- `scripts/Test-ScriptEncoding.ps1` —— 字节级检测。报告 BOM、非 ASCII
  字节数、严格 UTF-8 是否成立、CP936 往返是否无损，再按目标消费方
  （ps51 / ps7 / cmd / python / bash / data）给 OK/WARN/FAIL。只认证据：
  解不成 UTF-8 不等于就是 GBK，只有往返完全一致才标 gbk。`WARN` 不等于
  能跑：`cp1252` / `shift_jis` 这类名字本工具没有字节表，只输出
  `SOURCE_CODING_PAYLOAD=unverified`；`base64` / `rot13` 这类转换器直接
  `FAIL`（`UNUSABLE`）。
- `scripts/New-EncodedScript.ps1` —— 按指定编码落盘。中文内容走文件而不走
  命令行；先写临时文件、读回复验、再原子替换；默认拒绝覆盖，要覆盖用 `-Force`。
- `scripts/run_ps.py` —— 编码无关地执行脚本。`--command` / `--file` /
  `--stdin` 把正文走 `-EncodedCommand`，没有文件上下文；`--invoke-file`
  用原生 `-File`，保留 `$PSScriptRoot` 与 `$PSCommandPath`。默认不改执行
  策略、不改控制台编码；不是沙箱。退出码：子进程透传，3 本地错误，124 超时，
  127 找不到 shell。

## 4. 边界

这些工具只解决**编码与传输层**问题，不管权限、沙箱或安全审计。默认一律
「不改系统状态」：不注入 `-ExecutionPolicy Bypass`、不自动提权、不改 `ACP`；
要改必须显式传参。

## 5. 已知限制

- 5.1 是系统组件，不能卸载，也没有就地升级到 7 的路径；装了 7 也不影响工具
  继续以绝对路径调用 5.1。
- 系统级 UTF-8（Beta）需重启，且会让旧 GBK 软件乱码；它**不修** `Out-File`
  的 UTF-16LE，也不修 `$OutputEncoding` 的 us-ascii。
- 本规范以简体中文 Windows 为前提；其他语言/代码页判据相同，数值按
  `Get-WinScriptEnvironment.ps1` 输出调整。
