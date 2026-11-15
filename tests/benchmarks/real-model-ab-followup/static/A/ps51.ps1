$path = 'H:\work\部署\deploy.ps1'
$directory = [System.IO.Path]::GetDirectoryName($path)
[System.IO.Directory]::CreateDirectory($directory) | Out-Null
$script = @'
#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

try {
    Write-Host '开始部署'

    # 在这里加入实际部署步骤。

    Write-Host '部署完成：成功'
}
catch {
    Write-Host ('部署完成：失败 - ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}

Read-Host '按 Enter 键关闭窗口' | Out-Null
'@
$utf8WithBom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($path, $script, $utf8WithBom)
