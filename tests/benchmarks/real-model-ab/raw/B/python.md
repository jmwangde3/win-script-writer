# 把 GBK 编码的 Python 源文件转成 UTF-8

要同时改**文件字节**和第一、二行内的编码声明。只把 `# coding: gbk` 改成 `# coding: utf-8`、却不转文件字节，会让 Python 按 UTF-8 解读 GBK 内容，通常报 `SyntaxError`；反过来只转字节而保留 `gbk` 声明，也可能报错或把内容读成乱码。

Python 3 默认按 UTF-8 读源码。转好后可以删掉声明；若保留，写 `# coding: utf-8`。UTF-8 BOM 通常不需要，建议写成**无 BOM 的 UTF-8**。

下面是可直接运行的转换脚本：把原文件命名为当前目录下的 `legacy.py`，保存脚本为 `convert_source.py` 后运行 `python convert_source.py`。它先严格按 GBK 解码，替换前两行中已有的 coding 声明，再写出无 BOM UTF-8 到 `converted.py`，不会覆盖原文件。

```python
from pathlib import Path
import re

source = Path("legacy.py")
target = Path("converted.py")

raw = source.read_bytes()
text = raw.decode("gbk", errors="strict")
lines = text.splitlines(keepends=True)

# PEP 263 的编码声明只能位于前两行。保留注释其余内容和换行符。
for i in range(min(2, len(lines))):
    lines[i] = re.sub(
        r"(?i)(coding\s*[:=]\s*)[-\w.]+",
        r"\1utf-8",
        lines[i],
    )

converted = "".join(lines)
target.write_bytes(converted.encode("utf-8"))

# 回读并检查 UTF-8 字节确实可解码。
check = target.read_bytes().decode("utf-8", errors="strict")
compile(check, str(target), "exec")
print(f"已转换并通过语法检查：{target.resolve()}")
```

如果原文件没有编码声明，脚本不会凭空添加；Python 3 会按 UTF-8 读取。转换后检查输出文件中的中文、字符串、注释和路径字面量是否正常，再用实际运行方式执行 `converted.py`。如果程序还会读写文本数据、调用子进程或打印中文，那些是运行时 I/O 的编码问题，需分别显式指定编码；源码转成 UTF-8 不会自动改变它们的默认值。
