# Python

Python 3 在中文 Windows 上的默认值不是 UTF-8。更麻烦的是：**同一个脚本在
agent 宿主里跑和在用户双击时跑，默认编码可能不同。**

## 1. 两套环境，两套默认值（实测）

同一份 `python.exe`（3.13.9），只改环境变量：

| 项目 | agent 宿主内（`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`） | 裸环境（用户双击 / 计划任务） |
| --- | --- | --- |
| `sys.flags.utf8_mode` | `1` | `0` |
| `locale.getpreferredencoding(False)` | `utf-8` | **`cp936`** |
| `sys.stdout.encoding` | `utf-8` | **`gbk`** |
| `open(p,'w').write('中文')` 落盘字节 | `E4 B8 AD E6 96 87` | **`D6 D0 CE C4`** |

两套都是 `sys.getfilesystemencoding() = utf-8`（PEP 529 起 Windows 上恒定），
所以**中文路径本身是安全的**，出事的是文件内容。

这条差异是"agent 里好好的，用户一跑就乱码"的头号原因。判据：
**不要假设 `PYTHONUTF8` 存在**，见 `references/execution.md`。

## 2. 硬规则：每个 `open()` 都写 `encoding`

```python
from pathlib import Path

p = Path(r"D:\work\项目\data.txt")

# 写：显式 UTF-8，不要 BOM
p.write_text("中文内容\n", encoding="utf-8")

# 读：显式 UTF-8
text = p.read_text(encoding="utf-8")

# 读写别的编码也一样，永远显式
legacy = p.read_text(encoding="gbk")
```

`Path.read_text()` / `write_text()` 与 `open()` 的默认编码都是
`locale.getpreferredencoding(False)`，也就是上表的 cp936 或 utf-8，
取决于谁启动的进程。

需要"容忍 BOM"时用 `utf-8-sig`（能吃掉开头的 `EF BB BF`），写的时候
`utf-8` 就够。

## 3. `print()` 给管道

裸环境下 `sys.stdout.encoding` 是 `gbk`。把 `U+1F600` 这类 GBK 表达不了的
字符 `print` 出去，会直接抛 `UnicodeEncodeError`——而且是在**写出时**抛，
不是启动时，所以日志可能只写了一半。

三种处理按推荐顺序：

```python
# 1) 日志/输出只用 ASCII（最省事，跨任何宿主都不会坏）
print("OK: 3 files processed")

# 2) 需要非 ASCII：在入口处把 stdout 改成 UTF-8（3.7+）
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

# 3) 写文件而不是写终端
Path("report.txt").write_text(text, encoding="utf-8")
```

`errors="backslashreplace"` 比默认的 `strict` 好：出问题时留下可辨认的
`\uXXXX`，而不是让整个任务崩掉。

## 4. `subprocess`：别让它替你猜编码

```python
import subprocess

# 要文本时，显式给 encoding
r = subprocess.run(
    ["git", "log", "--oneline"],
    capture_output=True, text=True, encoding="utf-8", errors="replace",
)

# 更稳：拿字节，自己决定怎么解
r = subprocess.run(["git", "log", "--oneline"], capture_output=True)
text = r.stdout.decode("utf-8", "replace")
```

不要用 `shell=True` 拼中文命令：命令行按系统 ANSI 代码页解码，和
PowerShell 的 `-Command` 是同一个坑，见 `references/execution.md`。

`text=True` 而不给 `encoding` 时，用的又是 `locale` 默认值——在裸环境
就是 cp936，读 UTF-8 输出必崩。

## 5. 环境变量不是契约

`PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 都能把默认值改对，但它们：

- 只在设置了它们的进程树里生效；
- 用户双击、计划任务、CI 里通常没有；
- 会被 `-E` / `-I` / `-X utf8=0` 覆盖。

所以它们能当**加固**，不能当**前提**。代码里的 `encoding=` 才是前提。

Python 3.15 起 UTF-8 模式成为默认（PEP 686），届时这条会缓解，但
"第三方库自己用 locale 编码"的问题不会自动消失。

## 6. 与 PowerShell 交接

- PowerShell 写文件给你的（`Out-File` 产物）很可能是 UTF-16LE + BOM。
  读之前先看前两个字节：`FF FE` 就是 UTF-16LE。
- 你写给 PowerShell 的文件用 UTF-8 无 BOM；如果那是 `.ps1` 且含中文，
  它必须带 BOM，见 `references/powershell-51.md`。
- 需要双向传递时，让 Python 只负责"字节"和"UTF-8 文件"，不要参与命令行
  编码协商。
