# .bat 示例

在简体中文 Windows 上，将下面内容保存为 **ANSI/GBK（代码页 936），无 BOM**，例如 `build.bat`：

```bat
@echo off
chcp 936 >nul
cd /d "H:\工作\发布"
if errorlevel 1 exit /b %ERRORLEVEL%
"H:\工作\发布\build.exe"
exit /b %ERRORLEVEL%
```

`cd /d` 会同时切换盘符和目录；路径加引号可避免空格等字符拆开。批处理文件自身必须按 GBK(936) 保存且不能带 BOM，cmd 才能正确解析其中的中文路径。不要保存成 UTF-8（含或不含 BOM）。
