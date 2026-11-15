@chcp 65001 >nul
@echo off
echo 参数：%~1
"%~dp0build.exe"
set "build_exit=%ERRORLEVEL%"
echo 构建完成
exit /b %build_exit%
