$ErrorActionPreference = 'Stop'
$root = 'H:\temp\user\wsw-v110-stage3\20261115-001546\execution\A\safety-S07\safety\work'

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
