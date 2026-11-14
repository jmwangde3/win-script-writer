# win-script-writer

中文 Windows（zh-CN / 代码页 936 / GBK）上写脚本用的编码规范与四个工具。
面向 AI agent，也面向人。

## 解决什么

这些现象在简中 Windows 上反复出现，而且看起来像四件不同的事，实际是四条
独立的断链：

- `Get-Content` 读 UTF-8 文件得到「涓」「锟斤拷」
- `Out-File` / `>` 写出的 txt，Python 和 Node 读不了
- 中文参数传给 `git.exe`、`python.exe` 变成 `?`
- `.ps1` 里的中文字符串是乱码
- `.bat` 第一行报「不是内部或外部命令」
- 中文路径加嵌套引号报「字符串缺少终止符」
- Python 不写 `encoding` 就炸
- 脚本退出码 0，但什么都没做

## 适用环境

Windows 10/11 简体中文，系统 ANSI 代码页 936，Windows PowerShell 5.1，
PowerShell 7.4+，未开启系统级 UTF-8；Git Bash / MSYS2 侧为 UTF-8。

其他语言或代码页环境下判据相同，具体数值以
`scripts/Get-WinScriptEnvironment.ps1` 的实际输出为准。

## 快速开始

```bash
git clone https://github.com/jmwangde3/win-script-writer.git
cd win-script-writer
```

先看清这台机器（只读，不需要管理员）：

```powershell
powershell -NoProfile -File scripts/Get-WinScriptEnvironment.ps1
```

输出是一串 `KEY=value`。四个关键值：

```
ACP=936                 # 系统 ANSI 代码页，5.1 用它解析无 BOM 脚本
CONSOLEOUTCP=936        # 当前控制台输出代码页
OUTPUTENCODING=us-ascii # 5.1 往原生程序 stdin 灌字符串时用的编码（不含 argv）
PSEDITION=Desktop       # Desktop = 5.1，Core = 7
```

检查一个文件到底是什么：

```powershell
powershell -NoProfile -File scripts/Test-ScriptEncoding.ps1 -Path .\build.ps1
```

按指定编码落盘（默认拒绝覆盖；不传 `-Encoding` 时按扩展名选）：

```powershell
# .ps1 自动用 utf8-bom，正是 5.1 与 7 都认的存法
powershell -NoProfile -File scripts/New-EncodedScript.ps1 `
    -Path .\build.ps1 -ContentFile .\source.txt

# 需要别的编码就显式传
powershell -NoProfile -File scripts/New-EncodedScript.ps1 `
    -Path .\legacy.cmd -ContentFile .\source.txt -Encoding gbk -Force -Backup
```

含中文地执行一段脚本：

```bash
python scripts/run_ps.py 'Write-Output "hello"'
python scripts/run_ps.py --shell pwsh --command '$PSVersionTable.PSEdition'

# 需要一个真实文件上下文（$PSScriptRoot、相对 dot-source）时：
python scripts/run_ps.py --invoke-file .\script.ps1
```

## 四个工具

| 工具 | 作用 | 只读 |
| --- | --- | --- |
| `scripts/Get-WinScriptEnvironment.ps1` | 报告 ACP / OEMCP / 控制台代码页 / `$OutputEncoding` / 运行时版本 | 是 |
| `scripts/Test-ScriptEncoding.ps1` | 字节级检测编码：连 BOM 之后的负载一起验，识别 UTF-32 四字节签名与 Python 的 PEP 263 声明，按目标消费方给 OK/WARN/FAIL | 是 |
| `scripts/New-EncodedScript.ps1` | 按编码落盘，临时文件 + 读回校验 + 原子替换；默认编码按扩展名推导 | 否，需显式 `-Force` 才覆盖 |
| `scripts/run_ps.py` | 编码无关地执行脚本。文本模式走 UTF-16LE base64，`--invoke-file` 走原生 `-File` | 否，执行指定内容 |

退出码是契约：检测器 `0/1/2/3`，写入器 `0/2/3` + `4`（用户在确认提示上选了
「否」，**没有写入**；`-WhatIf` 仍是 0，只是预览），
`run_ps.py` 子进程码透传 + `3/124/127`。

## 装成 skill

Claude Code（个人级 / 项目级都支持）：

```bash
# 个人级
mkdir -p ~/.claude/skills/win-script-writer
cp -r SKILL.md references scripts ~/.claude/skills/win-script-writer/

# 项目级
mkdir -p .claude/skills/win-script-writer
cp -r SKILL.md references scripts .claude/skills/win-script-writer/
```

目录名（或 frontmatter 的 `name`）就是 `/win-script-writer` 这个命令。
Claude Code 按 `description` 决定何时自动加载。

只读 `AGENTS.md` / `CLAUDE.md` 类规则文件的宿主：把 `SKILL.md` 的路径写进去，
例如「写 Windows 脚本前先读 `<repo>/SKILL.md`」。不要把这些内容复制进规则
文件——复制出来的副本会漂移。

## 目录结构

```
SKILL.md                     入口，只放路由表与四条硬规则
references/                  10 份按需加载的细节
  encoding-matrix.md         哪种文件存哪种编码（含实测字节表）
  powershell-51.md           5.1 的四条断链与正确写法
  powershell-7.md            7 改对了什么、仍然坏在哪
  dual-version-compatibility.md  一个脚本跑两个版本的禁区
  cmd-bat.md                 .bat 四种存法的实测结果
  python.md                  默认编码不是 UTF-8
  git-bash.md                MSYS 路径转换与 git quotepath
  execution.md               四种执行方式的取舍
  security.md                工具默认不做什么
  troubleshooting.md         症状 → 一条修复
scripts/                     四个工具
tests/                       Pester + unittest + 契约检查
```

`SKILL.md` 必须保持小（当前约 5.3 KB），细节全部在 `references/`。这是
progressive disclosure 的前提：入口文件大了，就等于每次都全量加载。

## 设计取舍

- **只认证据，不猜。** 解不成 UTF-8 不能证明是 GBK——CP936 在 .NET 里没有
  未定义字节，`0xFF` 会映射到 `U+F8F5`。只有解码再编码字节完全一致才标
  `gbk`，且只给 medium 置信度。
- **`WARN` 不代表文件能跑。** Python 的 codec 名表比检测器能验的多：`cp1252`、
  `shift_jis`、`big5` 这类名字在验证过的 CPython 上成立，但检测器没有对应字节表，
  正文里有没有非法字节它看不见。这种情况报 `WARN` +
  `SOURCE_CODING_PAYLOAD=unverified`（JSON `SourceCodingPayload`），说明
  「名字落在兼容集合里、但当前解释器可能不支持它、负载未验证」，而不是假装
  `OK`。名字表本身是按族组织的精确表，不是前缀正则——`mac-bogus` 之类的仿写
  一律 `FAIL`；反过来，`base64` / `rot13` 这类解析得了但不能作源码的转换器
  是 `FAIL` + `PY_SOURCE_CODING_UNUSABLE`，与「名字不认识」分开报。
- **默认不改系统状态。** 不注入 `-ExecutionPolicy Bypass`、不自动提权、
  不改 `ACP`、不覆盖已有文件、不把无法编码的字符换成 `?`。理由见
  `references/security.md`。
- **不用 `Add-Type`。** 拿 Win32 代码页需要运行时编译 C#，而有些安全策略
  正好禁止这个。诊断工具必须在受限环境里也能跑，所以改用注册表与 .NET
  控制台层取值，并把来源写进输出（`ACPSOURCE=`）。
- **双版本都要过。** 每个阶段都在 Windows PowerShell 5.1 与 PowerShell 7
  下各跑一遍同一套测试，不接受「理论上兼容」。

## 测试

```powershell
# 全部
powershell -NoProfile -File tests\run-all.ps1
pwsh       -NoProfile -File tests\run-all.ps1

# 单套
powershell -NoProfile -File tests\run-all.ps1 -Suite pester
powershell -NoProfile -File tests\run-all.ps1 -Suite analyze
powershell -NoProfile -File tests\run-all.ps1 -Suite python
powershell -NoProfile -File tests\run-all.ps1 -Suite integration
powershell -NoProfile -File tests\run-all.ps1 -Suite evals
```

Python 侧用标准库 `unittest`，不需要 `pip install`。Pester 需要 5.7.1：

```powershell
Install-Module Pester -RequiredVersion 5.7.1 -Scope CurrentUser
Install-Module PSScriptAnalyzer -Scope CurrentUser
```

## 已验证范围

先分清三件事，混起来就会把「跑过」说成「支持」。

**正式验证矩阵（CI 六个作业，每次推送都跑）**：Windows PowerShell 5.1 与
Python 3.11、5.1 与 3.13、PowerShell 7 与 3.11、PowerShell 7 与 3.13、
UTF-8 模式预览（Python 3.13 + `PYTHONUTF8=1`）、docs contract。托管 runner 是
en-US / ACP 1252，CP936 相关用例在那里跳过自己；CP936 的断言只在自托管 runner
（`cp936.yml`，仓库尚未注册这种 runner，所以它还没跑过）或本机上成立，
**跳过不算通过**。

**额外实测（手工跑过，不进 CI）**：Windows 11 简体中文 ACP=936 / OEMCP=936，
PowerShell 5.1.26100（Desktop）与 7.7.0（Core），Pester 5.7.1、
PSScriptAnalyzer 1.24.0，Python 3.11.17 / 3.13.9 / 3.13.16 / 3.14.8 / 3.15.0rc3。

**尚未纳入正式矩阵**：Python 3.14 与 3.15。它们的别名表比本项目采样过的更宽，
检测器还没跟上：同一套别名回归在 3.14.8 上有 6 处分歧、3.15.0rc3 上有 58 处
（清单见 `CHANGELOG.md` 的「已知未覆盖」）。UTF-8 模式作业模拟的是 3.15 的默认
行为，**不是** 3.15 兼容测试。在这些版本上，检测器会把个别解释器能编译的文件
判 `FAIL`——方向是「多说一句」，不是放行。

其他环境没有实测过。判据可以复用，数字请自己跑
`Get-WinScriptEnvironment.ps1` 确认。

codec 别名的全量回归不写死名单：测试现场遍历 `encodings.aliases` 与
`encodings/` 下的模块名，逐个 `compile()` 后再问检测器。3.13.9 上是 471 个
拼写（327 个别名键 + 98 个规范名 + 121 个模块名 + 24 个仿写拼写，去重后）、
380 个可作源码、91 个被拒、0 处分歧；3.13.16 上是 479 个（多出的是 gh-149801
给 `cp858` / `cp1140` 的前导零别名，从 3.13.14 起才有），同样 0 处分歧。
换解释器版本数字会变，判据不变。

本机（ACP=936）的一次性验证记录与「跳过不等于覆盖」的说明在
`tests/cp936/README.md`。

## 许可

MIT，见 `LICENSE`。
