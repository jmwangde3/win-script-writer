# 用 `.bat` 调用中文路径下的程序

把下面内容保存为 `build.bat`，文件编码选 **ANSI（简体中文 GBK/代码页 936），不要 BOM**。批处理里的中文路径会由 `cmd.exe` 按当前代码页解读；在常见的简体中文 Windows 上，936 能正确表示这个路径。

```bat
@echo off
chcp 936 >nul
cd /d "H:\工作\发布" || exit /b 1
build.exe
exit /b %errorlevel%
```

`cd /d` 会同时切换盘符和目录。`build.exe` 因而从 `H:\工作\发布` 运行；最后一行把程序的退出码传回调用方。