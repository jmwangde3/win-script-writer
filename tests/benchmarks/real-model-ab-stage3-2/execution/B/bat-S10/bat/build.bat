chcp 65001 >nul
@echo off
setlocal

echo 参数：%~1
"%~dp0build.exe"
set "build_rc=%errorlevel%"
echo 构建完成
exit /b %build_rc%
