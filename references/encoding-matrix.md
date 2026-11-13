# 编码矩阵：哪种文件存成哪种编码

一页查表。所有「实测」标注的行都是在本项目 CI 与本机 zh-CN / CP936 环境下
实际跑出来的字节，不是推断。

## 1. 先分清四个不是一回事的设置

| 名称 | 含义 | 谁在用 | 怎么查 |
| --- | --- | --- | --- |
| ACP | 系统 ANSI 代码页 | Windows PowerShell 5.1 解析无 BOM 脚本；`Encoding.Default`（.NET Framework） | `Get-WinScriptEnvironment.ps1` 的 `ACP` |
| OEMCP | 系统 OEM 代码页 | cmd.exe 解析批处理、控制台默认字符集 | 同上 `OEMCP` |
| 控制台代码页 | 当前窗口的输入/输出代码页 | `chcp` 改的就是它；`[Console]::OutputEncoding` 跟着它 | 同上 `CONSOLEOUTCP` |
| `$OutputEncoding` | PowerShell 把字符串写进**原生程序的 stdin** 时用的编码 | 只影响管道输入：`'中文' | git hash-object --stdin` | 同上 `OUTPUTENCODING` |

四个值在 zh-CN 机器上的典型组合（本机实测）：ACP=936、OEMCP=936、
控制台输出代码页可能是 65001（某个宿主改过）、`$OutputEncoding` 在 5.1
上是 `us-ascii`、在 7 上是 `utf-8`。

### 1.1 四种「编码」，别混着说

| 层 | 谁决定 | 什么时候真的会坏 |
| --- | --- | --- |
| 文件编码 | 生产文件的那支笔 | 读的一方按别的编码解，见第 2 节 |
| 控制台编码 | `chcp` / `[Console]::OutputEncoding` | 程序写 stdout 时，宿主按它去解 |
| 管道编码 | `$OutputEncoding` | **只**在把字符串喂给原生程序的 stdin 时生效 |
| 命令行参数编码 | Windows 的 `CreateProcessW` 收 UTF-16 | 只有把命令**写成字节**再交给 shell 才会坏（GBK 的 `.bat`、手工拼的字符串） |

**`$OutputEncoding` 不参与 argv。** 参数以 Unicode 传给子进程，`'中文'` 作为
参数不经过它；它管的是 `|` 右边那个原生程序的 stdin。网上「改
`$OutputEncoding` 修中文参数」的说法把这两件事混成了一件，本机实测
`-Command 'Write-Output "中文"'` 在 5.1 与 7 上都正确，且与
`$OutputEncoding` 的值无关。

**结论：看到"乱码"先问是这四条里的哪一条坏了，不要笼统说"编码问题"。**

## 2. 文件类型 → 编码

| 文件 | 存成 | BOM | 理由 |
| --- | --- | --- | --- |
| `.ps1` / `.psm1` / `.psd1`，含非 ASCII | UTF-8 | **要有** | 5.1 无 BOM 按 ACP(936) 解析；7 无 BOM 按 UTF-8。带 BOM 两边都对 |
| `.ps1` / `.psm1` / `.psd1`，纯 ASCII | UTF-8 或 ASCII | 无所谓 | 没有非 ASCII 字节时 BOM 是唯一差异 |
| `.bat` / `.cmd` | ANSI(GBK 936) | **不能有** | cmd.exe 不认 BOM，`<EF BB BF>@echo` 会变成"不是内部或外部命令" |
| `.bat` / `.cmd`，必须 UTF-8 时 | UTF-8 | **不能有**，首行 `chcp 65001 >nul` | 本机实测可用；老版本 Win10 在 65001 下 `for /f`、管道有历史缺陷，换机器要重测 |
| `.py` | UTF-8 | **不要** | PEP 263 默认 UTF-8；BOM 会让"第一行"类工具出错 |
| `.sh` / `.bash` | UTF-8 | **不要** | BOM 会跑到 shebang 前面，脚本不再是可执行文件 |
| `.json` / `.yaml` / `.ini` / `.csv` | UTF-8 | **不要** | 大量解析器直接拒绝 BOM |
| 要给别的程序读的数据文件 | UTF-8 | **不要** | 宁可显式 `latin` 也不要用系统默认 |
| 任何 `.ps1`（UTF-16LE/BE） | 别这么存 | 有 BOM 才能跑 | 见 3.1：能执行但没人能 review，改造工具链成本远大于收益 |

一句话判据：**只有当消费方是 Windows PowerShell 5.1 的脚本时才需要 BOM，
其他一律不要 BOM。**

### 2.1 Python 的源码编码声明（PEP 263）

Python 3 默认按 UTF-8 读源码，但前两行里的注释可以改这个默认：

```python
# -*- coding: gbk -*-      ← 第 1 行
# coding=cp936             ← 或这种写法
```

| 文件实际字节 | 声明 | Python 3 的行为 | 检测器判定 |
| --- | --- | --- | --- |
| GBK | `gbk` / `cp936` / `ms936` / `936` | 正常执行 | `WARN`（`DECLARED`） |
| GB2312 | `gb2312` / `euc-cn` / `euccn` | 正常执行 | `WARN`（`DECLARED`，名字报 `gb2312`） |
| 7 位 HZ | `hz` / `hzgb` / `hz-gb-2312` | 正常执行 | `WARN`（`HZ`） |
| GB18030（含四字节） | `gb18030` / `gb18030-2000` | 正常执行 | `WARN`（`DECLARED`） |
| GBK 扩展（如 `81 40`） | `gb2312` | `SyntaxError: encoding problem: gb2312` | `FAIL`（`INVALID_BYTES`） |
| 非 UTF-8 | 无 | `SyntaxError: Non-UTF-8 code ...` | `FAIL`（`CP936_PYTHON`） |
| UTF-8 + BOM | `gbk` / `latin-1` / `cp1252` | `SyntaxError: … with BOM` | `FAIL`（`BOM_CONFLICT`） |
| UTF-8 + BOM | `utf8`（不是 `utf-8` 的规范写法） | `SyntaxError: encoding problem: utf8 with BOM` | `FAIL`（`BOM_CONFLICT`） |
| UTF-8 + BOM | `utf-8` / `utf-8-sig` | 正常执行 | `OK` |
| UTF-8 | `gbk`（字节解不出） | `SyntaxError: encoding problem: gbk` | `FAIL`（`INVALID_BYTES`） |
| UTF-8 | `gbk`（字节解得出的那种） | 能跑，读出来是乱码 | `WARN`（`AMBIGUOUS`） |
| 非 ASCII | `latin-1` | 正常执行 | `WARN`（`DECLARED`，`ENCODING=unknown`） |
| 任意 | `cp1252` / `shift_jis` / `big5` … | 正常执行 | `WARN`（`UNVERIFIED`） |
| 任意 | `utf-9` / `windows-936` / `cp54936` / `54936` / `hzgb2312` / `cn-gb` | `SyntaxError: encoding problem: <名字>` | `FAIL`（`UNKNOWN`） |
| UTF-8 | `utf-8` | 正常执行 | `OK` / `WARN`（带 BOM 时） |

### 2.1.1 「唯一」「歧义」「解不出」是三种结论，不是两种

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

关键区别：**只有声明本身解不出字节时才算错**。`utf8` 被报成 `AMBIGUOUS`
而不是 `FAIL`，因为 Python 真的把它跑起来了；硬判 `FAIL` 等于用自己的谨慎
去否决解释器的行为。反过来，`E4 B8 AD` 声明 `gbk` 必须 `FAIL`——它确实解不出
（见 2.2 的 GBK 网格），这是真错，不能降级成 `WARN`。

### 2.1.2 Latin-1 要一格一格算，不能一句「都能解」

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

### 2.1.3 codec 名字的四种状态

`Resolve-PythonCodingName` 以前返回 `$null` 表示一切异常，把「Python 不认识
这个名字」和「检测器没实现这个名字」压成同一件事：`cp1252` 与 `54936` 都报
`PY_SOURCE_CODING_UNKNOWN`，而前者 Python 跑得好好的（实测 `rc=0`）。

现在返回值带 `Support` 字段，四档：

| `Support` | 含义 | 例子 | 结论 |
| --- | --- | --- | --- |
| `supported` | 名字合法，检测器自己会验 | `utf-8`、`gbk`、`gb2312`、`hz`、`gb18030`、`latin-1` | 按 2.1.1 |
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


### 2.2 GBK、GB2312、HZ 和 GB18030 不是同一个编码

这四个族经常被当成「936 的四种写法」，实测不是：

- **GB2312**（EUC-CN）是 GBK 的真子集。字形区是 `A1–F7` 首字节 × `A1–FE`
  尾字节的网格，而且网格里有空洞：`AA–AF` 整段未分配，`A2`、`A4–A9`
  若干符号行提前结束。全表 7445 个双字节格。
- **HZ-GB-2312** 是 GB2312 的七位转义写法：双字节各减 `0x80`，用 `~{` 和
  `~}` 包起来，`~~` 是字面波浪号，`~\n` 是续行。**整个文件不含任何高位
  字节**，只看「有没有非 ASCII 字节」的检测器会把它当纯 ASCII 放过去。
- **GB18030** 在 GBK 之上补了四字节序列（如 `90 30 81 30` = U+10000），
  用于 GBK 装不下的码位。合法 GBK 字节也是合法 GB18030 字节，反之不成立。
- **GBK** 是 CP936 的近亲，但**不等于** CP936，差 2149 格，见 2.2.1。

所以「用 CP936 验证 GB2312」会放过 Python 直接拒绝的文件：声明 `gb2312`
而字节里出现 `81 40`，CP936 说没问题，Python 报
`SyntaxError: encoding problem: gb2312`。HZ 更极端——CP936 根本看不见它。

反过来，把 GB2312 归进 GBK 也会误伤：GB2312 字节本来就是合法 GBK，声明
`gbk` 完全成立，不该判冲突。检测器因此按「子集方向合法、超集方向非法」处理。

判据是**声明必须和字节相符**，而不是「能不能解出来」：UTF-8 的文件声明
`coding: gbk` 也可能被 GBK 解出一串字，但那是乱码。所以检测器先确认字节
满足声明的编码规则（`Test-CodingDecodes`），再确认检测到的编码族落在声明
能覆盖的范围内（`Test-PythonCodingAgrees`）。两步都过才是 `WARN`。

项目仍然只存 UTF-8 的 `.py`。声明成 GBK 只是让检测器不再把它判成「跑不了」，
不是推荐写法。

### 2.2.1 GBK 网格：21791 格，和 CP936 差 2149 格

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
一份 GBK 字节流声明 `gb18030` 永远成立，只能靠 2.1.1 的歧义判定表达。

### 2.2.2 HZ 的状态机比 RFC 1843 严

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


### 2.3 什么时候 `WARN`、什么时候 `FAIL`

一句话：**`FAIL` 只留给「解释器会拒」或「字节破坏了声明」；解释器能跑的一律
不进 `FAIL`。**

| 理由码 | 档 | 触发条件 | 退出码 |
| --- | --- | --- | --- |
| `PY_SOURCE_CODING_DECLARED` | `WARN` | 声明成立、唯一匹配 | 1 |
| `PY_SOURCE_CODING_AMBIGUOUS` | `WARN` | 声明成立，另一族也能解 | 1 |
| `PY_SOURCE_CODING_HZ` | `WARN` | HZ 声明成立（七位字节，无高位字节） | 1 |
| `PY_SOURCE_CODING_UNVERIFIED` | `WARN` | 名字 Python 认识，检测器没有该表 | 1 |
| `PY_SOURCE_CODING_UNKNOWN` | `FAIL` | `codecs.lookup` 不认这个名字 | 2 |
| `PY_SOURCE_CODING_INVALID_BYTES` | `FAIL` | 声明的编码解不出整段字节 | 2 |
| `PY_SOURCE_CODING_BOM_CONFLICT` | `FAIL` | 名字合法但与 BOM 互斥 | 2 |
| `PY_SOURCE_CODING_UNUSABLE` | `FAIL` | `utf-16` / `utf-32` / `base64_codec` 之类不能做源码编码 | 2 |

三条不走 `FAIL` 的情形值得单独记住，它们都是**修复前误判**的地方：

1. Python 能跑（`rc=0`）却被判 `FAIL` —— 等价于宣称一个能运行的文件不能用。
2. 「别的编码也能解」被判 `FAIL` —— 见 2.1.1，那是歧义不是错误。
3. 「检测器不认识这个 codec」被判 `FAIL` —— 见 2.1.3，那是工具欠缺不是文件错误。

反过来，`utf8` + BOM 这种「Python 实报 SyntaxError」的必须 `FAIL`：它看起来
只是拼写差异，实际连解释器都不放行（实测 `encoding problem: utf8 with BOM`）。

## 3. BOM 的字节签名

| 编码 | 前几个字节 | 说明 |
| --- | --- | --- |
| UTF-8 with BOM | `EF BB BF` | 本规范对 `.ps1` 的要求 |
| UTF-8 无 BOM | 无签名 | 只能靠"严格 UTF-8 能否解码"判定 |
| UTF-16 LE | `FF FE` | 5.1 的 `Out-File` / `>` 默认产出 |
| UTF-16 BE | `FE FF` | 罕见但存在 |
| UTF-32 LE | `FF FE 00 00` | **必须比 `FF FE` 先匹配**，否则会被当成 UTF-16LE |
| UTF-32 BE | `00 00 FE FF` | 同上，四字节签名优先 |
| GBK / CP936 | 无签名 | 中文双字节，首字节 `81–FE`，尾字节 `40–FE` |

四字节签名要先于两字节判断，因为 `FF FE 00 00` 的前两字节就是 `FF FE`。
按两字节优先匹配的实现在 UTF-32LE 文件上会报出一个「UTF-16LE 文件损坏」的
结论 —— 那个文件根本不存在。本项目检测器先判四字节，UTF-32 一律 `FAIL`
且理由写 `UTF32_UNSUPPORTED`：没有任何运行时能读 UTF-32 源码脚本。

注意 CP936 在 .NET 里**没有"未定义字节"**：`0xFF` 会被映射到 `U+F8F5`，
所以"解不出 UTF-8"根本不能证明"就是 GBK"。检测工具要求 CP936 往返
（解码再编码）字节完全一致才敢标 `gbk`，并且只给 `confidence=medium`。

## 3.1 「能跑」和「推荐」是两件事

BOM 只说明生产者声明了什么，不说明文件内容是不是合法文本。这两件事必须分开
判断，否则会得到两个方向都错的结论：把坏文件判成 OK，或者把能跑的判成不能跑。

实测（Windows PowerShell 5.1.26100 与 PowerShell 7.7.0，各跑一次）：

| 文件形式 | 能否被 PowerShell 解析执行 | 推荐 | 检测器判定 |
| --- | --- | --- | --- |
| UTF-8 + BOM，内容是合法 UTF-8 | 能 | ✅ `.ps1` 的标准存法 | `OK` |
| UTF-8 + BOM，内容不合法（`EF BB BF FF`） | 半个文件跑完，有报错，退出码 0 | ❌ 文件已损坏 | `FAIL`（`INVALID_ENCODING_PAYLOAD`） |
| UTF-16LE + BOM | 能，中文正确 | ⚠️ 可用但别用 | `WARN` |
| UTF-16BE + BOM | 能，中文正确 | ⚠️ 可用但别用 | `WARN` |
| UTF-16 无 BOM | **不能**：按单字节切词，首字符就失败，退出码仍是 0 | ❌ | `FAIL` |
| UTF-16 + BOM，奇数字节 / 孤立代理项 | 跑完能读的前半段，退出码 0 | ❌ 不是文本 | `FAIL` |

两条结论：

1. **"PowerShell 不支持 UTF-16 脚本"是错的。** 带 BOM 的 LE 和 BE 都能跑。
   不推荐的理由是生态，不是解析器：`cmd.exe`、`git diff`、多数编辑器按单字节
   读，仓库里放 UTF-16 脚本等于没人能 review。
2. **退出码 0 不能证明脚本跑对了。** 上表里三行"能跑/半个跑"都是 0。判断文件
   是否可读只能看字节，这就是检测器存在的理由。

## 4. 已实测的写入行为（同一句代码，两个版本不同）

测试载荷是两个汉字（U+4E2D U+6587），文件内容两行。下表是**实际落盘字节**。

| 写法 | Windows PowerShell 5.1 | PowerShell 7.6 |
| --- | --- | --- |
| `$s \| Out-File -Path f` | `FF FE …` UTF-16LE + BOM | UTF-8 无 BOM |
| `$s > f` | `FF FE …` UTF-16LE + BOM | UTF-8 无 BOM |
| `Set-Content -Path f -Value $s` | `D6 D0 CE C4` GBK 无 BOM | UTF-8 无 BOM |
| `Set-Content … -Encoding UTF8` | `EF BB BF …` **带 BOM** | UTF-8 **无 BOM** |
| `Add-Content -Path f -Value $s` | `D6 D0 CE C4` GBK 无 BOM | UTF-8 无 BOM |
| `Out-File … -Encoding utf8` | `EF BB BF …` **带 BOM** | UTF-8 **无 BOM** |
| `[IO.File]::WriteAllText(f, $s)` | UTF-8 无 BOM | UTF-8 无 BOM |
| `[IO.File]::WriteAllText(f, $s, $utf8NoBom)` | UTF-8 无 BOM | UTF-8 无 BOM |

两条要点：

1. `-Encoding UTF8` 在 5.1 和 7 上**产出的字节不同**（一个有 BOM 一个没有）。
   跨版本脚本里不要用它来表达"我要 BOM"或"我不要 BOM"，用
   `UTF8Encoding($true/$false)` 显式构造。
2. `[IO.File]::WriteAllText` 不带编码参数在 .NET Framework 4.x 上也是
   UTF-8 无 BOM，但这是实现细节，不是契约；写代码时把 `$utf8NoBom`
   传进去，读者不用猜。

## 5. 已实测的读取行为

| 场景 | 5.1 默认 `Get-Content` | 5.1 `-Encoding UTF8` | 7 默认 |
| --- | --- | --- | --- |
| UTF-8 无 BOM 文件 | **乱码**（按 936 解码） | 正确 | 正确 |
| UTF-8 带 BOM 文件 | 正确 | 正确 | 正确 |
| GBK 文件 | 正确 | 乱码 | **全是 U+FFFD** |

7 读 GBK 文件得到的是替换字符（本机实测 4 个 `U+FFFD`），**不是报错**。
这意味着"用 7 去读一个 GBK 配置"这种组合会静默丢数据，必须在检测阶段拦掉。

## 6. 判定流程

1. 跑 `Get-WinScriptEnvironment.ps1`，确认 ACP、控制台代码页、
   `$OutputEncoding` 三个值。
2. 对目标文件跑 `Test-ScriptEncoding.ps1 -Path <文件>`，看 `ENCODING=`、
   `BOM=`、`STRICT_UTF8=`、`PAYLOAD_VALID=`、`GBK_ROUNDTRIP=` 五个字段，
   而不是只看结论。`.py` 另外看 `SOURCE_CODING=`、`SOURCE_CODING_NAME=`、
   `SOURCE_CODING_SUPPORT=`、`SOURCE_CODING_KIND=` 四项——`KIND` 是
   2.1.1 与 2.1.3 里那张表的分支名，`SUPPORT` 说明检测器对这个名字的把握程度。
3. 按第 2 节的表决定目标编码。
4. 用 `New-EncodedScript.ps1` 落盘，不要用编辑器"另存为"。不传 `-Encoding`
   时它按扩展名选：`.ps1/.psm1/.psd1` → `utf8-bom`，`.bat/.cmd` → `gbk`，
   其余 → `utf8-nobom`，并在结果里报 `ENCODING_SOURCE=extension`。
5. 再跑一次 `Test-ScriptEncoding.ps1`，要求 `VERDICT=OK`、退出码 0。
6. 真要跑一次，别只看检测结果。
