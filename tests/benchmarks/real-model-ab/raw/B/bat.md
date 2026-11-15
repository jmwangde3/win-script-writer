在简体中文 Windows（代码页 936）上，把下面内容保存为 **ANSI/GBK（代码页 936），不要带 BOM** 的 `.bat` 文件，例如 `build.bat`：

```bat
@echo off
cd /d "H:\工作\发布"
if errorlevel 1 exit /b 1
build.exe
exit /b %ERRORLEVEL%
```

`cd /d` 会同时切换盘符和目录；保存为 GBK 可让 `cmd.exe` 正确读取批处理中的中文路径。不要保存成带 BOM 的 UTF-8。