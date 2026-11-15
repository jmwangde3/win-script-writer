# 回答

将下面内容保存为 `H:\工作\发布\build.bat`。文件编码为 **UTF-8 无 BOM**，换行符为 **CRLF**：

```bat
@echo off
chcp 65001 >nul
echo 发布说明：%~1
"%~dp0build.exe"
set "build_rc=%errorlevel%"
echo 构建完成
exit /b %build_rc%
```

脚本先用只含 ASCII 的 `chcp 65001` 将当前控制台代码页切到 65001，因此后续中文内容和中文目录名按 UTF-8 处理；无 BOM 可避免 BOM 被当作首条命令的一部分。无论启动时是代码页 936 还是 65001，脚本都会在解析中文行之前切换到 65001。`%~dp0` 指向 bat 所在目录，所以会运行同目录的 `build.exe`。

例如从该目录运行 `build.bat 发布说明`，脚本会打印参数和「构建完成」。它在运行 exe 后立即保存 `%errorlevel%`，之后再打印提示，最后用 `exit /b` 原样返回保存的退出码（此例为 7）。