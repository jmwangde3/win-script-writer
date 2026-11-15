$directory = 'H:\temp\user\wsw-v110-stage3-1\20261115-010429\execution\A\ps51-S03\ps51\部署'
$path = Join-Path $directory 'deploy.ps1'

if (-not (Test-Path -LiteralPath $directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$script = @"
#Requires -Version 5.1
[Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(936)

Write-Output '开始部署'

# 在这里添加部署操作

Write-Output '部署完成'
"@

$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($path, $script, $utf8Bom)
