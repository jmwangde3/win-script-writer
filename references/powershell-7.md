# PowerShell 7（Core）

7 修掉了 5.1 的四处默认行为中的三处半，但**不是全修**，而且修的方式会
让"同一个脚本在两个版本上产出不同字节"。这一页只讲与编码相关的差异，
以及 7 上仍然会坏的场景。

## 1. 7 改对了什么

| 项目 | 5.1 | 7.4+ |
| --- | --- | --- |
| 无 BOM `.ps1` 按什么解析 | 系统 ANSI（936） | UTF-8 |
| `Out-File` / `>` / `>>` 默认 | UTF-16LE + BOM | UTF-8 无 BOM |
| `Set-Content` / `Add-Content` 默认 | ANSI(936) 无 BOM | UTF-8 无 BOM |
| `$OutputEncoding` | `us-ascii` | `utf-8` |
| `[Encoding]::Default` | ANSI(936) | `utf-8`（无信息量） |
| `-Encoding UTF8` | 带 BOM | 不带 BOM |

实测载荷两个汉字，落盘字节见 `references/encoding-matrix.md` 第 4 节。

注意最后一行：`-Encoding UTF8` 在两版上**产出的字节不同**。跨版本脚本不
要用它，用 `New-Object System.Text.UTF8Encoding($true|$false)` 显式构造。

## 2. 7 仍然会坏的地方

### 读 GBK 文件：静默变成替换字符

7 把无 BOM 文件按 UTF-8 读。一个 GBK 编码的 `.ps1` 或 `.json` 在 7 上不会
报错，而是把每个非法字节读成 `U+FFFD`。实测两个汉字（4 字节 GBK）读出
`65533,65533,65533,65533`。

后果比崩溃更糟：配置里的中文变成四个问号方块，程序继续跑。

判据：任何"可能是 GBK"的输入文件，进 7 之前先用
`Test-ScriptEncoding.ps1` 确认是 `utf8-nobom` 或 `ascii`。

### 域从 5.1 继承的控制台代码页

7 自己的 stdout 走 UTF-8，但 `[Console]::InputEncoding` 仍可能继承控制台
的 936。当 7 把 stdin 交给原生程序时，边界上仍可能按 936 解释。

判据：跨进程传中文时不要靠默认值，显式 `-Encoding utf8` 或直接用
`scripts/run_ps.py`。

### `-EncodedCommand` 之外没必要用 base64

7 的 `-File` 配合 UTF-8 with BOM 脚本已经足够。base64 只在"命令行本身
不可信"时才需要（见 `references/execution.md`）。

## 3. 7 上有用的三个开关

### `$PSNativeCommandArgumentPassing`

较新的 7.x 上有这个变量（5.1 上不存在），本机 7.6.9 实测值为 `Windows`。
它决定 PowerShell 怎么把参数传给原生程序：`Legacy` 是老的行为（重新拼
命令行、吞引号），`Standard` 是新行为，`Windows` 是 Windows 上的默认折中。

含引号或中文的参数传给 `git.exe` 时行为不对，先看这个值：

```powershell
$PSNativeCommandArgumentPassing   # 期望：Standard 或 Windows，不是 Legacy
```

要局部改：`$PSNativeCommandArgumentPassing = 'Standard'`（脚本作用域内有效）。
跨版本脚本里引用前必须判空，否则 5.1 直接报变量不存在。

### `$PSStyle` / 输出装饰

较新的 7.x 上默认给 `Write-Host`、错误记录加 ANSI 转义序列，本机 7.6.9
实测 `$PSStyle.OutputRendering` 为 `Host`。把输出重定向到文件时会混入
`ESC[` 字节，让下游 diff 变脏。批处理场景建议：

```powershell
$PSStyle.OutputRendering = 'PlainText'
```

同样：5.1 上不存在。

### `-Encoding` 的完整取值

7.6.9 实测 `Set-Content` / `Out-File` 接受这些名字：

| 取值 | 落盘字节（载荷为单个汉字） | 说明 |
| --- | --- | --- |
| `utf8` | `E4 B8 AD` | 无 BOM，等同于 `utf8NoBOM` |
| `utf8NoBOM` | `E4 B8 AD` | 无 BOM |
| `utf8BOM` | `EF BB BF E4 B8 AD` | 带 BOM |
| `ansi` | `D6 D0` | 系统 ANSI，本机即 GBK |
| `oem` | `D6 D0` | 系统 OEM，本机同为 936 |
| `bigendianutf32` | `00 00 FE FF …` | 罕见，列在此仅说明取值面 |

写"我要 BOM"时用 `utf8BOM`；5.1 不认识这个值，所以跨版本还是用
`UTF8Encoding` 构造器最稳。

## 4. 写 7 专用脚本时

```powershell
#Requires -Version 7.4
$ErrorActionPreference = 'Stop'

# 读写都显式，别依赖"7 反正默认 UTF-8"
$text = Get-Content -LiteralPath $path -Raw -Encoding utf8
[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))

# 交给原生程序之前确认管道编码
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
```

"7 默认是 UTF-8"成立的是**默认值**，不是**保证**：用户 profile、宿主、
`chcp` 都可能改掉它。所以 7 专用脚本也要显式写编码。

## 5. 别再做的三件事

- 不要为了兼容 5.1 而在 7 专用脚本里加 BOM：多余且会让某些工具把它当
  内容（例如读取"第一行"的解析器）。
- 不要用 `[Encoding]::Default` 判断机器代码页：7 上恒为 utf-8。
- 不要以为装了 7 就等于修好了 5.1：调用方用绝对路径起 5.1 时，7 完全不
  参与。
