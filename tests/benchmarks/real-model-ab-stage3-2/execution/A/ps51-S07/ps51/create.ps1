#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$targetPath = 'H:\temp\user\wsw-v110-stage3-2\20261115-100407\execution\A\ps51-S07\ps51\部署\deploy.ps1'
$targetDirectory = [System.IO.Path]::GetDirectoryName($targetPath)
[void][System.IO.Directory]::CreateDirectory($targetDirectory)

# 这里字符串就是最终 deploy.ps1 的完整内容。
$expectedText = @'
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
Write-Output '开始部署'
# 在这里加入实际部署命令。
Write-Output '部署完成'
'@

# 显式要求 UTF-8 BOM；不要依赖 PowerShell 5.1 的默认写文件编码。
$utf8WithBom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($targetPath, $expectedText, $utf8WithBom)

# 从磁盘读回原始字节，验证 BOM。
$actualBytes = [System.IO.File]::ReadAllBytes($targetPath)
$hasUtf8Bom = ($actualBytes.Length -ge 3 -and
    $actualBytes[0] -eq 0xEF -and
    $actualBytes[1] -eq 0xBB -and
    $actualBytes[2] -eq 0xBF)

if (-not $hasUtf8Bom) {
    throw '验证失败：文件开头不是 UTF-8 BOM（EF BB BF）。'
}

# ReadAllText 会识别并去掉文件开头的 BOM，再比较正文。
$actualText = [System.IO.File]::ReadAllText($targetPath, $utf8WithBom)
if ($actualText -cne $expectedText) {
    throw '验证失败：读回的中文内容或其他正文与写入内容不一致。'
}

Write-Output ('验证通过：UTF-8 BOM = EF BB BF；正文与写入内容一致；文件 = {0}' -f $targetPath)
