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

两套都是 `sys.getfilesystemencoding() = utf-8`（PEP 529 起 Windows 恒定），
所以**中文路径是安全的**，出事的是文件内容。这是「agent 里好好的、用户一跑
就乱码」的头号原因：**不要假设 `PYTHONUTF8` 存在**，见 `references/execution.md`。

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

裸环境下 `sys.stdout.encoding` 是 `gbk`。把 `U+1F600` 这类 GBK 表达不了的字符
`print` 出去会抛 `UnicodeEncodeError`——而且是在**写出时**抛，所以日志可能只写了
一半。

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

`errors="backslashreplace"` 比默认的 `strict` 好：出问题时留下可辨认的 `\uXXXX`，
而不是让整个任务崩掉。

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

Python 3.15 起 UTF-8 模式成为默认（PEP 686）：`open()`、
`locale.getpreferredencoding()` 在不设环境变量时也是 UTF-8，上表右列会整体左移。
这不改变结论——`encoding=` 仍要显式写：第三方库可能仍按 locale 开文件，
`sys.stdout` 的编码还取决于终端与宿主，也有人用 `-X utf8=0` 或 `PYTHONUTF8=0`
把默认值退回去。

本项目验证这条的方式是把 UTF-8 模式**强制打开**（`PYTHONUTF8=1`，Python 3.13）跑同
一套测试：CI 是 `python-utf8-mode` 作业，本机是设变量后重跑。这是模拟 3.15 的默认
行为，不是 3.15 兼容测试——3.14 / 3.15 都不在正式验证矩阵里（见 `README.md`）。

## 6. 与 PowerShell 交接

- PowerShell 写给你的文件（`Out-File` 产物）很可能是 UTF-16LE + BOM，读之前
  先看前两个字节：`FF FE`。
- 你写给 PowerShell 的文件用 UTF-8 无 BOM；若是含中文的 `.ps1` 必须带 BOM，
  见 `references/powershell-51.md`。
- 双向传递时让 Python 只管"字节"和"UTF-8 文件"，不要参与命令行编码协商。

## 7. 源码编码声明（PEP 263）

`# coding: <名字>` 不是注释，是解释器的输入契约。这一节记录 CPython 3.11–3.15 预览
的实际行为（每条都跑过），以及 `Test-ScriptEncoding.ps1` 据此给出的判定；结论表在
`references/encoding-matrix.md`，这里是支撑它的细节。

### 7.1 「唯一」「歧义」「解不出」是三种结论，不是两种

最早这里只有一条「声明和字节相符吗」，于是把 `# coding: gb2312` + `茅`（`C3 A9`）
判成冲突：那两字节在 GB2312 是「茅」、在 UTF-8 是「é」，Python 按声明解出「茅」并
`rc=0`；「别的编码也能解」只是不唯一。

现在的判定分三档：

| 情况 | 判据 | 结论 |
| --- | --- | --- |
| 唯一匹配 | 声明能解，检测到的编码族覆盖它 | `WARN` + `DECLARED` |
| 歧义 | 声明能解，另一族也能解，且那族是检测结论 | `WARN` + `AMBIGUOUS` |
| 声明解不出 | 整段过不了声明的编码规则 | `FAIL` + `INVALID_BYTES` |

关键区别：**只有声明本身解不出字节时才算错**——`gb2312` 配合法 UTF-8 字节报
`AMBIGUOUS`（Python 真跑起来了，硬判等于用谨慎否决解释器），而 `E4 B8 AD` 声明
`gbk` 必须 `FAIL`（确实解不出，见 7.4）。

### 7.2 Latin-1 要一格一格算，不能一句「都能解」

ISO-8859-1 把 0x00–0xFF 全映射到字符，所以「能不能被 latin-1 解出」恒为真——这曾
让检测器对 `latin-1` 直接 `return $true`，而 repertoire 表却写
`latin-1 = @('ascii')`，非 ASCII 的 latin-1 文件都被判成冲突。

两处现已统一：latin-1 能描述任意字节，但它是单字节字符集，**不能**说明「这些字节
也是 GBK / UTF-8」，所以 repertoire 只算它自己：

- 纯 ASCII 声明 `latin-1`：成立且无歧义，`OK`。
- 含非 ASCII 声明 `latin-1`：能解（恒真）就 `WARN` + `DECLARED`，**不再**判
  `CONFLICT`。
- 检测结论恰好是 UTF-8：`WARN` + `AMBIGUOUS`（两族都能解，不武断）。
- 带 BOM：`FAIL` + `BOM_CONFLICT`（Python 实报
  `encoding problem: iso-8859-1 with BOM`）。

latin-1 与 UTF-8 的混用不在本节保护范围内：`WARN` 说的是「Python 能跑」，不是
「这样写没问题」。项目自己的 `.py` 仍然只存 UTF-8。

### 7.3 codec 名字的四种状态

`Resolve-PythonCodingName` 以前用 `$null` 表示一切异常，把「Python 不认识」和
「检测器没实现」压成同一件事（`cp1252` 与 `54936` 都报 `UNKNOWN`，前者 `rc=0`）。
现在返回 `Support` 字段，四档：

| `Support` | 含义 | 例子 | 结论 |
| --- | --- | --- | --- |
| `supported` | 名字合法，检测器自己会验 | `utf-8`、`gbk`、`gb2312`、`hz`、`gb18030`、`latin-1` | 按 7.1 |
| `python-only` | 名字合法，检测器没有该编码的表 | `cp1252`、`shift_jis`、`big5`、`euc-jp`、`koi8-r` | `WARN` + `UNVERIFIED` |
| `unusable` | 名字解析得了，但它是转换器不是文本 codec | `base64`、`rot13`、`hex`、`zlib`、`uu`、`bz2`、`quopri`；`utf-16` / `utf-32` 族另走同名理由码 | `FAIL` + `UNUSABLE` |
| `unknown` | `codecs.lookup` 不认 | `windows-936`、`cp54936`、`54936`、`hzgb2312`、`cn-gb` | `FAIL` + `UNKNOWN` |
| `bom-conflict` | 声明与 BOM 互斥 | `gbk` + BOM、`utf8` + BOM、`windows-936` + BOM | `FAIL` + `BOM_CONFLICT` |

BOM 判定**先于**名字查表：`windows-936` 报 `unknown encoding: windows-936`，带 BOM
报 `encoding problem: windows-936 with BOM`；都拒但理由码不同，检测器按解释器顺序
走（`py-coding-unknown-bom.py` 钉住）。

**「名字能解析」不等于「文件能跑」。** `python-only` 因此额外输出
`SOURCE_CODING_PAYLOAD=unverified`（JSON `"SourceCodingPayload": "unverified"`），
其它档位不输出该键——不是空串，否则判真假会被读成「已验证」。`cp1252` 正文含
`0x81`、`shift_jis` 的孤立 `93`，解释器都报 `SyntaxError`，检测器看不见这两个洞，
一律 `WARN`，不会是 `OK`。

名字表是数据。v1.0.3 用前缀正则（`^mac[-_.]?[a-z0-9]*$`、`^ibm[0-9]{3,5}$` 等）
归类，`mac-bogus`、`shift_jis_typo`、`big5-nope`、`ibm99999` 都被当成 Python 认识的
名字——解释器对这四个都抛 `SyntaxError`。v1.0.4 改**精确表**：先按 tokenizer 规则
归一化（小写、`_`→`-`、`utf-8-*` 折叠成 `utf-8`、`latin-1` 族折叠成 `latin-1`，
其余原样）再查表，105 个族、411 条拼写。表是采样到的各版本**并集**：
`cp858` 的 4 条前导零别名（`cp00858` / `csibm00858` / `ibm00858` /
`pc_multilingual_850_euro`）出自 CPython gh-149801，自 3.13.14 / 3.14.6 /
3.15.0b2 起才有，抄单机会拒掉新补丁写的文件——CI 报的。
`TestCodecAliasCoverage` 遍历 `encodings.aliases` 与模块名逐个
`compile()` 再问检测器：3.13.9 上 471 个拼写 / 380 可作 / 91 被拒 / **0 分歧**。
`ansi` 归 `mbcs`（本机 CP936），`ansi_x3.4-1968` 归 `ascii`：同一段 GBK 字节，解释器
跑前者、拒后者。

三类边界实测：`utf-8-*` 前缀一律当 UTF-8（`codecs.lookup('utf-8-unix')` 抛
`LookupError`，文件照样跑）；`latin-2` 到 `latin-16` 的连字符形式全都不认（`latin2`
能跑，`latin-2` / `latin_2` 报 `unknown encoding`，`latin-1` 是唯一例外）；裸代码页
数字是合法别名（`1252`、`936` 成立，`54936` 不成立）。

并集的双向风险写进输出：命中 `python-only` 只说明「本项目验证过的某个 CPython 认识
这个名字」，不说明当前解释器认识它——`cp00858` 在 3.14.8 / 3.15.0rc3 编译通过，
3.11.17 / 3.13.9 上是 `unknown encoding`。文案因此不再说「CPython recognizes this
codec」，`SOURCE_CODING_PAYLOAD=unverified` 保留，`WARN` 不上移。

转换器是另一档：`base64` / `rot13` 等 7 族 18 条拼写 `codecs.lookup()` 能解析，
解释器却在**名字**上拒绝（`SyntaxError: 'base64' is not a text encoding`），进
`PythonCodecUnusable` 给 `FAIL` + `PY_SOURCE_CODING_UNUSABLE`，与 `UNKNOWN` 分开
——前者没有拼写要改。`idna` / `punycode` 没进表：前者是文本 codec（ASCII 源码能
编译），后者败在字节。


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
（0 个被拒），还把 `0x80` 解成 €、`0xFF` 解成 U+F8F5。于是 UTF-8 的 `E4 B8 AD`
（中）在 CP936 眼里是「`E4B8` 一个字 + `AD` 一个合法首字节」——这正是当年把
UTF-8 文件判成「合法 GBK」的根因。现在 `Test-GbkCell` 逐格判定，集成测试把
21791 个可解格拼成一个文件要求放行、对每个有洞的首字节各取一格要求拒绝。

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
| `~\n` | GB 模式 | **`SyntaxError`** | 与 RFC 1843 相反，见下 |
| `~\r\n` | GB 模式 | **`SyntaxError`** | 与 LF 同结论，实测而非推断 |
| `0x21–0x7E` | GB 模式 | 双字节的第一/第二字节 | 空格、TAB、LF、`0x7F` 都非法 |
| `0x7E` | GB 模式第二字节 | 合法 | `56 7E` = `D6 FE` = 「筑」 |
| 文件结束 | 停在 GB 模式，最后一对完整 | **接受** | 实测 `rc=0`，内容是 `中文` |
| 文件结束 | 停在 GB 模式，单个字节悬挂 | `SyntaxError` | `can't decode byte` |

RFC 1843 允许行续接在两种模式下出现，CPython 只允许 ASCII 模式：GB 模式下 `~`
是双字节格的起始，第二字节必须落在 `0x21–0x7E`，而 `0x0A`、`0x0D` 都不在范围
内，所以 `"~{VP~\nXX~}"` 与 `"~{VP~\r\nXX~}"` 都报错（实测 `rc=1`）。v1.0.4 补了
`py-coding-hz-gb-newline.py` / `-gb-crlf.py` 两份夹具钉住两种行尾——只处理 LF 的
检测器会放过 CRLF 那份。

最后两行是两件不同的事，检测器分开表达：返回 `$true` + `Detail='unterminated'`，
`WARN` 理由追加「ends inside GB mode」。判成 `FAIL` 会拒掉一个 Python 能跑的文件：
夹具 `py-coding-hz-open.py` 去掉尾随换行 `rc=0`，加上换行 `rc=1`。

HZ 的 GB 模式双字节用 GB2312 表（`Test-Gb2312Cell`）而不是 GBK 表：HZ 定义在
GB2312 上，`81 40` 这种 GBK 扩展格在 HZ 里同样非法。
