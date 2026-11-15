#Requires -Version 7.4
$ErrorActionPreference = 'Stop'

# 不让 PowerShell 的输出装饰在重定向时带入 ANSI 颜色控制序列。
$PSStyle.OutputRendering = 'PlainText'

# 示例：写入 UTF-8 无 BOM 文件。
$path = Join-Path $PSScriptRoot 'output.txt'
$text = "中文内容`r`n第二行"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($path, $text, $utf8NoBom)

# 命令输出要保存到文件时，也在重定向前设置 PlainText，例如：
# Get-ChildItem | Out-File -LiteralPath $path -Encoding utf8NoBOM