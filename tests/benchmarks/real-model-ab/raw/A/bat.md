# 用 `.bat` 调用中文目录里的 `build.exe`

把下面内容保存为 `build.bat`，文件编码选 **ANSI（简体中文 Windows 上即 GBK/代码页 936），不要加 BOM**：

```bat
@echo off
chcp 936 >nul
cd /d "H:\工作\发布"
if errorlevel 1 exit /b 1
build.exe
exit /b %ERRORLEVEL%
```

关键是 `.bat` 里的中文路径要按当前代码页 936 保存；UTF-8（无论是否带 BOM）都可能让 `cmd.exe` 读错路径。`cd /d` 会同时切换驱动器和目录，双引号保护路径；之后从该目录运行 `build.exe`。最后一行把程序的退出码传给调用方。
