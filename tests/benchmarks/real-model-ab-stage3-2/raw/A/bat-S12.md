# build.bat

将下面内容保存为 `H:\工作\发布\build.bat`：**UTF-8 无 BOM**，换行符使用 **CRLF**。第一行必须保持为所示的 ASCII 命令，不能在它前面加空行或 BOM。

```bat
@echo off
chcp 65001 >nul
setlocal
"%~dp0build.exe"
set "BUILD_RC=%ERRORLEVEL%"
echo %~1
echo 构建完成
exit /b %BUILD_RC%
```

例如在该目录运行 `build.bat "发布说明"`。脚本先用纯 ASCII 的 `chcp 65001` 将活动控制台代码页切到 UTF-8；这行在进入脚本时的 936 或 65001 下都能解析。随后 cmd 按 UTF-8 解析脚本里的中文，并以 `%~dp0`（脚本所在目录）定位可执行文件，所以中文目录 `H:\工作\发布` 不依赖当前工作目录。它会把第一个参数打印出来，再打印「构建完成」。

运行 `build.exe` 后立即保存 `%ERRORLEVEL%`，最后以 `exit /b` 返回该值，因此示例中的退出码仍为 7。脚本会把当前控制台代码页留在 65001；这是为后续中文命令和输出设置的。