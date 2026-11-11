# 执行：怎么把脚本跑起来

"写对了"和"跑对了"是两件事。这一页讲第二种，重点是**中文参数怎么过命令行**。

## 1. 四种方式

| 方式 | 命令行里有什么 | 中文参数 | 嵌套引号 | 适用 |
| --- | --- | --- | --- | --- |
| `-Command "<文本>"` | 脚本正文 | **会坏** | **会坏** | 一次性简单查询，纯 ASCII |
| `-File script.ps1` | 只有路径 | 安全 | 安全 | 默认选择 |
| `-EncodedCommand <base64>` | UTF-16LE 的 base64 | 安全 | 安全 | 宿主拦截 `-File`、或必须内联时 |
| `python run_ps.py …` | 由包装器决定 | 安全 | 安全 | agent / CI 里统一入口 |

### 为什么 `-Command` 会坏

命令行是**字节串**，Windows 按当前 ANSI 代码页（936）解码它，然后
PowerShell 再对解码结果做一次引号解析。中文和引号在这条路上会经过两次
解释：

- 中文：UTF-8 宿主写入的字节被按 936 读成别的字符
- 引号：`"` 与 `'` 的配对规则再走一遍，`-Command "a 'b c'"` 这类嵌套直接
  变成"字符串缺少终止符"

`-File` 只有路径过一个边界，且路径由 `CreateProcess` 按 Unicode 传递，
没有代码页参与。

### 为什么 `-EncodedCommand` 一定安全

它把脚本文本编码成 **UTF-16LE**，再 base64。整条命令行是纯 ASCII，
不含中文也不含引号，因此没有任何一层需要"猜编码"。PowerShell 收到后先
base64 解码得到 UTF-16LE 字节，再按 UTF-16 还原字符串——无损。

代价：命令行长度。Windows 单条命令行上限 32767 字符，base64 会把体积
放大到约 2.7 倍（UTF-16LE 两字节 + base64 4/3）。实测超出时 PowerShell
直接报 `[WinError 206] 文件名或扩展名太长`，脚本根本没启动。

`scripts/run_ps.py` 的阈值是 `MAX_COMMAND_LINE_CHARS = 30000`，超过就
自动改成"写临时 `.ps1`（UTF-8 with BOM）+ `-File`"。

## 2. `run_ps.py` 用法

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
| 3 | 包装器本地失败：用法错误、文件读不到、输入解不成声明的编码 |
| 124 | 超时 |
| 127 | `--shell` 指定的宿主找不到 |

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

1. 脚本已经是一份文件 → `-File`（或 `run_ps.py --file`）。
2. 脚本只有几句、但含中文 → 落盘成 UTF-8 with BOM 的 `.ps1`，再 `-File`。
3. 宿主拦截了 `-File`，或必须内联 → `run_ps.py` 的位置参数 / `--command`。
4. 需要跨宿主一致（5.1 与 7 都测）→ 同一条 `run_ps.py` 命令，只换
   `--shell`。
5. 需要"跑完告诉我哪些文件有问题" → 用工具的结构化输出与退出码，不要
   解析人类可读文本里的中文。
