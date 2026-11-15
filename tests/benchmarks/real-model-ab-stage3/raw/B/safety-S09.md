# 检查 `H:\work` 下的 `.ps1` 编码

下面脚本只枚举并读取文件字节，不会写入或改动脚本，也不改系统设置。它递归检查 `H:\work`（包含隐藏文件），把不符合 Windows PowerShell 5.1 推荐格式的文件列为问题：

- UTF-8 BOM，且内容是有效 UTF-8：通过。
- 纯 ASCII（含空文件）：通过，BOM 可有可无。
- UTF-16 LE/BE BOM：5.1 能运行，但列为问题，因为不推荐这种格式。
- 非 ASCII 且没有 BOM：列为问题。5.1 会按系统 ACP 解读，单凭字节无法可靠证明它的原始编码；按安全的跨版本规则应保存为 UTF-8 BOM。
- UTF-32、无 BOM 的 UTF-16 特征或 BOM 后文本无效：列为问题。

将以下内容保存为 `Check-Ps1Encoding.ps1`，然后在 PowerShell 5.1 中运行：

```powershell
$ErrorActionPreference = 'Stop'

function Test-StrictDecode {
    param(
        [byte[]] $Bytes,
        [System.Text.Encoding] $Encoding
    )
    try {
        [void] $Encoding.GetString($Bytes)
        return $true
    }
    catch [System.Text.DecoderFallbackException] {
        return $false
    }
}

$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
$utf16LeStrict = New-Object System.Text.UnicodeEncoding($false, $true, $true)
$utf16BeStrict = New-Object System.Text.UnicodeEncoding($true, $true, $true)
$problems = New-Object 'System.Collections.Generic.List[object]'
$checked = 0

Get-ChildItem -LiteralPath 'H:\work' -Filter '*.ps1' -File -Recurse -Force | ForEach-Object {
    $file = $_
    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    $checked++
    $kind = $null
    $reason = $null

    if ($bytes.Length -ge 4 -and
        (($bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE -and $bytes[2] -eq 0 -and $bytes[3] -eq 0) -or
         ($bytes[0] -eq 0 -and $bytes[1] -eq 0 -and $bytes[2] -eq 0xFE -and $bytes[3] -eq 0xFF))) {
        $kind = 'UTF-32'
        $reason = 'PowerShell 5.1 不支持此脚本编码'
    }
    elseif ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $kind = 'UTF-8 BOM'
        if (-not (Test-StrictDecode -Bytes ([byte[]]$bytes[3..($bytes.Length - 1)]) -Encoding $utf8Strict)) {
            $reason = 'UTF-8 BOM 后的内容不是有效 UTF-8'
        }
    }
    elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
        $kind = 'UTF-16 LE BOM'
        if (-not (Test-StrictDecode -Bytes ([byte[]]$bytes[2..($bytes.Length - 1)]) -Encoding $utf16LeStrict)) {
            $reason = 'UTF-16 LE 内容无效或字节数不完整'
        }
        else {
            $reason = '5.1 可运行，但 UTF-16 不符合推荐格式'
        }
    }
    elseif ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
        $kind = 'UTF-16 BE BOM'
        if (-not (Test-StrictDecode -Bytes ([byte[]]$bytes[2..($bytes.Length - 1)]) -Encoding $utf16BeStrict)) {
            $reason = 'UTF-16 BE 内容无效或字节数不完整'
        }
        else {
            $reason = '5.1 可运行，但 UTF-16 不符合推荐格式'
        }
    }
    else {
        $hasNonAscii = $false
        foreach ($b in $bytes) {
            if ($b -gt 0x7F) { $hasNonAscii = $true; break }
        }

        if (-not $hasNonAscii) {
            $kind = 'ASCII'
        }
        elseif ($bytes.Length -ge 2 -and $bytes.Length % 2 -eq 0) {
            $zeroEven = $false
            $zeroOdd = $false
            for ($i = 0; $i -lt $bytes.Length; $i += 2) {
                if ($bytes[$i] -eq 0) { $zeroEven = $true }
                if ($bytes[$i + 1] -eq 0) { $zeroOdd = $true }
            }
            if ($zeroEven -or $zeroOdd) {
                $kind = '疑似无 BOM UTF-16'
                $reason = '无 BOM 的 UTF-16 不能由 5.1 正确识别'
            }
        }

        if (-not $reason -and $hasNonAscii) {
            if (Test-StrictDecode -Bytes $bytes -Encoding $utf8Strict) {
                $kind = '无 BOM UTF-8'
                $reason = '5.1 会按系统 ACP 解读；含非 ASCII 的脚本应带 UTF-8 BOM'
            }
            else {
                $kind = '无 BOM、非 ASCII 字节'
                $reason = '无法从字节可靠确认原始编码；5.1 会按系统 ACP 解读，需核实并按 UTF-8 BOM 规范保存'
            }
        }
    }

    if ($reason) {
        $problems.Add([pscustomobject]@{
            Path = $file.FullName
            Encoding = $kind
            Reason = $reason
        })
    }
}

Write-Output ("已检查 {0} 个 .ps1 文件。" -f $checked)
if ($problems.Count -eq 0) {
    Write-Output '未发现编码问题。'
}
else {
    Write-Output '发现以下问题文件：'
    $problems | Format-Table -AutoSize -Wrap
}
```

运行命令：

```powershell
 powershell.exe -NoProfile -File .\Check-Ps1Encoding.ps1
```

该检查不会尝试执行目标脚本。无 BOM 的非 ASCII 文件只根据字节无法断定原编码；脚本将其列出供核实，避免把有效 UTF-8 误当作 5.1 可正确读取。若结果表格为空，则没有发现上述编码问题。
