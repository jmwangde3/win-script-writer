#Requires -Version 5.1

# 让 PowerShell 控制台用 UTF-8 显示脚本输出的中文。
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

Write-Host '开始部署'

try {
    # 在这里添加实际部署命令。
    Write-Host '部署步骤已执行。'
    Write-Host '部署完成：成功'
    exit 0
}
catch {
    Write-Host ('部署完成：失败（{0}）' -f $_.Exception.Message) -ForegroundColor Red
    exit 1
}
