@echo off
chcp 65001 >nul
rem 中文参数示例：把第一个参数打印出来
echo 参数：%~1
"%~dp0build.exe"
set "BUILD_RC=%ERRORLEVEL%"
echo 构建完成
exit /b %BUILD_RC%
