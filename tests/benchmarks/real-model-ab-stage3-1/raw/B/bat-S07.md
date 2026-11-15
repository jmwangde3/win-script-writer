可以把中文目录写成 `\u` 转义，避免 `.bat` 源文件编码影响路径解析。将下面内容保存为 `build.bat`（ASCII/无 BOM）：

```bat
@echo off
set "WORKDIR=H:\u5de5\u4f5c\u53d1\u5e03"
for %%I in ("%WORKDIR%") do set "WORKDIR=%%~fI"
if not exist "%WORKDIR%\build.exe" (
    echo build.exe not found: "%WORKDIR%\build.exe"
    exit /b 1
)
cd /d "%WORKDIR%"
if errorlevel 1 exit /b 1
"%WORKDIR%\build.exe"
exit /b %ERRORLEVEL%
```

`cmd.exe` 会把 `\u5de5\u4f5c\u53d1\u5e03` 当作普通字符，所以这段并不能表示中文路径。实际上批处理没有通用的 `\u` 转义语法；要让 `cd` 识别中文，应把文件保存为**简体中文 ANSI/GBK（代码页 936），且不带 BOM**，并直接写中文：

```bat
@echo off
cd /d "H:\工作\发布"
if errorlevel 1 exit /b 1
"%CD%\build.exe"
exit /b %ERRORLEVEL%
```