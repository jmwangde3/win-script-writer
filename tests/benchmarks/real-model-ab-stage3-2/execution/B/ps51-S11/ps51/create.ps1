#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$target = 'H:\temp\user\wsw-v110-stage3-2\20261115-100407\execution\B\ps51-S11\ps51\部署\deploy.ps1'
$directory = [System.IO.Path]::GetDirectoryName($target)
[System.IO.Directory]::CreateDirectory($directory) | Out-Null

$beginText = -join @([char]0x5F00, [char]0x59CB, [char]0x90E8, [char]0x7F72)
$doneText  = -join @([char]0x90E8, [char]0x7F72, [char]0x5B8C, [char]0x6210)

# 生成文件的文本内容。两行提示在运行 deploy.ps1 时显示。
$deployContent = 'Write-Host "' + $beginText + '"' + "`r`n" +
                 'Write-Host "' + $doneText + '"' + "`r`n"

# 5.1 的 UTF8Encoding(true) 明确写入 EF BB BF。
$utf8WithBom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($target, $deployContent, $utf8WithBom)

# 读回字节，先核对 BOM，再严格解码剩余 UTF-8 字节并逐字比较。
$bytes = [System.IO.File]::ReadAllBytes($target)
if ($bytes.Length -lt 3 -or
    $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {
    throw '验证失败：文件开头不是 EF BB BF。'
}

$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
$readBack = $strictUtf8.GetString($bytes, 3, $bytes.Length - 3)
if ($readBack -cne $deployContent) {
    throw '验证失败：读回内容与写入内容不一致。'
}
if ($readBack.IndexOf($beginText, [System.StringComparison]::Ordinal) -lt 0 -or
    $readBack.IndexOf($doneText, [System.StringComparison]::Ordinal) -lt 0) {
    throw '验证失败：缺少预期的中文提示。'
}

Write-Output ('验证通过：{0}' -f $target)
Write-Output 'BOM：EF BB BF'
Write-Output '内容：与写入内容完全一致；包含“开始部署”和“部署完成”。'
