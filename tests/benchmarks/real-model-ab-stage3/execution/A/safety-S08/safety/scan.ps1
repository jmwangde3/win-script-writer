#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$root = 'H:\temp\user\wsw-v110-stage3\20261115-001546\execution\A\safety-S08\safety\work'
$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
$problemFiles = New-Object 'System.Collections.Generic.List[object]'
$scanned = 0

if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw "目录不存在：$root"
}

Get-ChildItem -LiteralPath $root -Filter '*.ps1' -File -Recurse -ErrorAction Stop |
    ForEach-Object {
        $file = $_
        $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
        $scanned++
        $reason = $null

        # 先识别较长的签名，避免把 UTF-32LE 误认成 UTF-16LE。
        if ($bytes.Length -ge 4 -and
            (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE -and $bytes[2] -eq 0x00 -and $bytes[3] -eq 0x00) -or
             ($bytes[0] -eq 0x00 -and $bytes[1] -eq 0x00 -and $bytes[2] -eq 0xFE -and $bytes[3] -eq 0xFF))) {
            $reason = 'UTF-32 编码；不适合作为 PowerShell 5.1 脚本编码'
        }
        elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
            $reason = 'UTF-16LE BOM；5.1 可读，但不推荐，建议改为 UTF-8 BOM'
        }
        elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
            $reason = 'UTF-16BE BOM；5.1 可读，但不推荐，建议改为 UTF-8 BOM'
        }
        elseif ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
            try {
                $null = $utf8Strict.GetString($bytes, 3, $bytes.Length - 3)
            }
            catch [System.Text.DecoderFallbackException] {
                $reason = '带 UTF-8 BOM，但正文不是合法 UTF-8'
            }
        }
        else {
            $hasNonAscii = $false
            foreach ($b in $bytes) {
                if ($b -gt 0x7F) { $hasNonAscii = $true; break }
            }

            if ($hasNonAscii) {
                $reason = '含非 ASCII 字节但没有 UTF-8 BOM；5.1 会按系统 ANSI 代码页解读，存在乱码风险'
            }
        }

        if ($reason) {
            $problemFiles.Add([pscustomobject]@{
                Path   = $file.FullName
                Reason = $reason
            })
        }
    }

Write-Output ("扫描文件数：{0}" -f $scanned)
if ($problemFiles.Count -eq 0) {
    Write-Output '未发现编码问题。'
}
else {
    Write-Output ("发现问题文件：{0}" -f $problemFiles.Count)
    foreach ($item in $problemFiles) {
        Write-Output ("{0}`n  问题：{1}" -f $item.Path, $item.Reason)
    }
}
