# 变更记录

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号按 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-11-11

第一个按契约重写的版本。0.1.0 是一份写给人看的规则加两个脚本；1.0.0 把
它拆成"入口 + 参考 + 工具 + 测试"四层，并且每个断言都有实测或测试支撑。

### Added

- `scripts/Get-WinScriptEnvironment.ps1`：只读自检，报告 ACP / OEMCP /
  控制台输入输出代码页 / `$OutputEncoding` / `[Encoding]::Default` /
  CP936 可用性 / 运行时版本 / `EXECUTIONPOLICY`。`-Output Json` 出机器
  可读报告，条件成立时附 `WARNING=` 行。
- `references/` 下 10 份参考，按 Progressive Disclosure 组织：
  `encoding-matrix`、`powershell-51`、`powershell-7`、
  `dual-version-compatibility`、`cmd-bat`、`python`、`git-bash`、
  `execution`、`security`、`troubleshooting`。
- `tests/analyze.ps1` 与 `tests/run-all.ps1 -Suite analyze`：静态分析
  成为测试矩阵的一员，而不是"记得就跑一次"的命令。
- `CONTRIBUTING.md`、本 `CHANGELOG.md`。

### Changed

- `SKILL.md` 从 8.5 KB 的单体规则文本改为 5.3 KB 的入口文件：只保留
  路由表、四条硬规则、工具清单与边界声明。细节全部下沉到 `references/`。
- `README.md` 重写：快速开始、四个工具的退出码契约、安装方式、已验证范围。
- `tests/integration/test_pipeline.py` 不再假设子进程总以 CP936 编码
  stdout。原来直接断言 GBK 字节，只要宿主把控制台改成 UTF-8 就误报失败；
  改为用 `GetConsoleOutputCP()` 取真实代码页再断言字符。

### Fixed

- **检测器在 `-File` 加重定向 stdin 时静默返回 `files=0`。** Windows
  PowerShell 会跳过 `process` 块但照常绑定参数，脚本因此从未打开文件却
  退出码 0。现在逐文件工作抽成 `Add-Inspection`，`end` 里在
  `$script:pipelineRan` 仍为 false 时补跑。
- `New-EncodedScript.ps1` 覆盖已有文件时 `File.Replace` 传 `$null` 会报
  "The path is not of a legal form"：`$null` 被绑成空字符串。改为使用
  一次性备份路径并在 `finally` 清理。
- `invalid-bytes.bin` 夹具原本用 `0xFF` 当非法字节，但 CP936 在 .NET 中
  没有未定义字节（`0xFF` → `U+F8F5`），导致它被正确判为 gbk。改用
  `0x81 0x20`（前导字节 + 非法尾字节）。
- 三参数 `Join-Path` 在 5.1 上不可用的写法从测试与工具里全部移除。

### Security

- 明确并文档化六条默认不变的行为：不注入 `-ExecutionPolicy Bypass`、
  不默认覆盖文件、不自动改 `ACP`、不自动提权、`run_ps.py` 不是沙箱、
  不静默替换字符。详见 `references/security.md`。

### Verified

本版所有数字都在下列环境实测：Windows 11 简体中文，ACP=936，OEMCP=936，
Windows PowerShell 5.1.26100（Desktop）、PowerShell 7.6.9（Core），
Pester 5.7.1，PSScriptAnalyzer 1.24.0，Python 3.13。

- Pester：50 项，5.1 与 7 各跑一遍，全通过。
- Python：26 项，全通过。
- 集成：7 项，全通过（其中 CP936 专有 3 项在非 936 宿主上跳过）。
- 文档契约：16 项，全通过。
- PSScriptAnalyzer：`scripts/` 全干净，两个宿主各跑一遍。

## [0.1.0] - 2026-11-09

首个公开版本。

### Added

- 中文 Windows 编码规则文档（`SKILL.md`）。
- `scripts/Test-ScriptEncoding.ps1`：BOM / 非 ASCII / 严格 UTF-8 检测。
- `scripts/New-EncodedScript.ps1`：按指定编码落盘。
- `scripts/run_ps.py`：UTF-16LE base64 传输，绕开命令行代码页。
- `.bat` / `.cmd` 四种存法的实测对照表。
