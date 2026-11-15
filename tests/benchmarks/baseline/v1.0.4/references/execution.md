# 执行：怎么把脚本跑起来

"写对了"和"跑对了"是两件事。这一页讲第二种，重点是**中文参数怎么过命令行**。

## 1. 五种方式

| 方式 | 命令行里有什么 | 文件上下文 | 适用 |
| --- | --- | --- | --- |
| `-Command "<文本>"` | 脚本正文 | 无 | 一次性简单查询 |
| `-File script.ps1` | 只有路径 | 有 | 默认选择 |
| `-EncodedCommand <base64>` | UTF-16LE 的 base64 | 无 | 宿主拦截 `-File`、或必须内联时 |
| `run_ps.py --command/--file/--stdin` | 由包装器决定 | **无** | agent / CI 里统一入口 |
| `run_ps.py --invoke-file <path>` | 只有路径 | **有** | 需要真实 `$PSScriptRoot` 时 |

### 中文到底在哪一层丢

"命令行按 ANSI 代码页解码"这句话太粗，会让人修错地方。实测下来是三层，
只有第二层和第三层会丢字：

| 层 | 机制 | 会不会丢中文字符 |
| --- | --- | --- |
| Windows 进程 API | `CreateProcessW` 收 UTF-16 命令行；用 argv 列表调用时由运行时拼好 | 不丢。实测 `-Command 'Write-Output "中文"'` 用 argv 调用，输出正确 |
| 字节层 | GBK 的 `.bat` 里写死的命令、Shell 把参数重拼成字节串、把文件当命令行喂 | 会丢。这些位置的编码由代码页决定 |
| 宿主解码层 | 捕获 stdout 后按哪个代码页解码 | 决定你"看到"的是不是乱码。5.1 按控制台输出代码页写 stdout，用 UTF-8 解就是乱码 |

所以真正的触发条件是"**某人把字符串变成了字节又没声明编码**"，不是
`-Command` 这个名字。同一个 `-Command`，argv 调用不丢字，写进 GBK 的 bat
再执行就会丢。判据：**能不走字节层就不走。**

### 嵌套引号的第二重风险

引号是另一个独立问题：`-Command` 的文本先被调用方拼一次，再被 PowerShell
的语法解析器解析一次，两次的引号规则不同。`-Command "Write-Output \"a 'b c'\""`
这类写法是否成立取决于**调用方**怎么拼，而不是 PowerShell 怎么解析。

`-File` 只有路径过一个边界，路径由 `CreateProcess` 按 Unicode 传递，不经
任何代码页，也不参与语法解析。

### 为什么 `-EncodedCommand` 一定安全

它把脚本文本编码成 **UTF-16LE**，再 base64。整条命令行是纯 ASCII，不含
中文也不含引号，因此没有任何一层需要"猜编码"。PowerShell 收到后先 base64
解码得到 UTF-16LE 字节，再按 UTF-16 还原字符串——无损。

代价：命令行长度。Windows 单条命令行上限 32767 字符，base64 会把体积放大到
约 2.7 倍（UTF-16LE 两字节 + base64 4/3）。超出时 PowerShell 直接报
`[WinError 206] 文件名或扩展名太长`，脚本根本没启动。

`scripts/run_ps.py` 的阈值是 `MAX_COMMAND_LINE_CHARS = 30000`，超过就写
临时 `.ps1`（UTF-8 with BOM）再用 `-File` 跑。**这个降级会改变文件上下文**，
所以它会在 stderr 上明说，见第 2 节。

## 2. `run_ps.py`：两种模式，别混

### 2.1 文本模式（`--command` / `--file` / `--stdin` / 位置参数）

脚本**正文**走 `-EncodedCommand`。它不是 `-File`，同一个脚本在这里和在
`-File` 下的行为不一样，差别就在文件上下文（本机实测）：

```
powershell -File .\probe.ps1     ROOT/CMD/MINE = C:\...\中文目录
run_ps.py --file .\probe.ps1     ROOT/CMD/MINE = ""（空）
```

`$PSScriptRoot` 为空，`$PSCommandPath` 为空，`$MyInvocation.MyCommand.Path`
为空，于是 `.\helper.ps1`、`"$PSScriptRoot\x.ps1"` 这类相对引用全部失效。
文本模式适合"跑几句看结果"，不适合跑一个依赖自己位置的脚本。

脚本超过命令行上限时会被写成临时文件再 `-File`，这时 `$PSScriptRoot` 变成
**临时目录**——同一个脚本因长度不同而换上下文。这个降级会在 stderr 上打
三行 `run_ps.py: note:`，明确告诉你去用 `--invoke-file`。不要忽略它。

### 2.2 原始文件模式（`--invoke-file <path>`）

路径原样交给子进程的 `-File`，文件**不被读取、不被解码、不被复制、不被改写**：

```bash
python scripts/run_ps.py --invoke-file .\script.ps1
python scripts/run_ps.py --invoke-file .\script.ps1 --script-args -Value 11
```

本机实测，同一份脚本：

```
ROOT=[C:\...\中文目录]
CMD=[C:\...\中文目录\脚本.ps1]
MINE=[C:\...\中文目录\脚本.ps1]
PARAM=11
HELPER=from-helper      # . "$PSScriptRoot\helper.ps1" 生效
```

中文目录、中文文件名、`param()`、`[CmdletBinding()]`、相对 dot-source 全部
按原生行为工作。`--script-args` 之后的参数原样转发给脚本，仍然走 argv 列表，
没有 shell。

它**不**注入 `-ExecutionPolicy Bypass`。策略拦下脚本时你拿到的是策略报错和
非零退出码，不是"悄悄绕过"：

```bash
python scripts/run_ps.py --invoke-file .\script.ps1 --execution-policy Restricted
# File ... cannot be loaded because running scripts is disabled on this system.
# exit 1
```

不兼容的组合直接报错（退出码 3），不会静默忽略：`--invoke-file` 与
`--console-encoding`、`--input-encoding`、`--command`、`--file`、`--stdin`、
位置参数互斥。前两个都要求改写文件内容，而这个模式承诺不改写。

### 2.3 通用开关

```bash
# 位置参数就是脚本正文
python scripts/run_ps.py 'Write-Output "hello"'

# 显式长选项
python scripts/run_ps.py --command 'Get-ChildItem -LiteralPath "D:\work\项目"'
python scripts/run_ps.py --file .\script.ps1
python scripts/run_ps.py - < script.ps1
echo 'Get-Date' | python scripts/run_ps.py --stdin

# 指定宿主
python scripts/run_ps.py --shell pwsh --command '$PSVersionTable.PSEdition'
python scripts/run_ps.py --shell powershell 'chcp'
```

默认行为：**什么都不注入**。不加 `-ExecutionPolicy Bypass`，不改
`[Console]::OutputEncoding`，不改 `$OutputEncoding`。需要时显式加：

```bash
python scripts/run_ps.py --execution-policy Bypass --command '...'
python scripts/run_ps.py --console-encoding utf8 --command '...'
```

输入编码默认 `utf-8-sig`（能吃掉 BOM）。源码不是 UTF-8 时：

```bash
python scripts/run_ps.py --input-encoding gbk --file legacy.ps1
```

超时默认 300 秒，`--timeout 0` 表示不限：

```bash
python scripts/run_ps.py --timeout 30 --command '...'
```

### 用了 `--console-encoding` 时脚本会被包一层

`--console-encoding` 要在你的脚本之前插入几句设置。但 `param(...)` 和
`[CmdletBinding()]` 只允许出现在脚本或脚本块的**第一条语句**，直接前置会让
PowerShell 报 `param : The term 'param' is not recognized`，然后**照常把
剩下的语句跑完并退出 0**——一个静默失效。

所以带上这个参数时，脚本会被包成：

```powershell
<prelude>; & {
<你的脚本>
}
```

两个可见影响：报错行号会整体偏移一行以上；脚本体在一个子作用域里执行
（`$script:` 仍指向外层脚本作用域，`exit` 仍退出整个进程）。不带
`--console-encoding` 时不会加这层包装，脚本原样执行。

### stderr 里可能出现 `#< CLIXML`

PowerShell 在输出流被重定向时，会把 `Write-Progress` 之类的进度记录序列化成
CLIXML 写进 stderr。这不是错误，也不是 `run_ps.py` 加的——它是子进程真实的
stderr 字节。第一次运行（模块首次加载）最容易碰到。

需要干净 stderr 时，在自己的脚本开头写：

```powershell
$ProgressPreference = 'SilentlyContinue'
```

`run_ps.py` 不替你设这个，因为它会改变脚本自己的可见行为。

## 3. 退出码

`run_ps.py` 的退出码是**契约**，不要改：

| 码 | 含义 |
| --- | --- |
| 子进程的码 | 脚本自己的退出码，原样透传 |
| 3 | 包装器本地失败：用法错误、参数互斥、文件读不到、输入解不成声明的编码 |
| 124 | 超时 |
| 127 | `--shell` 指定的宿主找不到 |

用法错误走 3 而不是 argparse 默认的 2，因为 2 会和"子进程退出 2"撞车。
这四条都有测试覆盖（`tests/python/test_run_ps.py`）。0.x 版本曾经对失败的
子进程返回 0，是这次重写专门修掉的。

## 4. `-File` 的两个陷阱

### 陷阱一：`process` 块可能整个不执行

用 `-File` 启动且宿主重定向了 stdin 时，Windows PowerShell 5.1 会跳过
`process` 块，但参数照样绑定成功。表现是脚本"跑了、没报错、什么也没做"。

写带 `[Parameter(ValueFromPipeline)]` 的工具脚本时，见
`references/powershell-51.md` 的兜底写法。

### 陷阱二：`exit` 不终止进程

`& child.ps1` 里的 `exit 7` 只设置 `$LASTEXITCODE`，父进程继续。要在测试
或包装脚本里拿到真实退出码，必须显式 `exit $LASTEXITCODE`。

## 5. 执行策略的现实

agent 宿主通常以 `-NoProfile -NonInteractive` 启动，但**不加**
`-ExecutionPolicy`。脚本能否运行取决于当前进程生效的策略，用
`Get-WinScriptEnvironment.ps1` 的 `EXECUTIONPOLICY` 查看。

本规范的主张：**工具不替用户放宽策略**。

- 工具自己的默认值不带 `Bypass`，理由见 `references/security.md`。
- 需要放宽时由调用者显式传参，并且这一行应该出现在调用点附近，能被
  code review 看到。
- 不要把 `Set-ExecutionPolicy` 写进任何脚本：它改的是机器状态，不是这一次
  调用。

## 6. 选择流程

1. 脚本已经是一份文件，且它需要自己的位置 → `run_ps.py --invoke-file`
   （或直接 `-File`）。
2. 脚本只有几句、但含中文 → 落盘成 UTF-8 with BOM 的 `.ps1`，再 `-File`。
3. 宿主拦截了 `-File`，或必须内联 → 位置参数 / `--command`；此时接受
   "没有文件上下文"这个前提。
4. 需要跨宿主一致（5.1 与 7 都测）→ 同一条 `run_ps.py` 命令，只换
   `--shell`。
5. 需要"跑完告诉我哪些文件有问题" → 用工具的结构化输出与退出码，不要
   解析人类可读文本里的中文。
