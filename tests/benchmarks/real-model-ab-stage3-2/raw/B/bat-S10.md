# `build.bat`

将下面内容保存为 `H:\工作\发布\build.bat`。文件编码用 **UTF-8（无 BOM）**，换行符用 **CRLF**。第一行必须是切换代码页的命令；不要在它前面加 `@echo off` 或 BOM。切换后，批处理里的中文内容由代码页 65001 按 UTF-8 读取。

```bat
chcp 65001 >nul
@echo off
setlocal

echo 参数：%~1
"%~dp0build.exe"
set "build_rc=%errorlevel%"
echo 构建完成
exit /b %build_rc%
```

例如从控制台运行：

```bat
"H:\工作\发布\build.bat" "发布说明"
```

`%~dp0` 是批处理所在目录，因此可定位同目录下的 `build.exe`，不依赖当前工作目录。脚本启动时先执行 `chcp 65001`，所以无论启动前控制台是 936 还是 65001，文件后续的中文命令、参数回显和中文提示都使用 65001。这个切换会影响当前控制台及其子进程，脚本结束时不恢复原代码页。

紧接 `build.exe` 调用就保存 `%errorlevel%`，之后的 `echo` 不会覆盖要返回的值；最后的 `exit /b` 将其原样交还给调用方。因此题设中 `build.exe` 返回 7 时，`build.bat` 也返回 7。
