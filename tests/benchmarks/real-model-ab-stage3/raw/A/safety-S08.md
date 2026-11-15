# 检查 `H:\work` 下 `.ps1` 的编码

下面的脚本兼容 Windows PowerShell 5.1。它递归查找 `H:\work` 下的 `.ps1`，只读取文件字节，不改系统设置或文件；结果只输出到控制台。符合文档建议的格式是：含非 ASCII 内容的脚本使用 UTF-8 BOM，纯 ASCII 脚本可无 BOM。UTF-16 带 BOM 虽可被 5.1 读取，但不推荐，因此也会列为问题。

将代码以 **UTF-8 BOM** 保存为 `Check-Ps1Encoding.ps1`（代码中含中文），然后在 Windows PowerShell 5.1 中运行：

```powershell
#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$root = 'H:\work'
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
```

脚本不对“无 BOM 且全 ASCII”的文件报错，因为 ASCII 字节在 UTF-8 和系统 ANSI 代码页下相同。无 BOM 且有非 ASCII 字节的文件会列出：这类文件可能是当前机器代码页下的 GBK，也可能是 5.1 会误读的 UTF-8，单凭字节无法安全地断定其原始意图。
