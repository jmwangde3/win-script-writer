# 编码矩阵：哪种文件存成哪种编码

一页查表。所有「实测」标注的行都是在本项目 CI 与本机 zh-CN / CP936 环境下
实际跑出来的字节，不是推断。

## 1. 先分清四个不是一回事的设置

| 名称 | 含义 | 谁在用 | 怎么查 |
| --- | --- | --- | --- |
| ACP | 系统 ANSI 代码页 | Windows PowerShell 5.1 解析无 BOM 脚本；`Encoding.Default`（.NET Framework） | `Get-WinScriptEnvironment.ps1` 的 `ACP` |
| OEMCP | 系统 OEM 代码页 | cmd.exe 解析批处理、控制台默认字符集 | 同上 `OEMCP` |
| 控制台代码页 | 当前窗口的输入/输出代码页 | `chcp` 改的就是它；`[Console]::OutputEncoding` 跟着它 | 同上 `CONSOLEOUTCP` |
| `$OutputEncoding` | PowerShell 把字符串交给**原生程序**时用的编码 | 管道 / 参数传给 `git.exe`、`python.exe` 等 | 同上 `OUTPUTENCODING` |

四个值在 zh-CN 机器上的典型组合（本机实测）：ACP=936、OEMCP=936、
控制台输出代码页可能是 65001（某个宿主改过）、`$OutputEncoding` 在 5.1
上是 `us-ascii`、在 7 上是 `utf-8`。

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

一句话判据：**只有当消费方是 Windows PowerShell 5.1 的脚本时才需要 BOM，
其他一律不要 BOM。**

## 3. BOM 的字节签名

| 编码 | 前几个字节 | 说明 |
| --- | --- | --- |
| UTF-8 with BOM | `EF BB BF` | 本规范对 `.ps1` 的要求 |
| UTF-8 无 BOM | 无签名 | 只能靠"严格 UTF-8 能否解码"判定 |
| UTF-16 LE | `FF FE` | 5.1 的 `Out-File` / `>` 默认产出 |
| UTF-16 BE | `FE FF` | 罕见但存在 |
| GBK / CP936 | 无签名 | 中文双字节，首字节 `81–FE`，尾字节 `40–FE` |

注意 CP936 在 .NET 里**没有"未定义字节"**：`0xFF` 会被映射到 `U+F8F5`，
所以"解不出 UTF-8"根本不能证明"就是 GBK"。检测工具要求 CP936 往返
（解码再编码）字节完全一致才敢标 `gbk`，并且只给 `confidence=medium`。

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
   `BOM=`、`STRICT_UTF8=`、`GBK_ROUNDTRIP=` 四个字段，而不是看结论。
3. 按第 2 节的表决定目标编码。
4. 用 `New-EncodedScript.ps1` 落盘，不要用编辑器"另存为"。
5. 再跑一次 `Test-ScriptEncoding.ps1`，要求 `VERDICT=OK`、退出码 0。
6. 真要跑一次，别只看检测结果。
