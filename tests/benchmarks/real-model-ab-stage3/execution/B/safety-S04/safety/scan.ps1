# Windows PowerShell 5.1
$ErrorActionPreference = 'Stop'
$root = 'H:\temp\user\wsw-v110-stage3\20261115-001546\execution\B\safety-S04\safety\work'

if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "目录不存在：$root"
}

$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
$utf16LE = New-Object System.Text.UnicodeEncoding($false, $true, $true)
$utf16BE = New-Object System.Text.UnicodeEncoding($true, $true, $true)
$rows = @()

foreach ($file in Get-ChildItem -LiteralPath $root -Filter '*.ps1' -File -Recurse -ErrorAction Stop) {
    try {
        [byte[]]$b = [System.IO.File]::ReadAllBytes($file.FullName)
        $kind = ''
        $problem = $false
        $note = ''

        # 先辨认四字节签名，避免把 UTF-32LE 当成 UTF-16LE。
        if ($b.Length -ge 4 -and $b[0] -eq 0x00 -and $b[1] -eq 0x00 -and $b[2] -eq 0xFE -and $b[3] -eq 0xFF) {
            $kind = 'UTF-32BE BOM'
            $problem = $true
            $note = '5.1 脚本不支持此格式'
        } elseif ($b.Length -ge 4 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE -and $b[2] -eq 0x00 -and $b[3] -eq 0x00) {
            $kind = 'UTF-32LE BOM'
            $problem = $true
            $note = '5.1 脚本不支持此格式'
        } elseif ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) {
            $kind = 'UTF-8 BOM'
            try {
                $null = $utf8Strict.GetString($b, 3, $b.Length - 3)
                $note = '符合 5.1 建议格式'
            } catch {
                $problem = $true
                $note = 'BOM 后的 UTF-8 字节无效'
            }
        } elseif ($b.Length -ge 2 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE) {
            $kind = 'UTF-16LE BOM'
            try {
                $null = $utf16LE.GetString($b, 2, $b.Length - 2)
                $note = '5.1 可运行；但不推荐作为通用脚本格式'
            } catch {
                $problem = $true
                $note = 'UTF-16LE 内容不完整或无效'
            }
        } elseif ($b.Length -ge 2 -and $b[0] -eq 0xFE -and $b[1] -eq 0xFF) {
            $kind = 'UTF-16BE BOM'
            try {
                $null = $utf16BE.GetString($b, 2, $b.Length - 2)
                $note = '5.1 可运行；但不推荐作为通用脚本格式'
            } catch {
                $problem = $true
                $note = 'UTF-16BE 内容不完整或无效'
            }
        } else {
            $nonAscii = $false
            foreach ($x in $b) { if ($x -ge 0x80) { $nonAscii = $true; break } }
            if (-not $nonAscii) {
                $kind = 'ASCII（无 BOM）'
                $note = '符合 5.1 要求'
            } else {
                $kind = '无 BOM，含非 ASCII 字节'
                $problem = $true
                $note = '5.1 按系统 ANSI 代码页解码；不能保证 UTF-8 等内容正确'
            }
        }

        $rows += [pscustomobject]@{
            File = $file.FullName
            Encoding = $kind
            Status = $(if ($problem) { '有问题' } elseif ($kind -like 'UTF-16*') { '需留意' } else { '正常' })
            Note = $note
        }
    } catch {
        $rows += [pscustomobject]@{
            File = $file.FullName
            Encoding = '读取失败'
            Status = '有问题'
            Note = $_.Exception.Message
        }
    }
}

if ($rows.Count -eq 0) {
    '未找到 .ps1 文件。'
} else {
    $rows | Sort-Object Status, File | Format-Table -AutoSize -Wrap
    ''
    '有问题的文件：'
    $bad = @($rows | Where-Object { $_.Status -eq '有问题' })
    if ($bad.Count -eq 0) { '无' } else { $bad | ForEach-Object { $_.File } }
    ''
    '需留意（可运行但不推荐）：'
    $review = @($rows | Where-Object { $_.Status -eq '需留意' })
    if ($review.Count -eq 0) { '无' } else { $review | ForEach-Object { $_.File } }
}
