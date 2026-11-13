# 排查：症状 → 一条修复

先跑一次 `Get-WinScriptEnvironment.ps1`，记下 `ACP`、`CONSOLEOUTCP`、
`OUTPUTENCODING`、`PSEDITION` 四个值。后面所有判断都基于这四个值，不要凭
印象。

**一次就够。** 这四个值是一台机器的属性，同一次会话里不会自己变；已经确认
过 ACP=936、OEMCP=936 的机器，不必每轮任务重跑一遍诊断。只有换了机器、换了
宿主（5.1 ↔ 7）、或自己 `chcp` 改过控制台之后才值得重查。

## 1. 先定位是哪一层

| 现象 | 大概率在这一层 |
| --- | --- |
| 终端里中文变方块/问号 | 断链四：stdout 编码 |
| 文件内容好好的，程序读进来乱 | 断链一：读文件解码 |
| 文件写出来 Python/Node 读不了 | 断链二：写文件编码 |
| 中文参数传进程序变成 `?` | 断链三：`$OutputEncoding` |
| 整段脚本报"字符串缺少终止符" | 命令传输层：`-Command` |
| `.bat` 第一行报"不是内部或外部命令" | BOM 出现在 `.bat` 里 |
| 脚本没报错但什么都没做 | `process` 块被跳过 |

## 2. 逐条修复

### 终端显示乱码，但文件是对的

不要在 stdout 输出中文。用 ASCII 标签：

```powershell
Write-Output 'VERDICT=OK'
```

必须输出中文时，先把两端对齐：

```powershell
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
```

注意这只管**当前进程**，宿主解码方式你控制不了。生产脚本用 ASCII 输出。

### `Get-Content` 读出来是"涓"、"锟斤拷"

```powershell
Get-Content -LiteralPath $p -Raw -Encoding UTF8
```

根因：5.1 对无 BOM 文件按 ANSI(936) 解析。永久解法是把文件存成 UTF-8 with
BOM（`.ps1`）或显式声明编码（数据文件）。

### 写出来的 txt/docx/json 打不开

```powershell
[System.IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding($false)))
```

根因：`>`、`>>`、`Out-File` 在 5.1 上产出 UTF-16LE + BOM。

### 管道传给 git/python 的中文变成 `?`

```powershell
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
```

根因：5.1 的 `$OutputEncoding` 是 `us-ascii`（实测 `中` 变成 `3F`）。

### 中文路径 + 嵌套引号报"字符串缺少终止符"

不要拼 `-Command`。把脚本落盘成 UTF-8 with BOM 的 `.ps1`，用 `-File` 跑；
或者：

```bash
python scripts/run_ps.py --command '<你的命令>'
```

### `-Command` 里参数被拆开了

同上。另外看一眼 `$PSNativeCommandArgumentPassing`（7 才有）：如果是
`Legacy`，改成 `Standard`。

### `.bat` 第一行报"不是内部或外部命令"

文件有 UTF-8 BOM。去掉 BOM，存成 GBK 无 BOM，见
`references/cmd-bat.md`。

### `.bat` 里中文路径 `if exist` 找不到

文件不是 GBK。存成 ANSI/GBK(936) 无 BOM，或者首行 `chcp 65001 >nul`
且文件无 BOM。

### 脚本退出码 0 但什么都没做

两种可能：

1. 工具用 `begin/process/end` 且以 `-File` 启动、stdin 被重定向 ——
   `process` 块根本没执行。加 `end` 里的兜底（见
   `references/powershell-51.md`）。
2. `& child.ps1` 里的 `exit 7` 只设置 `$LASTEXITCODE`，没终止父进程。

判据：让脚本在 `end` 里打印 `files=<n>`，如果 `n` 是 0 而参数明明传了，
就是第 1 种。

### Python 报 `UnicodeDecodeError`

```python
open(path, encoding="utf-8")   # 每个 open 都要写
```

如果文件确实是 GBK，写 `encoding="gbk"`，不要靠环境变量。

### Python `print()` 报 `UnicodeEncodeError`

裸环境下 `sys.stdout.encoding` 是 `gbk`（实测）。加：

```python
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
```

或者干脆只输出 ASCII。

### 同一个 Python 脚本，agent 里正常、双击就乱

agent 宿主设了 `PYTHONUTF8=1`，用户环境没有。实测两套环境下
`open(p,'w').write('中文')` 分别写出 UTF-8 与 GBK 字节。修法见
`references/python.md`：代码里写死 `encoding=`。

### `git status` 里中文文件名是 `\344\270\255`

```bash
git -c core.quotepath=false status
```

只是显示问题，仓库内容没坏。

### `New-EncodedScript.ps1` 报 `UNREPRESENTABLE_CHARACTER`

目标编码表达不了源文本里的字符（例如 emoji 存 GBK）。这是**故意**的：
宁可失败也不静默替换成 `?`。换 `utf8-nobom` 或 `utf8-bom`。

### `Test-ScriptEncoding.ps1` 退出码 3

参数或 I/O 问题：路径不存在、指向目录、无权读。看 stderr 的
`ERROR=NOT_FOUND` / `ERROR=IS_DIRECTORY` / `ERROR=READ_FAILED`。

### 两个版本测试结果不一样

先看是不是踩了 `references/dual-version-compatibility.md` 的语法禁区——那些
是**解析期**错误，5.1 上 `try/catch` 抓不到。

### `Test-ScriptEncoding.ps1` 报 `PAYLOAD_VALID=False`

BOM 存在，但标记之后的字节不是合法 UTF-8 / UTF-16。这是坏文件，不是检测器
太严：

```text
ENCODING=utf8-bom-invalid
PAYLOAD_VALID=False
PAYLOAD_PROBLEM=UTF-8 BOM followed by invalid UTF-8 at byte 3: ...
```

修法只有重写：把内容按 UTF-8 重新保存。别去动 BOM，也别把它当 ASCII 用——
`EF BB BF FF` 这种文件在 5.1 里会跑完前半段并以退出码 0 结束。

### 检测器说 UTF-16 文件是 `WARN`

带 BOM 的 UTF-16LE/BE 脚本两个版本都能跑，所以判 `WARN` 而不是 `FAIL`。
WARN 说的是"能用但别用"：`git diff` 当二进制、编辑器读成乱码、`cmd.exe`
完全不认。改造方法是重新存成 UTF-8 with BOM。

判 `FAIL` 的是**没有 BOM** 的 UTF-16（`UTF16_NO_BOM`）——那个真的跑不起来，
而且退出码是 0。

### `run_ps.py --file` 里 `$PSScriptRoot` 是空的

文本模式本来就没有文件上下文：正文走 `-EncodedCommand`，磁盘上没有这个
脚本。换成原始文件模式：

```bash
python scripts/run_ps.py --invoke-file .\script.ps1
```

### `run_ps.py` 在 stderr 打了三行 `note:`，`$PSScriptRoot` 变成临时目录

脚本太长，超过命令行上限，被写成临时文件再 `-File`。这是唯一的合法降级，
但上下文变了，所以它会明说。要真实位置就改 `--invoke-file`。

### `run_ps.py` 说 `--invoke-file cannot honour ...`

`--invoke-file` 和 `--console-encoding` / `--input-encoding` / `--command` /
`--file` / `--stdin` 互斥：这几个都要求改写脚本正文，而原始文件模式承诺
不改写。去掉其中一边。

### 写入器报 `REPLACE_FAILED`

临时文件写成功、读回校验也通过，但替换目标失败——最常见是目标只读或被
占用。原文件保持不动，报错里带 .NET 的原始消息。

### `New-EncodedScript.ps1` 写入的编码不是我想要的

不传 `-Encoding` 时按扩展名选：`.ps1/.psm1/.psd1` → `utf8-bom`，
`.bat/.cmd` → `gbk`，其余 → `utf8-nobom`。结果里的
`ENCODING_SOURCE=extension|explicit` 告诉你是哪条规则生效的。

## 3. 三步定位法

1. **看机器**：`Get-WinScriptEnvironment.ps1` → 四个代码页 + 版本。
2. **看文件**：`Test-ScriptEncoding.ps1 -Path <文件>` → `ENCODING=` 和
   `VERDICT=`，不要只看结论。
3. **看传输**：含中文的调用改走 `run_ps.py`，如果这样就正常，问题一定在
   命令行层。

## 4. 不要做的事

- 不要用 `chcp 65001` 去"修"文件编码：它改的是窗口，不是文件。
- 不要重新探测环境反复试错：四个值一次就能看清。
- 不要把"重装 PowerShell 7"当成解法：5.1 还在，坑还在。
- 不要在修好一个现象后顺手改 `ACP`：那是系统级状态，不是这次任务的产物。
