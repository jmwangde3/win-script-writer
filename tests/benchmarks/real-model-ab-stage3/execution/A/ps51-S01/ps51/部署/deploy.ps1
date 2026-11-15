#Requires -Version 5.1

# 中文版 Windows 控制台通常使用代码页 936；让 PowerShell 按相同编码输出。
[Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(936)

Write-Host '开始部署'

# 在此处添加部署操作

Write-Host '部署完成'
