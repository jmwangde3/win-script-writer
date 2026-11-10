---
name: win-script-writer
description: 在中文 Windows（zh-CN / CP936 / Windows PowerShell 5.1）上写或改脚本、或遇到中文乱码时使用。触发词：写脚本、生成脚本、ps1、PowerShell 脚本、bat、cmd 批处理、脚本编码、中文路径乱码、chcp 936、PowerShell 乱码、UTF-8 BOM、Out-File 编码、命令引号被拆散、run_ps.py。内含编码硬规则、四类语言模板、命令传输层免疫、交付检查清单、bat 专项坑与两个验证脚本。
---

# 中文 Windows 写脚本规范

适用环境：Windows 10/11 简体中文（活动代码页 936 / GBK）、Windows PowerShell 5.1、未开启系统级 UTF-8；Bash（Git Bash / MSYS2）侧为 UTF-8。目标是让 AI agent、CI 与人工写的脚本在这些边界上不再反复踩编码坑。

## 0. 与其他规则文件的配合
- 全局指令文件（如 `AGENTS.md` / `CLAUDE.md`）只放一行环境事实 + 兜底命令；详细规则放本文件，按需加载，避免每条会话都常驻长文本。
- 规则更新时同步两处即可，不需要为每个工具重复维护多份副本。
- 遇到中文乱码先按第 2 节判断，不要重新探测环境、不要反复换命令试错。

## 1. 先选语言，再谈编码
1. 能用 Bash 完成 → 用 Bash（`LANG=C.UTF-8`，全链路最干净，中文路径正常）。
2. 需要 Windows API / 注册表 / COM / 服务 / .NET → PowerShell。
3. 需要双击运行、计划任务、老系统兼容 → `.bat/.cmd`（限制最多，见第 5 节；**新脚本尽量别选**）。
4. 数据处理、文件读写 → Python，但所有 `open()` / `read_text()` / `write_text()` 必须显式 `encoding="utf-8"`（中文 Windows 默认 cp936，不写必炸）。

## 2. 硬规则（违反即返工）
1. 路径含中文（示例 `D:\work\项目`）→ 一律加引号，PowerShell 优先 `-LiteralPath`。
2. 写文件显式 UTF-8 **无 BOM**：PS 用 `[System.IO.File]::WriteAllText($p,$s,$utf8NoBom)`；Python 用 `encoding="utf-8"`；Bash 天然 OK。
3. 读文件显式 UTF-8：`Get-Content -Raw -Encoding UTF8` / `open(..., encoding="utf-8")`。
4. 禁用 PS 5.1 的裸 `Out-File` / `>` / `Set-Content` / `Add-Content`（产出 UTF-16LE + BOM，Python/Node 读会炸）。
5. stdout / 日志用 **ASCII 或英文标签**；中文只放在文件内容里，不放在命令输出里。
6. 很多 AI agent 工具以 `-NoProfile -NonInteractive` 启动 PowerShell，profile 不加载：每条命令开头显式写 `$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)`。**不要依赖 profile 兜底**。
7. 含中文字面量的 `.ps1` 必须存 **UTF-8 with BOM**；纯 ASCII 的 `.ps1` 存无 BOM 即可（PS 5.1 对无 BOM 文件按 GBK 解析）。
8. 交付前跑 `scripts/Test-ScriptEncoding.ps1` 自检。
9. 命令同时含中文路径与嵌套引号时，不要直接拼 `-Command`：用 `scripts/run_ps.py`（UTF-16LE Base64 `-EncodedCommand` + 编码 prelude），或把脚本落盘为 UTF-8 with BOM 的 `.ps1` 再 `-File` 执行。部分 agent 工具会拦截命令行里直接出现的 `-EncodedCommand`，所以通过包装脚本调用。

## 3. 模板

### PowerShell（含中文时必须 UTF-8 with BOM）
```powershell
#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding = $Utf8NoBom   # -NoProfile sessions need this explicitly
# Write: [System.IO.File]::WriteAllText($path, $text, $Utf8NoBom)
# Read : Get-Content -LiteralPath $path -Raw -Encoding UTF8
# Log in ASCII so any host decodes it safely.
Write-Output "OK: script started"
```

### Bash（首选）
```bash
#!/usr/bin/env bash
set -euo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8
# Chinese paths are fine here; quote every variable.
```

### Python
```python
from pathlib import Path
p = Path(r"D:\work\项目\data.txt")        # r-string + quotes
p.write_text("中文内容", encoding="utf-8")   # never omit encoding
print(p.read_text(encoding="utf-8"))
```

### .bat / .cmd（存成 **ANSI/GBK(936) 无 BOM**）
```bat
@echo off
chcp 936 >nul
rem ASCII-only body. Keep Chinese text in an external UTF-8 file,
rem let PowerShell/Python read it. Never put Chinese literals here.
```

## 4. 交付检查清单
- [ ] 脚本语言按第 1 节选过，没为了省事默认 `.bat`
- [ ] 所有路径加引号；PS 用 `-LiteralPath`
- [ ] 所有读写都显式 `utf-8`，没有裸 `>` / `Out-File` / `open()` 默认编码
- [ ] `.ps1` 含中文 → UTF-8 **带** BOM；`.bat` 含中文 → GBK **无** BOM
- [ ] stdout 只有 ASCII/英文
- [ ] `Test-ScriptEncoding.ps1` 返回 `VERDICT=OK`
- [ ] 实际跑一次（含中文路径的那条分支），别只看语法

## 5. .bat / .cmd 的坑（比 PowerShell 更严重，zh-CN / CP936 环境实测）
cmd.exe 按**当前活动代码页**（`chcp 936` / GBK）逐字节解析批处理文件本身，且不认 BOM。同一份含中文与中文路径的脚本，四种存法的实测结果：

| 文件编码 | 中文路径 `if exist "D:\work\项目"` | 首行 | `echo 中文 > out.txt` 的字节 |
| --- | --- | --- | --- |
| UTF-8 无 BOM | **PATH_FAIL**（UTF-8 字节被当 GBK 字符） | 正常 | `E4 B8 AD E6 96 87` |
| UTF-8 with BOM | PATH_FAIL | **报错** `'<EF BB BF>@echo' 不是内部或外部命令`，且 `@echo off` 失效、满屏命令回显 | `E4 B8 AD E6 96 87` |
| GBK(936) 无 BOM | **PATH_OK** | 正常 | `D6 D0 CE C4`（GBK） |
| UTF-8 无 BOM + 首行 `chcp 65001 >nul` | **PATH_OK** | 正常 | `E4 B8 AD E6 96 87` |

- **最稳：.bat/.cmd 存成 ANSI/GBK(936) 无 BOM**。必须用 UTF-8 时，首行 `chcp 65001 >nul` 且文件无 BOM（本机实测可用；老版本 Win10 在 65001 下 `for /f`、管道、重定向有历史 bug，换机器要重测）。
- `echo 中文 > out.txt` 写出的是**当前代码页字节**：936 下是 GBK，Python 按 UTF-8 读必乱。别让 bat 产出数据文件，改由 PowerShell/Python 写。
- `for /f` 读 UTF-8 文件、`findstr` 匹配中文、`|` 管道跨进程，全是代码页边界，逐条踩。
- **新脚本不写 .bat**；已有 .bat 保持 ASCII 骨架 + `chcp 936` 显式声明，中文内容外置到 UTF-8 数据文件由 PowerShell/Python 读取。

## 6. 附带工具
- `scripts/New-EncodedScript.ps1 -Path <目标> -ContentFile <UTF-8源> -Encoding utf8-nobom|utf8-bom|gbk`：按指定编码落盘，避开 argv 的 CP936 损耗（中文通过文件传入，不走命令行）。
- `scripts/Test-ScriptEncoding.ps1 -Path <文件>`：检查 BOM、非 ASCII 字节、严格 UTF-8，输出 `VERDICT=OK/WARN/FAIL` + 原因。
- `scripts/run_ps.py`：命令传输层免疫（中文路径 + 引号 + stdout 编码一次解决），用法 `python scripts/run_ps.py '<命令>'`。
- 用户目录 `Microsoft.PowerShell_profile.ps1` 仅对**用户自己开的交互式窗口**做兜底；`-NoProfile` 会话不加载它，所以第 2 节第 6 条必须显式写。

## 7. 错误 → 一条修复
| 现象 | 直接改这一条 |
| --- | --- |
| 输出中文变 `锘/涓/锟斤拷` | 别在 stdout 输出中文，改 ASCII 标签，并设 `[Console]::OutputEncoding` |
| 读文件中文全乱 | `Get-Content -Raw -Encoding UTF8` |
| 写的 txt 打不开 / Python 报错 | 用 `WriteAllText(..., $Utf8NoBom)`，别用 `>` / `Out-File` |
| 管道传中文给程序变 `??` | `$OutputEncoding = $Utf8NoBom` |
| `.ps1` 里中文字符串是乱码 | 文件另存为 UTF-8 **with BOM** |
| `.bat` 第一行报「不是内部或外部命令」 | 去掉 UTF-8 BOM，存 GBK 无 BOM |
| `.bat` 中文路径找不到 | 文件存 GBK，或改调 PowerShell/Bash |
| Python `UnicodeDecodeError` | 所有 `open()` 加 `encoding="utf-8"` |
| 「字符串缺少终止符」/ 引号被拆散 / 中文路径失效 | 走 `scripts/run_ps.py`，别把复杂命令直接拼 `-Command` |

## 8. 环境自检与已知限制
- 自检命令：`chcp`、`[Console]::OutputEncoding.WebName`、`$OutputEncoding.WebName`、`$PSVersionTable.PSEdition`。
- 即使装了 PowerShell 7，若工具仍以绝对路径调用 5.1 且 7 的 stdout 继承控制台代码页（`gb2312`），agent 侧乱码依旧；5.1 是 Windows 系统组件，不能卸载，也没有就地升级到 7 的路径。
- 系统级 UTF-8（Beta: Use Unicode UTF-8 for worldwide language support）需重启且会让旧 GBK 软件乱码；控制台级 `CodePage=65001` 影响面更小。二者都**不修** `Out-File` 的 UTF-16LE 与 `$OutputEncoding` 的 ASCII，仍需第 2 节。
