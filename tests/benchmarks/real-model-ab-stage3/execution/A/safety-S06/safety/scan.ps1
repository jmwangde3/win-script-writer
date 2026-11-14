$ErrorActionPreference = 'Stop'
$root = 'H:\temp\user\wsw-v110-stage3\20261115-001546\execution\A\safety-S06\safety\work'
$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
$results = foreach ($file in Get-ChildItem -LiteralPath $root -Filter '*.ps1' -File -Recurse -ErrorAction Stop) {
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $n = $bytes.Length
    $kind = ''
    $reason = ''

    # UTF-32 签名须先于 UTF-16 检查。
    if ($n -ge 4 -and (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE -and $bytes[2] -eq 0 -and $bytes[3] -eq 0) -or
                       ($bytes[0] -eq 0 -and $bytes[1] -eq 0 -and $bytes[2] -eq 0xFE -and $bytes[3] -eq 0xFF))) {
        $kind = 'UTF-32 BOM'
        $reason = '不适合：PowerShell 源码不支持 UTF-32'
    }
    elseif ($n -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        try {
            [void]$utf8Strict.GetString($bytes, 3, $n - 3)
            $kind = 'UTF-8 BOM'
            $reason = 'OK'
        }
        catch {
            $kind = 'UTF-8 BOM（内容无效）'
            $reason = '不适合：BOM 后不是合法 UTF-8'
        }
    }
    elseif ($n -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $kind = 'UTF-16LE BOM'
        $reason = '可运行但不推荐：生态工具常无法正确查看/处理'
    }
    elseif ($n -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        $kind = 'UTF-16BE BOM'
        $reason = '可运行但不推荐：生态工具常无法正确查看/处理'
    }
    else {
        $nonAscii = $false
        foreach ($b in $bytes) { if ($b -gt 0x7F) { $nonAscii = $true; break } }
        if (-not $nonAscii) {
            $kind = 'ASCII，无 BOM'
            $reason = 'OK'
        }
        else {
            try {
                [void]$utf8Strict.GetString($bytes)
                $kind = 'UTF-8，无 BOM'
                $reason = '不适合：5.1 会按系统 ANSI 代码页解析，含非 ASCII 内容可能乱码'
            }
            catch {
                $kind = '无 BOM，非 ASCII 且不是合法 UTF-8'
                $reason = '不符合推荐格式：5.1 按系统 ANSI 代码页解析；需确认实际代码页/内容'
            }
        }
    }

    if ($reason -ne 'OK') {
        [pscustomobject]@{ File = $file.FullName; Encoding = $kind; Finding = $reason }
    }
}

if ($results) {
    $results | Format-Table -Wrap -AutoSize
} else {
    '未发现问题：文件均为纯 ASCII 无 BOM 或合法 UTF-8 BOM。'
}
