# Git Bash / MSYS2

全链路最干净的选项。UTF-8 是它的默认值，中文路径也正常工作——但边界在
"从 Bash 调 Windows 程序"那一步。

## 1. 环境基线（本机实测）

```
LANG=en_US.UTF-8
LC_ALL=C.UTF-8
MSYSTEM=UCRT64
```

`printf '中文\n' > 中文测试.txt` 落盘是 `E4 B8 AD E6 96 87 0A`，`cat` 读回
正确。**在 Bash 内部不需要做任何编码处理。**

建议每个脚本显式声明，不要依赖调用者：

```bash
#!/usr/bin/env bash
set -euo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8
```

用 `C.UTF-8` 而不是 `en_US.UTF-8`：前者在 Git Bash 里一定存在，后者依赖
locale 是否被生成。

## 2. 两种路径写法

| 写法 | 谁认识 |
| --- | --- |
| `/h/AI工作区/project` | MSYS 程序（bash、coreutils、git、grep…） |
| `H:/AI工作区/project` 或 `H:\AI工作区\project` | Windows 原生程序（`python.exe`、`powershell.exe`…） |

**MSYS 会在把参数交给原生程序时自动转换**：传 `/h/temp/x.txt` 给
`python.exe`，它收到的是 `H:/temp/x.txt`。实测：

```
python.exe -c "print(sys.argv[1])" /h/temp/中文测试.txt
  -> H:/temp/中文测试.txt          （自动转换，正确）
MSYS_NO_PATHCONV=1 python.exe ...
  -> /h/temp/中文测试.txt          （关掉转换，原生程序不认）
```

判据：

- 传给 Windows 原生程序 → 两边都行，但你**不要**自己再拼一次。
- 传给 MSYS 程序 → 必须是 `/h/...`，传 `H:/...` 反而不认。
- 参数看起来像路径但其实不是路径（例如 `-X`、`//server/share`）时，用
  `MSYS_NO_PATHCONV=1` 局部关掉，别全局关。

## 3. 中文文件名在 git 里变成 `\344\270\255`

`core.quotepath` 默认开启，`git status` / `git diff` 会把非 ASCII 文件名
转义成八进制：

```
git diff --cached --name-only
  -> "\344\270\255\346\226\207\346\226\207\344\273\266.txt"

git -c core.quotepath=false diff --cached --name-only
  -> 中文文件.txt
```

两种处理：

```bash
# 一次性看真名
git -c core.quotepath=false status

# 或本项目里关掉（会影响所有仓库的显示，谨慎）
git config --global core.quotepath false
```

注意这只是**显示**问题，提交进去的路径一直是 UTF-8 字节，不改仓库内容。

## 4. 从 Bash 调 PowerShell

```bash
# 推荐：把脚本落盘，用 -File 跑
powershell.exe -NoProfile -NonInteractive -File "H:/work/step1.ps1"

# 含中文参数时：不要拼 -Command
powershell.exe -NoProfile -Command "Write-Output '中文'"   # 可能已经坏了
```

`-Command` 的内容会经过命令行解码，中文和嵌套引号都在路上损坏。含中文时
用 `-File` 加 UTF-8 with BOM 的 `.ps1`，或者走
`scripts/run_ps.py`（见 `references/execution.md`）。

反向（PowerShell 调 bash）同理：路径要转成 `/h/...`，字符串参数用文件传。

## 5. 读 Windows 程序产出的文件

Windows 程序可能写出：

- UTF-16LE + BOM（PowerShell 5.1 的 `Out-File`）—— Bash 侧 `cat` 会显示
  每个字符中间夹一个空字节，`file` 会报 `Little-endian UTF-16 Unicode text`
- GBK（cmd 的 `echo 中文 > f`）—— Bash 侧看起来是一串 `\xD6\xD0...`
- UTF-8 无 BOM —— 正常

处理顺序：先 `od -An -tx1 file | head -1` 看头几个字节，再决定用
`iconv -f UTF-16LE -t UTF-8` / `iconv -f GBK -t UTF-8` / 直接用。

不要用 `cat` 当判据：终端显示乱码既可能是内容错，也可能是终端解码错。

## 6. 与 PowerShell 的分工

| 任务 | 选谁 |
| --- | --- |
| 文本处理、批量改名、grep/sed/awk | Bash |
| 注册表、服务、COM、WMI、计划任务 | PowerShell |
| 需要 `.NET` 类型操作字节 | PowerShell |
| 需要双击运行 | 都不合适，见 `references/cmd-bat.md` |

不要为了"统一语言"把 Windows 系统操作硬塞进 Bash（会绕一大圈还更容易坏），
也不要为了"原生"把文本处理写成 PowerShell 管道（编码坑更多）。
