# PowerShell 7.4：写 UTF-8 无 BOM，并让重定向输出不带颜色控制字符

```powershell
#Requires -Version 7.4
$ErrorActionPreference = 'Stop'

# PowerShell 7.4+ 将终端颜色装饰从重定向输出中去掉。
$PSStyle.OutputRendering = 'PlainText'

# 明确指定 UTF-8 无 BOM；不要依赖默认编码。
$path = Join-Path $PSScriptRoot 'result.txt'
$text = "第一行：中文`r`n第二行：UTF-8 无 BOM"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($path, $text, $utf8NoBom)

# 示例输出也会在重定向时以纯文本写入。
Write-Output "已写入：$path"
```

将上面的内容保存为 `write-file.ps1`，用 PowerShell 7.4 运行：

```powershell
pwsh -NoProfile -File .\write-file.ps1 > .\run.log
```

`result.txt` 由 `WriteAllText` 明确写成 UTF-8 无 BOM。`$PSStyle.OutputRendering = 'PlainText'` 会让 PowerShell 在输出被重定向时不附加 ANSI 颜色序列；它不负责清理脚本自己写出的、原本就包含 ESC 字符的字符串。`>` 在这里仅重定向控制台输出，不用于写 `result.txt`。