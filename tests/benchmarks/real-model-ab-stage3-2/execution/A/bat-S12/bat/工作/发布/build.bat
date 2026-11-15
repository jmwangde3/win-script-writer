@echo off
chcp 65001 >nul
setlocal
"%~dp0build.exe"
set "BUILD_RC=%ERRORLEVEL%"
echo %~1
echo 构建完成
exit /b %BUILD_RC%
