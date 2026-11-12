# 变更记录

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号按 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.1] - 2026-11-12

稳定性修复。1.0.0 的三个编码判定错误、`run_ps.py` 的文件语义含糊、写入器
默认值与它自己的规范互相矛盾，这三类问题都在这一版修掉，并且每条都换成了
"先测量再判定"的实现。

### Changed（会改变既有行为，需注意）

- **`Test-ScriptEncoding.ps1` 对 UTF-16 脚本的判定从 `FAIL` 改为 `WARN`。**
  1.0.0 的理由是"Windows PowerShell 5.1 无法可靠解析 UTF-16 脚本"，这句
  话没有验证过，而且是错的：实测 5.1.26100 与 7.7.0 都能解析执行带 BOM 的
  UTF-16LE 与 UTF-16BE 脚本，中文正确。`WARN` 表达的是"能跑但不推荐"——
  `cmd.exe`、`git diff`、多数编辑器按单字节读。真实不成立的是**没有 BOM**
  的 UTF-16，那个仍然 `FAIL`。
  **影响**：用 `-Profile ps51` / `ps7` 检查 UTF-16LE/BE 文件时退出码从 2
  变成 1；带 `-FailOnWarning` 的调用方退出码仍是 2。
- **`New-EncodedScript.ps1` 的默认编码按扩展名推导。** 1.0.0 对任何目标都
  默认 `utf8-nobom`，于是用它写一个含中文的 `.ps1`，产出的正是检测器
  （`-Profile ps51`）判 `FAIL` 的文件——两个工具互相矛盾。现在 `.ps1` /
  `.psm1` / `.psd1` → `utf8-bom`，`.bat` / `.cmd` → `gbk`，其余 →
  `utf8-nobom`；显式 `-Encoding` 永远优先。结果新增
  `ENCODING_SOURCE=explicit|extension`。
- **`run_ps.py` 的用法错误退出码从 2 改为 3。** argparse 默认用 2 表示用法
  错误，与"子进程退出 2"撞车。

### Added

- **`run_ps.py --invoke-file <path>`：保留真实文件上下文的执行模式。**
  路径原样交给子进程的 `-File`，不读、不解码、不复制、不改写文件，因此
  `$PSScriptRoot`、`$PSCommandPath`、`$MyInvocation.MyCommand.Path`、
  `param()`、`[CmdletBinding()]`、相对 dot-source 全部按原生行为工作。
  `--script-args` 之后的内容原样转发给脚本（argv 列表，无 shell）。
  与 `--console-encoding` / `--input-encoding` / `--command` / `--file` /
  `--stdin` / 位置参数互斥，冲突时退出码 3 并说明原因。
- 检测器输出新增 `PAYLOAD_VALID` 与 `PAYLOAD_PROBLEM` 两个字段；编码名新增
  `utf8-bom-invalid` / `utf16le-bom-invalid` / `utf16be-bom-invalid`。
- `tests/cp936/verify-local.ps1`：在真实 zh-CN 机器上一次性跑完 CP936 门禁
  的全部检查，不需要注册自托管 runner。
- `tests/integration/test_package.py`：解压发布包并实际执行里面的工具。
- `test.yml` 新增 `python-utf8-mode` 作业：用 `PYTHONUTF8=1` 模拟 Python
  3.15 的默认 UTF-8 模式（PEP 686），确认默认值改变后行为不退化。

### Fixed

- **UTF-8 BOM 被当成"文件是 UTF-8"的证据，从不检查后面的字节。**
  `EF BB BF FF`、`EF BB BF C3 28`、`EF BB BF E4 B8` 全部返回
  `ENCODING=utf8-bom`、`STRICT_UTF8=True`、`VERDICT=OK`、退出码 0。BOM 是
  声明，不是内容合法的证明，现在标记之后的字节一律严格解码，失败就
  `FAIL` 并给出首个坏字节的偏移。UTF-16 的 BOM 同理，另外单独拦奇数字节与
  孤立代理项。
- **`-ExpectedEncoding ascii` 与 `utf8-nobom` 被当成互兼容。** 一个含 18 个
  非 ASCII 字节的文件在 `-Profile ps7` 下通过了 `-ExpectedEncoding ascii`，
  输出还会出现 `EXPECTED_MATCH=True` 与 `VERDICT=FAIL` 并存的自相矛盾行。
  现在 ascii 的含义是"每个字节都在 0x00–0x7F"，方向不对称：纯 ASCII 满足
  `utf8-nobom`，反之不成立；带 BOM 不算 ASCII。
- **`run_ps.py --file` 的文件上下文随脚本长度变化。** 短脚本走
  `-EncodedCommand`，`$PSScriptRoot` 为空；长脚本被写成临时文件走 `-File`，
  `$PSScriptRoot` 变成临时目录。同一个脚本因长度不同换语义，且没有任何
  提示。现在降级时在 stderr 打三行 `run_ps.py: note:`，点名
  `--invoke-file`。
- **写入器的备份文件会被覆盖。** 备份名是秒级时间戳，而 `File.Replace`
  会覆盖同名备份，同一秒内两次写入会销毁前一个备份。现在遇到同名自动加
  序号。
- **写入失败仍打印 `WROTE=<路径>`。** 失败路径上"已写入"这一行最容易被
  当真，现在非零退出码不再输出该字段。
- `run_ps.py` 的临时目录创建失败、清理失败不再抛异常：分别返回 3 与保持
  子进程退出码。

### Verified

- Windows PowerShell 5.1.26100（Desktop）与 PowerShell 7.7.0（Core）各跑
  一遍完整矩阵：Pester 77、Python 47、文档契约 38、集成 22、
  PSScriptAnalyzer 12 文件 0 告警。
- CP936：本机 ACP=936，`CP936_ASSERTIONS_EXECUTED`。**GitHub 上的
  `cp936` 工作流仍未运行**——仓库没有注册自托管 runner，也没有设置
  `CP936_RUNNER` 变量，每次 push 的结果都是 `skipped`。跳过不等于通过，
  记录见 `tests/cp936/README.md`。
- Python 3.13.9 在默认模式与 `PYTHONUTF8=1`（`sys.flags.utf8_mode=1`）下
  各跑一遍：Python 47、集成 22，全部通过。**没有 3.15 解释器，Python 3.15
  本身未验证**，`python-utf8-mode` 作业只模拟它的默认值。
- 发布包：18 个条目、72,867 字节、全正斜杠、无 `.pyc` 与测试物料，
  每个条目与检出逐字节一致；解压到干净目录后三个工具实跑通过，
  `--invoke-file` 的 `$PSScriptRoot` 指向脚本自身目录。
- `git diff --check origin/main..HEAD` 无告警。

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
  成为测试矩阵的一员，而不是"记得就跑一次"的命令。分析范围从
  `scripts/` 扩到 `scripts/` + `tests/`，其中测试树单独排除
  `PSUseDeclaredVarsMoreThanAssignments`（Pester 5 的 `BeforeAll` 作用域
  会让真用到的变量看起来没用到），`tests/fixtures/data` 作为测试载荷
  整体跳过。
- `tests/package.ps1`：发布打包与 release notes 生成，可本地复跑。CI 的
  发布作业调用它，而不是把逻辑写进 YAML。
- 三个工作流：`test.yml`（5.1 / 7 × Python 3.11 / 3.13 矩阵 + 文档契约）、
  `cp936.yml`（自托管 936 runner，宿主不是 936 时直接失败而不是跳过）、
  `release.yml`（只在推 `v*` 标签时运行）。
- `CONTRIBUTING.md`、本 `CHANGELOG.md`。

### Changed

- `SKILL.md` 从 8.5 KB 的单体规则文本改为 5.3 KB 的入口文件：只保留
  路由表、四条硬规则、工具清单与边界声明。细节全部下沉到 `references/`。
- `README.md` 重写：快速开始、四个工具的退出码契约、安装方式、已验证范围。
- `tests/integration/test_pipeline.py` 不再假设子进程总以 CP936 编码
  stdout。原来直接断言 GBK 字节，只要宿主把控制台改成 UTF-8 就误报失败；
  改为用 `GetConsoleOutputCP()` 取真实代码页再断言字符。

### Fixed

- **`run_ps.py --console-encoding` 让 `param()` 静默失效。** prelude 拼在
  用户脚本前面，而 `param(...)` 与 `[CmdletBinding()]` 只允许是第一条语句，
  于是 PowerShell 报 `param : The term 'param' is not recognized`，**照常
  跑完剩下的语句并退出 0**。带参数块的真实脚本走 `--file` 时会静默丢掉所有
  参数。现在只在需要注入 prelude 时才把脚本体包进 `& { … }`，默认路径一个
  字节都不变。新增三个用例：`param()` 不被挤掉、prelude 在包装内仍然生效、
  末尾注释不会把收尾的 `}` 吃掉。
- **检测器在 `-File` 加重定向 stdin 时静默返回 `files=0`。** Windows
  PowerShell 会跳过 `process` 块但照常绑定参数，脚本因此从未打开文件却
  退出码 0。现在逐文件工作抽成 `Add-Inspection`，`end` 里在
  `$script:pipelineRan` 仍为 false 时补跑。
- **打包脚本把 release notes 写成了乱码。** `Get-Content` 不带
  `-Encoding` 时 5.1 按 CP936 解码这份 UTF-8 的 `CHANGELOG.md`，中文全部
  损坏。这是本仓库记录的第一条断链，出现在本仓库自己的构建脚本里。
- **`Compress-Archive` 在 5.1 上把 zip 条目名写成反斜杠**
  （`win-script-writer\SKILL.md`），不符合 APPNOTE，在按规范处理的解压
  工具上会变成一个文件名含反斜杠的怪文件。改为逐条
  `ZipFileExtensions::CreateEntryFromFile` 并显式把分隔符归一成 `/`，
  打包后重新打开 zip 校验，发现反斜杠即以非零退出码失败。
- **静态分析在参数绑定时只打警告、仍然报 `ANALYZER_CLEAN`。**
  `Invoke-ScriptAnalyzer -Path` 不接受文件数组，绑定失败是非终止错误，
  原来会被吞掉。现在每次调用都 `-ErrorAction Stop`，并且打印
  `ANALYZED_FILES=`，分析 0 个文件也算失败。
- `New-EncodedScript.ps1` 覆盖已有文件时 `File.Replace` 传 `$null` 会报
  "The path is not of a legal form"：`$null` 被绑成空字符串。改为使用
  一次性备份路径并在 `finally` 清理。
- `invalid-bytes.bin` 夹具原本用 `0xFF` 当非法字节，但 CP936 在 .NET 中
  没有未定义字节（`0xFF` → `U+F8F5`），导致它被正确判为 gbk。改用
  `0x81 0x20`（前导字节 + 非法尾字节）。
- 三参数 `Join-Path` 在 5.1 上不可用的写法从测试与工具里全部移除。
- `tests/Common/TestHelpers.ps1` 里的两个死变量（`RepoRootPath`、
  `buffer`）与一个空 `catch` 块。
- **CI 工作流把矩阵表达式喂给了 `shell` 键。** GitHub 在展开矩阵之前就解析
  `jobs.<id>.steps[*].shell`，`shell: ${{ matrix.shell }}` 被判为
  `Unrecognized named-value: 'matrix'`，首次推送 0 秒失败，一个 job 都没起。
  改为每个宿主一个 job，`shell` 一律写字面量。同一处还修掉了 7 把模块装到
  `Documents/PowerShell/Modules` 而 5.1 只查
  `Documents/WindowsPowerShell/Modules` 的问题——共用一个安装步骤等于让 5.1
  那一路退回系统自带的 Pester 3.4。
- **测试依赖的解析散落在每个入口，漏一处就红。** 文档契约要解析工作流文件，
  需要 PyYAML；矩阵 job 装了、发布 job 忘了，于是全绿的分支推 tag 后 1 分 40
  秒失败。改为在测试入口脚本里统一探测并安装，所有入口共用一条路径。过程中
  踩到两个坑：`$ErrorActionPreference = 'Stop'` 会把原生程序的 stderr 变成
  终止错误，于是"预期失败"的探测直接终止脚本；`pip install yaml` 找不到发行
  包——模块名是 `yaml`，发行包名是 `PyYAML`，而且装完必须再探测一次才算数，
  pip 返回 0 从来不能证明 `import` 会成功。
- **发布包里混进了 `scripts/__pycache__/*.pyc`。** 打包直接复制目录，本地检出
  干净，所以十次手跑都是 18 个条目；CI 在同一个检出里先跑测试、留下了字节码
  缓存，实际发出 19 个。现在归档前清掉缓存，并把条目对照扩展名白名单校验
  ——黑名单只能挡住已经想到的东西。同一次发布还暴露了
  `if ($LASTEXITCODE -ne 0)` 把成功的打包判成失败：脚本成功时不设置
  `$LASTEXITCODE`，`$null -ne 0` 成立，报错信息因此打印成 "packaging failed
  with " 后面什么都没有。

### Security

- 明确并文档化六条默认不变的行为：不注入 `-ExecutionPolicy Bypass`、
  不默认覆盖文件、不自动改 `ACP`、不自动提权、`run_ps.py` 不是沙箱、
  不静默替换字符。详见 `references/security.md`。

### Verified

本版所有数字都在下列环境实测：Windows 11 简体中文，ACP=936，OEMCP=936，
Windows PowerShell 5.1.26100（Desktop）、PowerShell 7.6.9（Core），
Pester 5.7.1，PSScriptAnalyzer 1.24.0，Python 3.13。

- Pester：50 项，5.1 与 7 各跑一遍，全通过。
- Python：29 项，全通过。
- 集成：7 项，全通过（其中 CP936 专有 3 项在非 936 宿主上跳过）。
- 文档契约：28 项，全通过。
- PSScriptAnalyzer：`scripts/` 全干净，两个宿主各跑一遍。
- GitHub Actions：`windows-latest` 上 5.1 与 7 各配 Python 3.11 / 3.13，
  四个组合全部 `RESULT=PASSED`；`ubuntu-latest` 跑文档契约。CP936 门禁需要
  带 `self-hosted, windows, cp936` 标签的 runner，未配置时该 job 显示
  skipped，而不是无限排队。

## [0.1.0] - 2026-11-09

首个公开版本。

### Added

- 中文 Windows 编码规则文档（`SKILL.md`）。
- `scripts/Test-ScriptEncoding.ps1`：BOM / 非 ASCII / 严格 UTF-8 检测。
- `scripts/New-EncodedScript.ps1`：按指定编码落盘。
- `scripts/run_ps.py`：UTF-16LE base64 传输，绕开命令行代码页。
- `.bat` / `.cmd` 四种存法的实测对照表。
