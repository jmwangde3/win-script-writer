在 `answer.bat` 中写入：

```bat
@echo off
chcp 936 >nul
cd /d "H:\工作\发布" || exit /b 1
build.exe
exit /b %ERRORLEVEL%
```

将这个 `.bat` 文件保存为 **ANSI/GBK（代码页 936），且不要 BOM**。`cmd.exe` 会按当前代码页读取批处理文件；在简体中文 Windows 上，GBK 文件中的中文路径才能正确识别。`cd /d` 同时切换到目标目录和驱动器，之后运行该目录里的 `build.exe`；如果切换目录失败，脚本会以错误码 1 退出。