$root = ''H:\work''
$issues = New-Object ''System.Collections.Generic.List[object]''

try {
    $files = Get-ChildItem -LiteralPath $root -Filter ''*.ps1'' -File -Recurse -Force -ErrorAction Stop
} catch {
    Write-Error (''无法枚举 {0}: {1}'' -f $root, $_.Exception.Message)
    return
}

foreach ($file in $files) {
    try {
        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)

        if ($bytes.Length -ge 4 -and
            (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE -and $bytes[2] -eq 0x00 -and $bytes[3] -eq 0x00) -or
             ($bytes[0] -eq 0x00 -and $bytes[1] -eq 0x00 -and $bytes[2] -eq 0xFE -and $bytes[3] -eq 0xFF))) {
            $issues.Add([pscustomobject]@{ Path = $file.FullName; Reason = ''UTF-32 BOM：不支持/不适合作为 PowerShell 脚本编码'' })
            continue
        }

        if ($bytes.Length -ge 2 -and
            (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) -or
             ($bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF))) {
            $issues.Add([pscustomobject]@{ Path = $file.FullName; Reason = ''UTF-16 BOM：5.1 可运行，但不是推荐的脚本格式'' })
            continue
        }

        $hasUtf8Bom = $bytes.Length -ge 3 -and
            $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
        $start = if ($hasUtf8Bom) { 3 } else { 0 }
        $hasNonAscii = $false
        for ($i = $start; $i -lt $bytes.Length; $i++) {
            if ($bytes[$i] -ge 0x80) {
                $hasNonAscii = $true
                break
            }
        }

        if (-not $hasNonAscii) {
            continue
        }

        if (-not $hasUtf8Bom) {
            $issues.Add([pscustomobject]@{ Path = $file.FullName; Reason = ''含非 ASCII 字节但没有 UTF-8 BOM；5.1 会按系统 ANSI 代码页解析'' })
            continue
        }

        try {
            $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
            $payload = New-Object byte[] ($bytes.Length - 3)
            [Array]::Copy($bytes, 3, $payload, 0, $payload.Length)
            [void]$strictUtf8.GetString($payload)
        } catch {
            $issues.Add([pscustomobject]@{ Path = $file.FullName; Reason = ''UTF-8 BOM 后的内容不是有效 UTF-8'' })
        }
    } catch {
        $issues.Add([pscustomobject]@{ Path = $file.FullName; Reason = (''读取失败：'' + $_.Exception.Message) })
    }
}

if ($issues.Count -eq 0) {
    Write-Output ''未发现问题文件。''
} else {
    $issues | Format-Table -AutoSize -Wrap
    Write-Output (''问题文件数：{0}'' -f $issues.Count)
}
