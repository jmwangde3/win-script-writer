# 双版本兼容：一个脚本同时跑在 5.1 与 7

原则只有一条：**要么只用 5.1 也认识的写法，要么在运行时分叉，绝不在
同一份文件里混用 7 专属语法。**

原因是解析时机：7 专属语法在 5.1 上是**解析期错误**，`try/catch` 抓不到，
整个文件根本不会开始执行。你以为的"优雅降级"不存在。

## 1. 语法禁区（5.1 上直接解析失败）

| 写法 | 从哪个版本可用 | 5.1 上的表现 |
| --- | --- | --- |
| `$a ? $b : $c` 三元 | 7.0 | 解析错误 |
| `$a ?? $b` / `$a ??= $b` 空合并 | 7.0 | 解析错误 |
| `cmd1 && cmd2` / `cmd1 \|\| cmd2` | 7.0 | 解析错误 |
| `Get-Content -AsByteStream` | 6.0 | 参数不存在（用 `-Encoding Byte`） |
| `Join-Path -AdditionalChildPath` | 6.0 | 参数不存在 |
| `ConvertFrom-Json -AsHashtable` | 6.0 | 参数不存在 |
| `Out-File -Encoding utf8BOM` | 6.0 | 取值不在集合内 |
| `ForEach-Object -Parallel` | 7.0 | 参数不存在 |
| `$IsWindows` / `$IsLinux` / `$IsMacOS` | 6.0 | 变量不存在（StrictMode 下报错） |
| `[System.Text.Encoding]::Latin1` | .NET Core | 属性不存在 |
| `Test-Json` | 6.1 | 命令不存在 |

## 2. 行为差异（语法合法，但结果不同）

这些比语法禁区更危险：脚本能跑，只是产出的字节不同。

| 项目 | 5.1 | 7 |
| --- | --- | --- |
| 无 BOM `.ps1` 的解析编码 | 系统 ANSI（936） | UTF-8 |
| `Out-File` / `>` 默认 | UTF-16LE + BOM | UTF-8 无 BOM |
| `Set-Content` / `Add-Content` 默认 | ANSI 无 BOM | UTF-8 无 BOM |
| `Set-Content -Encoding UTF8` | **带** BOM | **不带** BOM |
| `$OutputEncoding` | `us-ascii` | `utf-8` |
| `[Encoding]::Default` | ANSI(936) | `utf-8` |
| `Get-Content` 读 GBK 文件 | 正确 | 四个 `U+FFFD` |
| `Join-Path $a 'b' 'c'`（三参数） | 报错 `A positional parameter cannot be found` | 正常 |

上表每一行都有实测支撑，载荷与字节见 `references/encoding-matrix.md`。

## 3. 唯一安全的写法

### 3.1 只用交集语法

```powershell
#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Utf8Bom = New-Object System.Text.UTF8Encoding($true)

# 两个版本都认的路径拼接
$dir = Join-Path (Join-Path $root 'sub') 'file.txt'
# 或者
$dir = [System.IO.Path]::Combine($root, 'sub', 'file.txt')

# 两个版本都认的编码表达
[System.IO.File]::WriteAllText($path, $text, $Utf8NoBom)
```

### 3.2 必须分叉时，先判版本再调函数

```powershell
$isCore = $PSVersionTable.PSEdition -eq 'Core'

if ($isCore) {
    $bytes = Get-Content -LiteralPath $path -AsByteStream -TotalCount 4
}
else {
    $bytes = Get-Content -LiteralPath $path -Encoding Byte -TotalCount 4
}
```

关键：7 专属语法必须写在**独立函数或独立文件的字符串里**，不能直接出现在
公共代码路径上，否则 5.1 连解析都过不去。真要执行 7 专属代码，用
`[scriptblock]::Create()` 延迟解析，或者干脆起一个子进程跑另一个文件。

## 4. 落盘编码

跨版本脚本自身必须 **UTF-8 with BOM**（见
`references/powershell-51.md` 断链一）。这是唯一两边都对的存法。

不要为了"7 上更干净"而存无 BOM：那等于放弃 5.1。

## 5. 验证方法

不要靠"我记得这不支持". 写一个 probe，用两个宿主各跑一次，比较输出。

本项目的做法：

```powershell
# 同一个脚本，两个宿主
powershell.exe -NoProfile -File tests\run-all.ps1 -Suite pester
pwsh.exe       -NoProfile -File tests\run-all.ps1 -Suite pester
```

`tests/run-all.ps1` 用 `(Get-Process -Id $PID).Path` 取"当前宿主"，所有
子套件都用同一个版本执行，这样"在 5.1 下全部通过"和"在 7 下全部通过"
是同一条命令的两次运行，不是两套人肉步骤。

对 CI：把 `runs-on` 与 shell 做成矩阵，见 `.github/workflows/test.yml`。

## 6. 常见误判

- **"我在 7 上测过了"**：7 通过不代表 5.1 通过，尤其编码相关。
- **"加了 `#Requires -Version 7.0` 就安全了"**：这只是提前报错，不是兼容。
  双版本脚本应该是 `#Requires -Version 5.1`。
- **"用 `$PSVersionTable.PSVersion.Major -ge 7` 包住就行"**：包住的是
  运行期分支，解析期照样失败。`if ($true) { $a ? $b : $c }` 在 5.1 上
  一样是解析错误。
- **"`-Encoding UTF8` 是通用写法"**：它在两版上产出的字节不同，是双版本
  脚本里最容易漏的一条。
