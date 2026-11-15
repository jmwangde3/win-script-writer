# Windows PowerShell 5.1
$ErrorActionPreference = 'Stop'
$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
$strictLe = New-Object System.Text.UnicodeEncoding($false, $true, $true)
$strictBe = New-Object System.Text.UnicodeEncoding($true, $true, $true)
$problems = New-Object 'System.Collections.Generic.List[object]'

Get-ChildItem -LiteralPath 'H:\work' -Filter '*.ps1' -File -Recurse -ErrorAction Stop | ForEach-Object {
    $path = $_.FullName
    try {
        $b = [System.IO.File]::ReadAllBytes($path)
        $kind = $null
        $reason = $null

        # 先识别较长签名，避免把 UTF-32 误认成 UTF-16。
        if ($b.Length -ge 4 -and (($b[0] -eq 0xFF -and $b[1] -eq 0xFE -and $b[2] -eq 0 -and $b[3] -eq 0) -or ($b[0] -eq 0 -and $b[1] -eq 0 -and $b[2] -eq 0xFE -and $b[3] -eq 0xFF))) {
            $kind = '问题'
            $reason = 'UTF-32 BOM：不适合作为 PowerShell 源码'
        }
        elseif ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) {
            try { [void]$strictUtf8.GetString($b, 3, $b.Length - 3) }
            catch { $kind = '问题'; $reason = 'UTF-8 BOM 后的内容不是合法 UTF-8' }
        }
        elseif ($b.Length -ge 2 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE) {
            try { [void]$strictLe.GetString($b, 2, $b.Length - 2); $kind = '可运行但不推荐'; $reason = 'UTF-16LE 带 BOM' }
            catch { $kind = '问题'; $reason = 'UTF-16LE 内容损坏或长度异常' }
        }
        elseif ($b.Length -ge 2 -and $b[0] -eq 0xFE -and $b[1] -eq 0xFF) {
            try { [void]$strictBe.GetString($b, 2, $b.Length - 2); $kind = '可运行但不推荐'; $reason = 'UTF-16BE 带 BOM' }
            catch { $kind = '问题'; $reason = 'UTF-16BE 内容损坏或长度异常' }
        }
        else {
            $hasNonAscii = $false
            foreach ($byte in $b) { if ($byte -gt 0x7F) { $hasNonAscii = $true; break } }
            if (-not $hasNonAscii) {
                # 纯 ASCII：无 BOM 时各相关解析器的字符解释一致。
            }
            else {
                try {
                    [void]$strictUtf8.GetString($b)
                    $kind = '问题'
                    $reason = '含非 ASCII 的 UTF-8 无 BOM；5.1 會按系統 ANSI 代碼頁解析'
                }
                catch {
                    $kind = '需确认'
                    $reason = '无 BOM 且不是严格 UTF-8；可能是 ACP/936，也可能是其他编码'
                }
            }
        }

        if ($kind) {
            $problems.Add([pscustomobject]@{ 类型 = $kind; 文件 = $path; 原因 = $reason })
        }
    }
    catch {
        $problems.Add([pscustomobject]@{ 类型 = '无法检查'; 文件 = $path; 原因 = $_.Exception.Message })
    }
}

if ($problems.Count -eq 0) {
    '未发现问题文件。'
}
else {
    $problems | Sort-Object 类型, 文件 | Format-Table -AutoSize -Wrap
}
