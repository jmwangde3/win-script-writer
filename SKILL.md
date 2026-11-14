---
name: win-script-writer
description: 在中文 Windows（zh-CN / 代码页 936 / GBK）上写或改脚本、或遇到 PowerShell 中文乱码时使用；也用于排查 encoding、BOM、Out-File、chcp 936、中文路径、引号被拆散等问题。覆盖 Windows PowerShell 5.1 与 PowerShell 7 双版本，提供编码检测、按编码落盘、编码无关执行与环境自检四个工具。触发词：写脚本、生成脚本、ps1、PowerShell 脚本、bat、cmd 批处理、脚本编码、中文乱码、UTF-8 BOM、run_ps.py。
---

# 中文 Windows 写脚本规范

适用环境：Windows 10/11 简体中文（系统 ANSI 代码页 936）、Windows
PowerShell 5.1、PowerShell 7.4+、未开启系统级 UTF-8；Git Bash / MSYS2
侧为 UTF-8。目标是让脚本在这些边界上不再反复踩同一个坑。

## 0. 三步走通

1. **看清这台机器**：`scripts/Get-WinScriptEnvironment.ps1`。一次报出
   ACP、OEMCP、控制台输入/输出代码页、`$OutputEncoding`、
   `[Encoding]::Default`、CP936 是否可用、当前是 5.1 还是 7。
   这些是**四个不同的设置**，混为一谈是绝大多数误判的来源。
2. **读一份参考**：按下表只读与当前任务相关的那一份，不要全量加载。
3. **交付前自检**：`scripts/Test-ScriptEncoding.ps1 -Path <文件>` 必须
   `VERDICT=OK`、退出码 0。它不是风格检查，是字节级判定。

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

违反其中任何一条都要返工，细节见对应参考文件。

1. **`.ps1` 里出现非 ASCII 字符 → 存 UTF-8 with BOM。** 5.1 对无 BOM
   文件按系统 ANSI 代码页（936）解析，UTF-8 中文会变成乱码字符串；7 对
   无 BOM 文件按 UTF-8 解析。带 BOM 是两边都对、别的工具也读得懂的推荐
   存法（UTF-16 带 BOM 也能跑，但只有它一家认，别用）。纯 ASCII 的
   脚本存无 BOM 即可。
2. **不要用 `>`、`>>`、`Out-File`、`Set-Content` 写文件。** 5.1 下它们
   产出 UTF-16LE + BOM 或 ANSI，Python、Node、git 读进来就是乱码。改
   `[System.IO.File]::WriteAllText($p, $s, $utf8NoBom)`，写前读回校验。
3. **中文与嵌套引号不要手拼命令行。** 用 argv 列表调用时 Windows 的命令行
   本身是 Unicode，不丢字；丢字发生在字节层：GBK 的 `.bat` 里写的命令、
   Shell 把参数重新拼成字符串、以及把 stdout 按错的代码页解码。要稳就走
   文件：`-File`，或 `scripts/run_ps.py`。需要真实文件语义（`$PSScriptRoot`、
   相对 dot-source）用它的 `--invoke-file`，见 `references/execution.md`。
4. **不要假设 profile 生效。** agent 宿主普遍以
   `-NoProfile -NonInteractive` 启动，`$PROFILE` 不会被加载。需要编码
   兜底就在脚本开头显式写，不要依赖用户配置。

## 3. 工具

四个工具都只依赖 PowerShell 5.1 自带的 .NET 与 Python 标准库，不需要装模块、
不需要管理员权限。

- `scripts/Get-WinScriptEnvironment.ps1` —— 只读自检。`-Output Json`
  出机器可读报告，`WARNING=` 行只在条件真的成立时出现。
- `scripts/Test-ScriptEncoding.ps1` —— 字节级检测。报告 BOM、非 ASCII
  字节数、严格 UTF-8 是否成立、CP936 往返是否无损，再按目标消费方
  （ps51 / ps7 / cmd / python / bash / data）给 OK/WARN/FAIL。只认证据：
  解不成 UTF-8 不等于就是 GBK，只有往返完全一致才标 gbk。`WARN` 不等于
  能跑：`cp1252` / `shift_jis` / `big5` 这类名字 Python 认、本工具没有字节
  表，会输出 `SOURCE_CODING_PAYLOAD=unverified`（负载未验证）。
- `scripts/New-EncodedScript.ps1` —— 按指定编码落盘。中文内容通过文件
  传入而不走命令行；先写临时文件、读回复验、再原子替换；默认拒绝覆盖，
  要覆盖必须显式 `-Force`。
- `scripts/run_ps.py` —— 编码无关地执行脚本。`--command` / `--file` /
  `--stdin` 把正文走 `-EncodedCommand`，没有文件上下文；`--invoke-file`
  用原生 `-File`，保留 `$PSScriptRoot` 与 `$PSCommandPath`。默认不改执行
  策略、不改控制台编码；它不是沙箱。退出码：子进程原样透传，3 本地错误，
  124 超时，127 找不到指定 shell。

## 4. 边界

这些工具解决的是**编码与传输层**问题，不管权限、沙箱或安全审计。默认一律
「不改系统状态」：不注入 `-ExecutionPolicy Bypass`、不自动提权、不改 `ACP`。
要改必须显式传参，理由见 `references/security.md`。

## 5. 已知限制

- Windows PowerShell 5.1 是系统组件，不能卸载，也没有就地升级到 7 的路
  径。装了 7 也不影响工具继续以绝对路径调用 5.1。
- 系统级 UTF-8（Beta 选项）需重启，且会让旧 GBK 软件乱码；它**不修**
  `Out-File` 的 UTF-16LE，也不修 `$OutputEncoding` 的 us-ascii。
- 本规范以简体中文 Windows 为默认前提。其他语言/代码页下判据相同，数值按
  `Get-WinScriptEnvironment.ps1` 的实际输出调整。
