# 编码矩阵：哪种文件存成哪种编码

一页查表。标「实测」的行都是本机 zh-CN / CP936 与 CI 上真跑出来的字节。

## 1. 先分清四个不是一回事的设置

| 名称 | 含义 | 谁在用 | 怎么查 |
| --- | --- | --- | --- |
| ACP | 系统 ANSI 代码页 | Windows PowerShell 5.1 解析无 BOM 脚本；`Encoding.Default`（.NET Framework） | `Get-WinScriptEnvironment.ps1` 的 `ACP` |
| OEMCP | 系统 OEM 代码页 | cmd.exe 解析批处理、控制台默认字符集 | 同上 `OEMCP` |
| 控制台代码页 | 当前窗口的输入/输出代码页 | `chcp` 改的就是它；`[Console]::OutputEncoding` 跟着它 | 同上 `CONSOLEOUTCP` |
| `$OutputEncoding` | PowerShell 把字符串写进**原生程序的 stdin** 时用的编码 | 只影响管道输入：`'中文' | git hash-object --stdin` | 同上 `OUTPUTENCODING` |

本机实测的典型组合：ACP=936、OEMCP=936、控制台输出代码页可能被宿主改成
65001、`$OutputEncoding` 在 5.1 是 `us-ascii`、在 7 是 `utf-8`。

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
`# -*- coding: gbk -*-` 或 `# coding=cp936`。

| 文件实际字节 | 声明 | Python 3 的行为 | 检测器判定 |
| --- | --- | --- | --- |
| GBK | `gbk` / `cp936` / `ms936` / `936` | 正常执行 | `WARN`（`DECLARED`） |
| GB2312 | `gb2312` / `euc-cn` / `euccn` | 正常执行 | `WARN`（`DECLARED`，名字报 `gb2312`） |
| 7 位 HZ | `hz` / `hzgb` / `hz-gb-2312` | 正常执行 | `WARN`（`HZ`） |
| GB18030（含四字节） | `gb18030` / `gb18030-2000` | 正常执行 | `WARN`（`DECLARED`） |
| GBK 扩展（如 `81 40`） | `gb2312` | `SyntaxError: encoding problem: gb2312` | `FAIL`（`INVALID_BYTES`） |
| 非 UTF-8 | 无 | `SyntaxError: Non-UTF-8 code ...` | `FAIL`（`CP936_PYTHON`） |
| UTF-8 + BOM | `gbk` / `latin-1` / `cp1252` | `SyntaxError: … with BOM` | `FAIL`（`BOM_CONFLICT`） |
| UTF-8 + BOM | `utf8`（非规范写法） | `SyntaxError: encoding problem: utf8 with BOM` | `FAIL`（`BOM_CONFLICT`） |
| UTF-8 + BOM | `utf-8` / `utf-8-sig` | 正常执行 | `OK` |
| UTF-8 | `gbk`（字节解不出） | `SyntaxError: encoding problem: gbk` | `FAIL`（`INVALID_BYTES`） |
| UTF-8 | `gbk`（字节解得出的那种） | 能跑，读出来是乱码 | `WARN`（`AMBIGUOUS`） |
| 非 ASCII | `latin-1` | 正常执行 | `WARN`（`DECLARED`，`ENCODING=unknown`） |
| 任意 | `cp1252` / `shift_jis` / `big5` … | 正常执行 | `WARN`（`UNVERIFIED`，`PAYLOAD=unverified`） |
| 含该编码无映射的字节 | `cp1252`（正文有 `0x81`） | `SyntaxError: encoding problem: cp1252` | `WARN`（`UNVERIFIED`，**工具看不见这个洞**） |
| 截断的多字节字符 | `shift_jis`（`93` 后无尾字节） | `SyntaxError: … can't decode byte` | `WARN`（`UNVERIFIED`，同上） |
| 任意 | `utf-9` / `windows-936` / `cp54936` / `54936` / `hzgb2312` / `cn-gb` | `SyntaxError: encoding problem: <名字>` | `FAIL`（`UNKNOWN`；带 BOM 时归 `BOM_CONFLICT`） |
| UTF-8 | `utf-8` | 正常执行 | `OK` / `WARN`（带 BOM 时） |

### 2.1.1 细节在别处

这一节只放结论表和理由码；GBK 的 21791 格、HZ 逐字节规则、歧义怎么分、codec
名字四档都在 `python.md` 第 7 节。

### 2.1.2 什么时候 `WARN`、什么时候 `FAIL`

一句话：**`FAIL` 只留给「解释器会拒」或「字节破坏了声明」；解释器能跑的一律
不进 `FAIL`。**

| 理由码 | 档 | 触发条件 | 退出码 |
| --- | --- | --- | --- |
| `PY_SOURCE_CODING_DECLARED` | `WARN` | 声明成立、唯一匹配 | 1 |
| `PY_SOURCE_CODING_AMBIGUOUS` | `WARN` | 声明成立，另一族也能解 | 1 |
| `PY_SOURCE_CODING_HZ` | `WARN` | HZ 声明成立（七位字节，无高位字节） | 1 |
| `PY_SOURCE_CODING_UNVERIFIED` | `WARN` | 名字 Python 认识，检测器没有该表（附 `SOURCE_CODING_PAYLOAD=unverified`） | 1 |
| `PY_SOURCE_CODING_UNKNOWN` | `FAIL` | `codecs.lookup` 不认这个名字 | 2 |
| `PY_SOURCE_CODING_INVALID_BYTES` | `FAIL` | 声明的编码解不出整段字节 | 2 |
| `PY_SOURCE_CODING_BOM_CONFLICT` | `FAIL` | 声明与 BOM 互斥（先于查名字判定，名字本身不合法也一样） | 2 |
| `PY_SOURCE_CODING_UNUSABLE` | `FAIL` | `utf-16` / `utf-32` 之类不能做源码编码 | 2 |

三条不走 `FAIL` 的情形值得单独记住，它们都是**修复前误判**的地方：

1. Python 能跑（`rc=0`）却被判 `FAIL` —— 等价于宣称一个能运行的文件不能用。
2. 「别的编码也能解」被判 `FAIL` —— 那是歧义不是错误，见 `python.md` 7.1。
3. 「检测器不认识这个 codec」被判 `FAIL` —— 那是工具欠缺不是文件错误（7.3）。

第 3 条的边界要说清：`WARN` 只表示**名字**通过了解释器解析，不表示文件能跑。
`cp1252` 配 `0x81`、`shift_jis` 配孤立 `93`，解释器都报 `SyntaxError`，检测器
看不见这些洞，只能输出 `SOURCE_CODING_PAYLOAD=unverified`（JSON
`SourceCodingPayload`）说「负载未验证」——已知盲区，不是 `OK`。

反过来，`utf8` + BOM 这种「Python 实报 SyntaxError」的必须 `FAIL`：它看起来
只是拼写差异，实际连解释器都不放行（实测 `encoding problem: utf8 with BOM`）。

### 2.2 GBK、GB2312、HZ 和 GB18030 不是同一个编码

这四个族经常被当成「936 的四种写法」，实测不是：

- **GB2312**（EUC-CN）是 GBK 的真子集，7445 个双字节格，网格有空洞。
- **HZ-GB-2312** 是 GB2312 的七位转义写法（`~{` … `~}`），**整个文件不含高位
  字节**，只看「有没有非 ASCII 字节」的检测器会把它当纯 ASCII。
- **GB18030** 在 GBK 之上补了四字节序列，合法 GBK 字节也是合法 GB18030。
- **GBK** 是 CP936 的近亲但**不等于** CP936，差 2149 格，见 `python.md` 7.4。

所以「用 CP936 验证 GB2312」会放过 Python 拒绝的文件，HZ 更是完全看不见；反过来
把 GB2312 归进 GBK 也误伤。检测器按「子集方向合法、超集方向非法」处理，判据是
**声明必须和字节相符**而不是「能不能解出来」：UTF-8 文件声明 `coding: gbk` 也能
解出一串乱码字。两步都过（`Test-CodingDecodes` + `Test-PythonCodingAgrees`）才是
`WARN`。

项目仍然只存 UTF-8 的 `.py`。声明成 GBK 只是让检测器不再判它「跑不了」，
不是推荐写法。

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

四字节签名必须先判，因为 `FF FE 00 00` 的前两字节就是 `FF FE`：两字节优先的实现
会把 UTF-32LE 文件报成「UTF-16LE 损坏」。检测器先判四字节，UTF-32 一律 `FAIL` +
`UTF32_UNSUPPORTED`——没有运行时能读 UTF-32 源码。

注意 CP936 在 .NET 里**没有"未定义字节"**：`0xFF` 映射到 `U+F8F5`，所以"解不出
UTF-8"根本不能证明"就是 GBK"。检测工具要求 CP936 往返（解码再编码）字节完全一致
才敢标 `gbk`，并且只给 `confidence=medium`。

## 3.1 「能跑」和「推荐」是两件事

BOM 只说明生产者声明了什么，不说明内容是不是合法文本。分开判断，否则两个方向
都错：坏文件判成 OK，或能跑的判成不能跑。

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

1. **"PowerShell 不支持 UTF-16 脚本"是错的。** 带 BOM 的 LE/BE 都能跑；不推荐
   是生态原因：`cmd.exe`、`git diff`、多数编辑器按单字节读，等于没人能 review。
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
2. `WriteAllText` 不带编码参数在 .NET Framework 4.x 上也是 UTF-8 无 BOM，但那是
   实现细节不是契约；把 `$utf8NoBom` 传进去，读者不用猜。

## 5. 已实测的读取行为

| 场景 | 5.1 默认 `Get-Content` | 5.1 `-Encoding UTF8` | 7 默认 |
| --- | --- | --- | --- |
| UTF-8 无 BOM 文件 | **乱码**（按 936 解码） | 正确 | 正确 |
| UTF-8 带 BOM 文件 | 正确 | 正确 | 正确 |
| GBK 文件 | 正确 | 乱码 | **全是 U+FFFD** |

7 读 GBK 文件得到替换字符（实测 4 个 `U+FFFD`），**不是报错**：「用 7 读 GBK
配置」会静默丢数据，必须在检测阶段拦掉。

## 6. 判定流程

1. 跑 `Get-WinScriptEnvironment.ps1`，确认 ACP、控制台代码页、
   `$OutputEncoding` 三个值。
2. 对目标文件跑 `Test-ScriptEncoding.ps1 -Path <文件>`，看 `ENCODING=`、`BOM=`、
   `STRICT_UTF8=`、`PAYLOAD_VALID=`、`GBK_ROUNDTRIP=` 五个字段而不只看结论。
   `.py` 另看 `SOURCE_CODING`、`_NAME`、`_SUPPORT`、`_KIND`，`python-only` 时
   还有 `_PAYLOAD=unverified`；`KIND` 是 2.1.2 理由码表的分支名。
3. 按第 2 节的表决定目标编码，用 `New-EncodedScript.ps1` 落盘，不要用编辑器
   "另存为"。不传 `-Encoding` 时它按扩展名选：`.ps1/.psm1/.psd1` → `utf8-bom`，
   `.bat/.cmd` → `gbk`，其余 → `utf8-nobom`，并报 `ENCODING_SOURCE=extension`。
4. 再跑一次检测，要求 `VERDICT=OK`、退出码 0；真要执行时别只看检测结果。
