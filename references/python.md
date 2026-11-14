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

Python 3.15 起 UTF-8 模式成为默认（PEP 686）：届时 `open()`、
`locale.getpreferredencoding()` 在不设环境变量时也是 UTF-8，上表右列会
整体左移。这不改变本页的结论——`encoding=` 仍然要显式写，因为

- 第三方库可能仍按 locale 编码开文件；
- `sys.stdout` 的编码还取决于终端与宿主；
- 有人会用 `-X utf8=0` 或 `PYTHONUTF8=0` 把默认值退回去。

本项目验证这条的方式是把 UTF-8 模式**强制打开**跑一遍（`PYTHONUTF8=1`），
`tests/python` 与 `tests/integration` 都必须照常通过。CI 里对应
`test.yml` 的 `python-utf8-mode` 作业，本机则用
`set PYTHONUTF8=1` 后跑同一套。这是 3.15 行为的模拟，不是 3.15 本身。

## 6. 与 PowerShell 交接

- PowerShell 写文件给你的（`Out-File` 产物）很可能是 UTF-16LE + BOM。
  读之前先看前两个字节：`FF FE` 就是 UTF-16LE。
- 你写给 PowerShell 的文件用 UTF-8 无 BOM；如果那是 `.ps1` 且含中文，
  它必须带 BOM，见 `references/powershell-51.md`。
- 需要双向传递时，让 Python 只负责"字节"和"UTF-8 文件"，不要参与命令行
  编码协商。

## 7. 源码编码声明（PEP 263）

`# coding: <名字>` 不是注释，是解释器的输入契约。这一节记录 CPython 3.13 的
实际行为（每条都跑过），以及 `Test-ScriptEncoding.ps1` 据此给出的判定。
结论表在 `references/encoding-matrix.md`，这里是支撑它的细节。

### 7.1 「唯一」「歧义」「解不出」是三种结论，不是两种

最早这里只有一条「声明和字节相符吗」，于是把 `# coding: gb2312` + 一个 `茅`
字（字节 `C3 A9`）判成了冲突。那两字节在 GB2312 里是「茅」，在 UTF-8 里是
「é」，两边都能解——Python 按声明解出「茅」并正常运行（实测 `rc=0`）。
「别的编码也能解」不是错误，只是不唯一。

现在的判定分三档：

| 情况 | 判据 | 结论 |
| --- | --- | --- |
| 唯一匹配 | 声明能解，检测到的编码族覆盖它 | `WARN` + `DECLARED` |
| 歧义 | 声明能解，另一族也能解，且那族是检测结论 | `WARN` + `AMBIGUOUS` |
| 声明解不出 | 整段过不了声明的编码规则 | `FAIL` + `INVALID_BYTES` |

关键区别：**只有声明本身解不出字节时才算错**。声明 `gb2312` 而字节恰好也是
合法 UTF-8 的文件被报成 `AMBIGUOUS` 而不是 `FAIL`，因为 Python 真的把它跑起来
了；硬判 `FAIL` 等于用自己的谨慎去否决解释器的行为。反过来，`E4 B8 AD` 声明
`gbk` 必须 `FAIL`——它确实解不出（见 7.4 的 GBK 网格），这是真错，不能降级
成 `WARN`。

### 7.2 Latin-1 要一格一格算，不能一句「都能解」

ISO-8859-1 把 0x00–0xFF 全部 256 个值映射到字符，所以「字节能不能被 latin-1
解出」恒为真——这曾让检测器对 `latin-1` 直接 `return $true`，而同一张
repertoire 表却写着 `latin-1 = @('ascii')`，两处互相矛盾：任何非 ASCII 的
latin-1 文件都被判成「和 ASCII 冲突」。

两处现已统一到同一件事上：latin-1 能描述任意字节，但它描述的是单字节
字符集，**不能**用来说明「这些字节也是 GBK / UTF-8」。所以 latin-1 的
repertoire 只算它自己：

- 纯 ASCII 文件声明 `latin-1`：语法上成立且无歧义，检测器给 `OK`。
- 含非 ASCII 的文件声明 `latin-1`：只要字节能被 latin-1 解（恒真）就是
  `WARN` + `DECLARED`，**不再**判 `CONFLICT`。
- 检测结论恰好是 UTF-8：`WARN` + `AMBIGUOUS`（两族都能解，不武断）。
- 带 BOM：`FAIL` + `BOM_CONFLICT`（Python 实报
  `encoding problem: iso-8859-1 with BOM`）。

latin-1 与 UTF-8 的任何混用都不在本节保护范围内：`WARN` 说的是「Python 能跑」，
不是「这样写没问题」。项目自己的 `.py` 仍然只存 UTF-8。

### 7.3 codec 名字的四种状态

`Resolve-PythonCodingName` 以前返回 `$null` 表示一切异常，把「Python 不认识
这个名字」和「检测器没实现这个名字」压成同一件事：`cp1252` 与 `54936` 都报
`PY_SOURCE_CODING_UNKNOWN`，而前者 Python 跑得好好的（实测 `rc=0`）。

现在返回值带 `Support` 字段，四档：

| `Support` | 含义 | 例子 | 结论 |
| --- | --- | --- | --- |
| `supported` | 名字合法，检测器自己会验 | `utf-8`、`gbk`、`gb2312`、`hz`、`gb18030`、`latin-1` | 按 7.1 |
| `python-only` | 名字合法，检测器没有该编码的表 | `cp1252`、`shift_jis`、`big5`、`euc-jp`、`koi8-r`、`unicode_escape` | `WARN` + `UNVERIFIED` |
| `unknown` | Python 的 `codecs.lookup` 不认 | `windows-936`、`cp54936`、`54936`、`hzgb2312`、`cn-gb`、`gb18030-2022` | `FAIL` + `UNKNOWN` |
| `bom-conflict` | 名字合法但和 BOM 冲突 | `gbk` + BOM、`utf8` + BOM | `FAIL` + `BOM_CONFLICT` |

`UNVERIFIED` 是诚实的欠缺，不是缺陷：检测器没有 `shift_jis` 的双字节表，就不能
声称验过它。给 `WARN` 加一句「CPython 认识这个名字，本工具无法验证字节」比
猜一个 `OK` 可靠。**`python-only` 的代价是检测器不引 Python 运行时**——那会让
一个纯 PowerShell 工具变成需要装解释器才能跑，而且解释器版本会改变判定结果。

名字表是数据，数据会漂。这张表按「族」写而不是按 300 个拼写写，但仍然有
三类容易写错的边界，全部是实测出来的：

- **`utf-8-*` 前缀一律当 UTF-8。** `codecs.lookup('utf-8-unix')` 抛
  `LookupError`，可文件照样能跑——tokenizer 先归一化再查表。所以
  `utf-8-unix`、`utf-8-bogus` 都得给 `WARN`，判 `FAIL` 是错的。
- **`latin-2` 到 `latin-16` 的连字符形式全都不认。** `latin2` 能跑、
  `latin-2` 与 `latin_2` 都报 `encoding problem`；`latin-1` 是唯一例外
  （它被归一化成 `iso-8859-1`）。这种反直觉的分界只能靠实测，不能靠推理。
- **裸代码页数字是合法别名。** `# coding: 1252` 能跑，`# coding: 936` 是 GBK；
  唯一不成立的是 `54936`。

集成测试 `TestCodingNameAgreement` 因此不写死任何名字的预期结论：它把每个名字
写进真实源文件，先问解释器，再问检测器，只比较两边答案是否一致。名字表漏一个
拼写、或者 stdlib 改了别名，这条测试会红，而不是让某个能跑的文件被判失败。


### 7.4 GBK 网格：21791 格，和 CP936 差 2149 格

CPython 的 `gbk` 是 126 个首字节 × 190 个尾字节（`40–7E`、`80–FE`，跳过
`7F`）＝ 23940 个候选格，其中 **21791 格**解得开且往返一致。剩下的 2149 格
是空洞，分布有规律：

| 首字节 | 尾字节 `40–A0`（低区） | 尾字节 `A1–FE`（高区） |
| --- | --- | --- |
| `81–A0` | 全有 | 全有 |
| `A1–A7` | 全无 | 有，但符号区各自的尾巴缺失 |
| `A8` | `40–95` 有，`96–A0` 无 | 缺 `BC`、`BF`、`C1–C4`、`EA–FF` |
| `A9` | 缺 `58`、`5B`、`5D–5F`、`89–95`、`97–A0` | 只有 `A4–EF` |
| `AA–AF` | 全有 | 全无 |
| `B0–D6`、`D8–F7` | 全有 | 全有 |
| `D7` | 全有 | 有至 `F9` |
| `F8–FD` | 无 | 无 |
| `FE` | 有至 `4F` | 全无 |

还有两个单字节洞：**`0x80` 与 `0xFF` Python 都报错**。

这张表必须自己带着。CP936 把上面 2149 个空洞**全部**映射到私用区并往返成功
（本机实测 21791+2149 格中 0 个被拒），还把 `0x80` 解成 €、`0xFF` 解成
U+F8F5。于是 UTF-8 的 `E4 B8 AD`（中）在 CP936 眼里是「`E4B8` 一个字 +
`AD` 一个合法首字节」——这正是当年把 UTF-8 文件判成「合法 GBK」的根因。
现在的检测器用 `Test-GbkCell` 逐格判定，集成测试把 21791 个可解格拼成一个
文件要求检测器放行、再对每个有洞的首字节各取一格要求拒绝，两边答案必须一致。

同理 GB18030 覆盖全 2 字节区（0 洞，`A1 40` 解成 U+E4C6 并可往返），所以
一份 GBK 字节流声明 `gb18030` 永远成立，只能靠 7.1 的歧义判定表达。

### 7.5 HZ 的状态机比 RFC 1843 严

CPython 3.13 的 `hz` 编解码器对转义的处理和 RFC 的宽容读法不一致，实测逐条：

| 字节 | 位置 | CPython | 说明 |
| --- | --- | --- | --- |
| `~{` | ASCII 模式 | 进入 GB 模式 | |
| `~}` | GB 模式 | 退出，回 ASCII | 必须成对 |
| `~}` | ASCII 模式 | **`SyntaxError`** | RFC 允许的「冗余 `~}`」Python 不认 |
| `~~` | ASCII 模式 | 一个字面 `~` | |
| `~~` | GB 模式 | **`SyntaxError`** | 转义只在 ASCII 模式成立 |
| `~\n` | ASCII 模式 | 续行，两行拼一起 | 只认 LF；`~\r\n` 报错 |
| `~\n` | GB 模式 | **`SyntaxError`** | 同上 |
| `0x21–0x7E` | GB 模式 | 双字节的第一/第二字节 | 空格、TAB、LF、`0x7F` 都非法 |
| `0x7E` | GB 模式第二字节 | 合法 | `56 7E` = `D6 FE` = 「筑」 |
| 文件结束 | 停在 GB 模式，最后一对完整 | **接受** | 实测 `rc=0`，内容是 `中文` |
| 文件结束 | 停在 GB 模式，单个字节悬挂 | `SyntaxError` | `can't decode byte` |

最后两行是两件不同的事，检测器分开表达：返回 `$true` + `Detail='unterminated'`，
`WARN` 理由里追加「ends inside GB mode」。判成 `FAIL` 会让一个 Python 能跑的
文件被拒——这是实测出来的，不是推测：夹具 `py-coding-hz-open.py` 去掉尾随换行
后 `rc=0`，加上换行后 `rc=1`（`can't decode byte 0x0a`）。

HZ 的 GB 模式双字节用的是 GB2312 表（`Test-Gb2312Cell`），不是 GBK 表：
HZ 定义在 GB2312 上，`81 40` 这种 GBK 扩展格在 HZ 里同样非法。
