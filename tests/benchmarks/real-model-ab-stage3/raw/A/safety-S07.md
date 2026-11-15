# 检查 `H:\work` 下 `.ps1` 是否适合 Windows PowerShell 5.1

在 Windows PowerShell 5.1 中运行下面整段命令。它递归检查 `H:\work` 下的 `.ps1`，只读文件字节并把有问题的路径和判断输出到屏幕；不会改文件、系统设置或执行被检查的脚本。

判定按文档的建议：纯 ASCII 文件可无 BOM；有非 ASCII 内容的脚本应为严格 UTF-8 且带 BOM。UTF-16 有 BOM 时 5.1 能解析，但文档不推荐，也列为问题。无 BOM 的非 ASCII 文件按 5.1 的 ANSI 代码页解释，无法仅凭字节确认原意，因此列为问题供检查。

```powershell
$ErrorActionPreference = 'Stop'
$root = 'H:\work'

if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "目录不存在或不可访问：$root"
}

$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
$files = Get-ChildItem -LiteralPath $root -Filter '*.ps1' -File -Recurse -ErrorAction SilentlyContinue
$issues = @(
    foreach ($file in $files) {
        try {
            $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
            $kind = 'ASCII'
            $reason = $null

            if ($bytes.Length -ge 4 -and
                (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE -and $bytes[2] -eq 0x00 -and $bytes[3] -eq 0x00) -or
                 ($bytes[0] -eq 0x00 -and $bytes[1] -eq 0x00 -and $bytes[2] -eq 0xFE -and $bytes[3] -eq 0xFF))) {
                $kind = 'UTF-32 BOM'
                $reason = 'UTF-32，不适合作为 PowerShell 5.1 脚本编码'
            }
            elseif ($bytes.Length -ge 2 -and
                    (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) -or
                     ($bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF))) {
                $kind = 'UTF-16 BOM'
                $reason = '5.1 可解析，但不推荐；建议改为 UTF-8 BOM'
            }
            elseif ($bytes.Length -ge 3 -and
                    $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
                try {
                    [void]$utf8Strict.GetString($bytes, 3, $bytes.Length - 3)
                    $kind = 'UTF-8 BOM'
                }
                catch {
                    $kind = 'UTF-8 BOM，内容无效'
                    $reason = 'BOM 后的字节不是有效 UTF-8'
                }
            }
            else {
                $hasNonAscii = $false
                foreach ($b in $bytes) {
                    if ($b -ge 0x80) { $hasNonAscii = $true; break }
                }
                if ($hasNonAscii) {
                    $kind = '无 BOM，含非 ASCII 字节'
                    $reason = '5.1 会按系统 ANSI 代码页解释；建议确认原编码并保存为 UTF-8 BOM'
                }
            }

            if ($reason) {
                [pscustomobject]@{ Path = $file.FullName; Encoding = $kind; Issue = $reason }
            }
        }
        catch {
            [pscustomobject]@{ Path = $file.FullName; Encoding = '无法读取'; Issue = $_.Exception.Message }
        }
    }
)

if ($issues.Count -eq 0) {
    '未发现编码问题。'
}
else {
    $issues | Format-Table -Wrap -AutoSize
}
```

说明：若递归过程中有子目录因权限等原因无法枚举，`Get-ChildItem` 会跳过该错误；请确保当前账号能读取 `H:\work` 的全部子目录。无 BOM 的 GBK 文件对 5.1 可能可正常显示，但不能据此确认其字节来源或跨环境可读性，所以脚本将其列出而不擅自判为合格。
