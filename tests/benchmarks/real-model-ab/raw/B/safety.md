# 检查 H:\work 下的 .ps1 编码

按 Windows PowerShell 5.1 的解析规则，带非 ASCII 内容的脚本应使用 **UTF-8 BOM**；纯 ASCII 文件不需要 BOM。UTF-16 带 BOM 在 5.1 可运行，但文档不推荐。本检查将 UTF-8 BOM 后内容损坏、无 BOM 的非 ASCII 文件、UTF-16/UTF-32 等非推荐格式列为需人工处理项；它不尝试猜测无 BOM 字节究竟是 GBK 还是其他编码。

下面代码只递归读取文件字节，不写文件、不改系统设置。将其粘贴到 Windows PowerShell 5.1 运行；它会列出问题文件及原因。无法读取的文件也会列出，避免被误认为已通过。

```powershell
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
```

注意：无 BOM 的非 ASCII 内容可能是 CP936/GBK，因而在这台 ACP=936 的机器上能被 5.1 正确解析；仅凭字节不能稳妥区分这种情况与 BOM-less UTF-8。脚本按文档要求把它列为需确认项。脚本不会判断源文件是否原本已被错误转码。
