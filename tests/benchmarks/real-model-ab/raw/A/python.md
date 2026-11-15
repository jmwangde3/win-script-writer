# 把 GBK 的 `.py` 转成 UTF-8

关键是同时转换**文件字节**和源码编码声明。只把第一行改成 `# coding: utf-8`，而文件仍是 GBK，Python 就会按 UTF-8 解码，中文通常会报 `SyntaxError`。

建议保存为 UTF-8（通常选无 BOM），并把声明改为：

```python
# coding: utf-8
```

可以用下面的小工具转换。将代码保存为 `gbk_to_utf8.py`，然后在源文件所在目录运行 `python gbk_to_utf8.py old.py new.py`。它会按 GBK 解码、改写第一或第二行的编码声明、再以 UTF-8 写出新文件；原文件不动。脚本会拒绝找不到声明的文件，避免悄悄产出未按预期处理的结果。

```python
from pathlib import Path
import re
import sys

if len(sys.argv) != 3:
    raise SystemExit("用法: python gbk_to_utf8.py old.py new.py")

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_bytes().decode("gbk")
lines = text.splitlines(keepends=True)

# PEP 263 的编码声明只会在前两行；保留行尾和其余源码。
pattern = re.compile(r"(?i)(coding\s*[=:]\s*)[-\w.]+")
for i in range(min(2, len(lines))):
    updated, count = pattern.subn(r"\g<1>utf-8", lines[i], count=1)
    if count:
        lines[i] = updated
        break
else:
    raise SystemExit("前两行没有编码声明；未写出目标文件")

dst.write_bytes("".join(lines).encode("utf-8"))
print(f"已转换: {src} -> {dst}")
```

转换后检查几件事：

- 用 UTF-8 重新打开目标文件，确认中文注释、字符串和文档字符串都正常；不要只看第一行。
- 运行 `python -m py_compile new.py` 检查语法，再运行脚本确认行为没变。若源码里有用 `open()` 读写文本文件的代码，给每处明确写 `encoding="utf-8"`（旧 GBK 数据文件则按实际编码读，例如 `encoding="gbk"`）。源码转成 UTF-8 不会自动改变这些数据文件的编码。
- 源码编码和终端输出编码是两回事。中文 `print()` 在某些中文 Windows 环境仍可能受 GBK 控制台或管道影响；必要时明确设置 stdout/stderr 编码，或将报告以 UTF-8 写入文件。
- 若项目有其他工具、打包器或旧版 Python 使用编码声明，也一并确认它们能识别 UTF-8。转换前后建议保留版本控制差异，重点核对中文文本。

`# coding: utf-8` 是 Python 读取源文件时的约定；`open()` 的默认文本编码以及 `print()` 的输出编码各自另有默认值，不能因为源码改成 UTF-8 就假设它们也变成 UTF-8。
