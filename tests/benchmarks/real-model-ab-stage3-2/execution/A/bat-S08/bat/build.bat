@echo off
chcp 65001 >nul
echo 发布说明：%~1
"%~dp0build.exe"
set "build_rc=%errorlevel%"
echo 构建完成
exit /b %build_rc%
