# build.bat

将下面内容保存为 `H:\工作\发布\build.bat`：

```bat
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
```

**保存格式：** UTF-8 无 BOM，使用 CRLF（Windows）换行。脚本含中文，因此不能带 BOM；批处理在执行首条命令前按启动时的活动代码页解析文件。首行 `chcp 65001 >nul` 把代码页切为 UTF-8，使后续中文路径和提示按 65001 解析；启动时原为 936 或 65001 都可执行这条纯 ASCII 命令。目录与可执行文件路径通过 `%~dp0` 从脚本所在位置取得，并整体加引号。

`%~1` 会打印第一个参数；可这样调用：

```bat
"H:\工作\发布\build.bat" "发布说明"
```

外层引号让 Windows 将带中文的参数作为一个参数传入。运行 `build.exe` 后立即保存 `%ERRORLEVEL%`，之后的中文提示不会覆盖它，最后以 `exit /b` 原样返回其退出码（本例为 7）。
