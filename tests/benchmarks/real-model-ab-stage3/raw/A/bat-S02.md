```bat
@echo off
chcp 936 >nul
cd /d "H:\工作\发布" || exit /b 1
build.exe
exit /b %ERRORLEVEL%
```

把文件保存为 **GBK（代码页 936），且不要带 BOM**。批处理文件含有中文路径，`cmd.exe` 会按活动代码页解码文件；在中文 Windows 上显式设为 936，并用 GBK 保存，路径才能正确识别。路径加双引号可避免目录名含空格时被拆开；`cd /d` 也会在需要时切换盘符。若切换目录失败，脚本返回错误；否则返回 `build.exe` 的退出码。