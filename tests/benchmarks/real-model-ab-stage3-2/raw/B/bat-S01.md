建议将 `build.bat` 保存为 **UTF-8 无 BOM**，换行符使用 **CRLF**。第一条命令只有 ASCII 字符：脚本先执行 `chcp 65001`，然后才解析含中文的后续行，因此无论启动时控制台代码页是 936 还是 65001，中文路径和脚本文字都按 UTF-8 处理。这个切换仅作用于当前控制台，子进程也会继承该代码页。

将下面内容原样保存为 `H:\工作\发布\build.bat`：

```bat
@chcp 65001 >nul
@echo off
echo 参数：%~1
"%~dp0build.exe"
set "build_exit=%ERRORLEVEL%"
echo 构建完成
exit /b %build_exit%
```

例如运行：

```bat
"H:\工作\发布\build.bat" 发布说明
```

`%~dp0` 指向批处理文件所在目录，所以即使当前工作目录不同，也会运行同目录下的 `build.exe`。脚本先保存程序的退出码，再打印中文提示，最后用 `exit /b` 原样返回该码；因此本例返回 `7`。