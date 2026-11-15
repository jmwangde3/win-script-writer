#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# 用 Unicode 码点构造路径及中文，避免脚本自身编码影响字面量。
$dirName = -join ([char[]](0x90E8, 0x7F72))
$targetDir = Join-Path 'H:\temp\user\wsw-v110-stage3-2\20261115-100407\execution\A\ps51-S02\ps51' $dirName
$targetPath = Join-Path $targetDir 'deploy.ps1'

$startText = -join ([char[]](0x5F00, 0x59CB, 0x90E8, 0x7F72))
$doneText  = -join ([char[]](0x90E8, 0x7F72, 0x5B8C, 0x6210))

# 生成文件内容。用单引号包住提示，使目标脚本运行时原样输出中文。
$lines = @(
    '#Requires -Version 5.1'
    "Write-Output '$startText'"
    "Write-Output '$doneText'"
)
$content = [string]::Join("`r`n", $lines) + "`r`n"

if (-not [System.IO.Directory]::Exists($targetDir)) {
    [void][System.IO.Directory]::CreateDirectory($targetDir)
}

# UTF8Encoding(true) 写入 EF BB BF 前缀。
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($targetPath, $content, $utf8Bom)

# 读回原始字节验证 BOM，再读回文本验证与待写内容完全一致。
$bytes = [System.IO.File]::ReadAllBytes($targetPath)
if ($bytes.Length -lt 3 -or
    $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {
    throw '验证失败：文件开头不是 EF BB BF。'
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$readBack = [System.IO.File]::ReadAllText($targetPath, $utf8NoBom)
if ($readBack -cne $content) {
    throw '验证失败：读回文本与写入文本不一致。'
}
if (-not $readBack.Contains($startText) -or -not $readBack.Contains($doneText)) {
    throw '验证失败：中文提示缺失。'
}

Write-Output '验证通过：BOM=EF BB BF；读回文本与写入内容一致；中文提示齐全。'
Write-Output ('文件：' + $targetPath)
