@echo off
chcp 65001 >nul
set "BUILD_EXE=%~dp0build.exe"
if not exist "%BUILD_EXE%" (
    echo 找不到 build.exe
    exit /b 2
)
echo 参数：%~1
"%BUILD_EXE%"
set "BUILD_EXIT=%ERRORLEVEL%"
echo 构建完成
exit /b %BUILD_EXIT%
