# Windows PowerShell 5.1（Desktop）

5.1 不是"老一点的 PowerShell"，它在编码上有四处**默认行为**与直觉相反。
本项目把四处合称"四断链"，因为一条链上任意一处断掉，最终表现都是"乱码"
或"文件打不开"，但修法完全不同。

## 1. 四断链

### 断链一：读 —— 无 BOM 的 UTF-8 按 ANSI 代码页解析

`.ps1` 文件本身：解析器先看 BOM。`EF BB BF` 按 UTF-8，`FF FE` 按 UTF-16LE，
`FE FF` 按 UTF-16BE；**没有 BOM 就按系统 ANSI 代码页**（zh-CN 是 936）。

实测：一个只含 `中`（U+4E2D）的 UTF-8 无 BOM 文本
- `Get-Content` 默认读出来码点是 `28051`（`U+6D93` 涓）——不是报错，是错字
- `Get-Content -Encoding UTF8` 读出来是 `20013`（正确）

推理：脚本里的中文字面量、中文注释同理。文件没有 BOM，字符串就已经错了，
运行时再补救也没用。

UTF-16 值得单独说一句，因为流传的说法是错的：**5.1 能跑带 BOM 的 UTF-16
脚本**，LE 和 BE 都实测跑通、中文正确。不能跑的是**没有 BOM 的 UTF-16**
（按单字节切词，首字符就失败）。能跑不等于该用——`cmd.exe`、`git diff`、
编辑器大多按单字节读，详见 `references/encoding-matrix.md` 第 3.1 节。

### 断链二：写 —— `>`、`>>`、`Out-File` 产出 UTF-16LE + BOM

实测（载荷两个汉字）：
- `$s > f` 和 `$s | Out-File f` 都是 `FF FE 2D 4E 87 65 …`，即 UTF-16LE
- `Set-Content` 换个毛病：新文件按 ANSI（`D6 D0 CE C4`）落盘
- `Add-Content` 与 `Set-Content` 同

后果：Python 的 `json.load`、Node 的 `fs.readFileSync`、`git diff` 全崩或
读出乱码。而且 `-Encoding UTF8` 在 5.1 上**会加 BOM**，与 7 的行为相反。

### 断链三：管道给原生程序 —— `$OutputEncoding` 是 `us-ascii`

实测：`[char]0x4E2D | python -c "..."` 读到 stdin 是 `3F`，即 `?`。
非 ASCII 在离开 PowerShell 的那一刻被替换成问号，**没有任何警告**。

**作用面只有管道 stdin，不含命令行参数。** 这一条经常被说错，值得拆开：

| 通道 | 由谁决定编码 | `$OutputEncoding` 有影响吗 |
| --- | --- | --- |
| 管道 stdin（`... \| native.exe`） | `$OutputEncoding`，默认 `us-ascii` | 有，就是它在截 |
| 命令行参数（`native.exe 中文`） | 由 `CreateProcess` 传宽字符，进程自己转 | 没有 |
| PowerShell 自己的 stdout | `[Console]::OutputEncoding` | 没有 |
| 写文件（`Out-File` / `>`） | `-Encoding` 参数，默认 UTF-16LE | 没有 |

所以出现乱码时先判断是哪一层：参数里的中文即使 `$OutputEncoding` 是
`us-ascii` 也能完整到达原生程序；反过来说，把 `$OutputEncoding` 设成 UTF-8
也修不好参数层的问题（那一层的问题通常出在目标程序用 ACP 解 argv，或调用方
用 8.3 短路径之外的方式传参）。stdin、stdout、文件、argv 四种编码互不代偿，
逐层核对才有效。

### 断链四：自己的 stdout —— 按控制台输出代码页编码

5.1 用 `[Console]::OutputEncoding` 写 stdout，该值来自控制台的输出代码页
（普通 zh-CN 控制台是 936/gb2312）。宿主如果按 UTF-8 解码这些字节，就得到
"锟斤拷"。

实测条件差异：本机在被宿主改成 65001 的会话里，5.1 的
`[Console]::OutputEncoding` 也随之变成 `utf-8`。所以**不要记忆"5.1 是
gb2312"**，要用 `Get-WinScriptEnvironment.ps1` 看当前值。

## 2. 四条正确写法

```powershell
#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# 读：显式声明编码，别让解析器猜
$text = Get-Content -LiteralPath $path -Raw -Encoding UTF8

# 写：临时文件 -> 读回复验 -> 原子替换
[System.IO.File]::WriteAllText($temp, $text, $Utf8NoBom)
$back = [System.IO.File]::ReadAllText($temp, $Utf8NoBom)
if ($back -cne $text) { throw 'VERIFY_FAILED' }
[System.IO.File]::Replace($temp, $path, $backupPath, $true)

# 管道给原生程序前，先把它改成 UTF-8
$OutputEncoding = $Utf8NoBom
```

这一套就是 `scripts/New-EncodedScript.ps1` 的实现，包括 `File.Replace`
必须给真实备份路径这一点（传 `$null` 会被绑成空字符串，报
"The path is not of a legal form"）。

## 3. 其他必须知道的 5.1 行为

### `process` 块可能整个不执行

用 `-File` 启动且宿主重定向了 stdin 时，5.1 会**跳过 `process` 块**，
但参数照样绑定成功。表现是脚本返回 `files=0 exit=0`——静默假通过。

写工具脚本时要么不用 `begin/process/end`，要么在 `end` 里补一个兜底：

```powershell
process { $script:pipelineRan = $true; ... }
end { if (-not $script:pipelineRan) { ... 处理 $Path ... } }
```

这个坑是本项目实测踩出来的：集成测试一度全绿，因为检测器根本没看文件。

### 三参数 `Join-Path` 不存在

`Join-Path $a 'b' 'c'` 在 5.1 报
`A positional parameter cannot be found that accepts argument 'b'`。
用 `Join-Path (Join-Path $a 'b') 'c'` 或 `[IO.Path]::Combine($a,'b','c')`。

### `exit` 在子脚本里不死进程

`& child.ps1` 里写 `exit 7`，只会把 `$LASTEXITCODE` 设成 7，父脚本继续跑。
实测确认。测试里要拿到真实退出码，需要显式 `exit $LASTEXITCODE`。

### 代码页提供程序

`[Text.Encoding]::GetEncoding(936)` 在 .NET Framework 上开箱可用。
.NET Core 上需要 `CodePagesEncodingProvider`（PowerShell 7 自己注册了；
裸宿主不一定）。工具脚本里应写 try/catch 并显式注册，见
`scripts/Test-ScriptEncoding.ps1` 的 `Get-CodePageEncoding`。

### `[Encoding]::Default`

5.1 上等于系统 ANSI 代码页（本机实测 `gb2312`）。7 上恒为 `utf-8`，
不携带任何机器信息——所以"用 `[Encoding]::Default` 探测 ACP"只在 5.1 成立。

## 4. 不要做的事

- 不要用 `chcp 65001` 去"修"5.1 的乱码：它改的是控制台代码页，不改
  `Out-File` 的 UTF-16LE，也不改 `$OutputEncoding` 的 us-ascii。
- 不要依赖 `$PROFILE`：agent 宿主以 `-NoProfile` 启动。
- 不要把 `[Console]::OutputEncoding` 当成脚本内部编码设置：它只管 stdout。
- 不要指望把 5.1 "升级"成 7：它是系统组件，没有就地升级路径。
