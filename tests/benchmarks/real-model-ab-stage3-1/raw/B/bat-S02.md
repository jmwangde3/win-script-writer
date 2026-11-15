建议把 `.bat` 保存为 **GBK（代码页 936），且不要 BOM**。脚本内容如下：

```bat
@echo off
chcp 936 >nul
cd /d "H:\工作\发布"
if errorlevel 1 exit /b 1
"H:\工作\发布\build.exe"
exit /b %ERRORLEVEL%
```

`cd /d` 会同时切换到 H: 盘并进入目标目录；`chcp 936` 让 `cmd.exe` 按简体中文 Windows 常用代码页解释批处理里的中文路径。保存为 GBK 无 BOM，避免 UTF-8 字节被按 936 解码而导致路径识别失败，也避免 BOM 干扰第一行命令。