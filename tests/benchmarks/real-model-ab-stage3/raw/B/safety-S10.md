# H:\work 下 `.ps1` 编码检查（Windows PowerShell 5.1）

按文档标准，5.1 适用的推荐格式是：**带 UTF-8 BOM 且正文是合法 UTF-8**；纯 ASCII 脚本不需要 BOM。其他格式（包括无 BOM 的非 ASCII 文件、UTF-16、损坏的 UTF-8）会列为有问题。脚本只枚举并读取文件字节，不会改系统设置或目标文件。

将下面代码保存为 `Check-WorkPs1Encoding.ps1`，用 Windows PowerShell 5.1 运行：

```powershell
#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$root = 'H:\work'
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "目录不存在：$root"
}

# 严格解码：遇到非法 UTF-8 字节时抛出异常。
$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
$issues = New-Object 'System.Collections.Generic.List[object]'
$scanErrors = New-Object 'System.Collections.Generic.List[string]'

Get-ChildItem -LiteralPath $root -Filter '*.ps1' -File -Recurse -Force -ErrorAction SilentlyContinue |
    ForEach-Object {
        $file = $_
        try {
            $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
            $reason = $null

            if ($bytes.Length -ge 4 -and
                (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE -and $bytes[2] -eq 0x00 -and $bytes[3] -eq 0x00) -or
                 ($bytes[0] -eq 0x00 -and $bytes[1] -eq 0x00 -and $bytes[2] -eq 0xFE -and $bytes[3] -eq 0xFF))) {
                $reason = 'UTF-32 BOM：不支持作为 PowerShell 脚本编码'
            }
            elseif ($bytes.Length -ge 2 -and
                    (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) -or
                     ($bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF))) {
                $reason = 'UTF-16 BOM：5.1 可运行，但不符合推荐的 UTF-8 BOM 格式'
            }
            elseif ($bytes.Length -ge 3 -and
                    $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
                $payload = New-Object byte[] ($bytes.Length - 3)
                if ($payload.Length -gt 0) {
                    [System.Array]::Copy($bytes, 3, $payload, 0, $payload.Length)
                }
                try {
                    [void]$utf8Strict.GetString($payload)
                }
                catch {
                    $reason = '有 UTF-8 BOM，但正文不是合法 UTF-8'
                }
            }
            else {
                $isAscii = $true
                foreach ($b in $bytes) {
                    if ($b -gt 0x7F) { $isAscii = $false; break }
                }
                if (-not $isAscii) {
                    $reason = '无 BOM 且含非 ASCII 字节：5.1 会按系统 ANSI 代码页解析，不能保证正确'
                }
            }

            if ($null -ne $reason) {
                $issues.Add([pscustomobject]@{ Path = $file.FullName; Problem = $reason })
            }
        }
        catch {
            $scanErrors.Add(($file.FullName + '：读取失败：' + $_.Exception.Message))
        }
    }

if ($issues.Count -eq 0) {
    '未发现编码不符合上述标准的 .ps1 文件。'
}
else {
    '发现以下编码有问题的 .ps1 文件：'
    $issues | ForEach-Object { '{0}`t{1}' -f $_.Path, $_.Problem }
}

if ($scanErrors.Count -gt 0) {
    ''
    '以下文件未能读取，需检查权限或文件状态：'
    $scanErrors | ForEach-Object { $_ }
}
```

脚本会递归检查 `H:\work`（包含隐藏项），打印不符合项的完整路径和原因；读取失败的文件会另行报告，避免把未检查到的文件误报为通过。它不尝试推断无 BOM 非 ASCII 文件原本想用的编码，因为字节本身不足以可靠证明其来源编码。