# 变更记录

格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号按 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.4] - 2026-11-14

编码判定准确性的第二轮修复。v1.0.3 把 codec 名字分成三档是对的，但分档靠的是
前缀正则，于是「像别名但不是别名」的一类名字被算进 `python-only`；同时
`python-only` 的文案暗示「名字通过 = 文件能跑」，而检测器对这类文件的字节一无所知。
这一版把名字表换成精确表，并让未验证这件事显式出现在输出里。

### Changed（会改变既有行为，需注意）

- **codec 名字表从宽泛前缀正则换成精确表。** 原实现用
  `^mac[-_.]?[a-z0-9]*$`、`^(shift|s)[-_.]?jis[a-z0-9_]*$`、
  `^(big5|csbig5|hkscs)[-_.a-z0-9]*$`、`^ibm[0-9]{3,5}$` 这类模式归类，
  于是 `mac-bogus`、`shift_jis_typo`、`big5-nope`、`ibm99999` 全被判成
  「Python 认识、本工具没验」，而解释器对这四个都抛 `SyntaxError`。
  现在先把名字按 tokenizer 的规则归一化（小写、`_`→`-`、`utf-8-*` 折叠成
  `utf-8`、`latin-1` 族折叠成 `latin-1`、其余保留原样只在 utf-8/latin-1
  两族上截断 `.`），再查按族组织的精确表（105 个族、411 条拼写，逐条跑过解释器，
  或由 CI 在更新补丁上跑过——表是矩阵内各版本的并集；其中 7 族 18 条是转换器
  codec，见下一条）；
  `utf-16` / `utf-32` 族单独一档
  表示「解析得了但不能作源码」。
  **影响**：上述四个仿写名与 `mac` / `macos` / `macx` / `iso_646_us` /
  `jisx0208` / `x_mac_cyrillic` / `pt_154` / `cshproman8` / `utf-8.unix`
  从 `WARN` 变成 `FAIL` + `PY_SOURCE_CODING_UNKNOWN`。
  反方向没变松：`cp1252` / `shift_jis` / `big5` / `mac-roman` / `latin2` /
  `euc-jp` / `ansi` / `ansi-x3.4-1968` 仍是 `python-only`；`utf-16` 族仍
  `FAIL` + `UNUSABLE`。
- **`python-only` 不再声称文件能跑，新增 `SOURCE_CODING_PAYLOAD=unverified`。**
  文案从「CPython resolves that name and the file runs」改为「resolves that
  name and accepts this spelling, but this detector has no byte level
  verifier for it, so the payload was not checked; the file may still fail
  to decode」。文本输出多一行 `SOURCE_CODING_PAYLOAD=unverified`，JSON 多一个
  `"SourceCodingPayload": "unverified"`，**只在 `python-only` 时出现**，
  其它档位键不存在（不是空字符串——消费方判真假时会读错）。
  **影响**：`WARN` 的含义被收紧成「名字成立」，不再被读成「可以运行」。
  一份 `# coding: cp1252` 且正文含 `0x81` 的文件在解释器里是
  `SyntaxError: 'charmap' codec can't decode byte 0x81 ... character maps to
  <undefined>`，检测器仍是 `WARN` + `unverified`。
  这是写进输出的盲区，不是 `OK`。
- **`python-only` 的提示语改成「兼容集合」口径。** 表是采样到的各版本并集，
  所以命中只意味着「本项目验证过的某个 CPython 认识它」，不意味着**当前**解释器
  认识它：`cp00858` / `csibm00858` / `ibm00858` / `pc_multilingual_850_euro`
  是 `cp858` 的四条前导零别名，来自 CPython gh-149801，自 3.13.14、3.14.6、
  3.15.0b2 起才随补丁发布（3.13.9 与 3.11.17 都没有）；实测 3.11.17 与 3.13.9 报
  `unknown encoding: cp00858`，3.14.8 与 3.15.0rc3 编译通过。
  原文案
  「CPython recognizes this codec」对集合成立、对用户机器上的解释器不成立。
  现在改为「该名字在本项目对 CPython 验证过的兼容集合里，但运行这个文件的解释器
  可能不支持它，且检测器没有验证字节」，`SOURCE_CODING_PAYLOAD=unverified` 保留，
  `WARN` 不升级为 `OK`，判定宽度一点没变。
- **转换器 codec 单开一档 `unusable`，与「名字不认识」分开。** `base64` /
  `rot13` / `hex` / `zlib` / `uu` / `bz2` / `quopri` 这 7 族 18 条拼写
  `codecs.lookup()` 都能解析，但都不是文本 codec，解释器拒绝声明时的原话是
  `SyntaxError: 'base64' is not a text encoding; use codecs.decode() to handle
  arbitrary codecs`。v1.0.3 把它们和 `mac-bogus` 一起归进 `unknown-name`，
  等于让人去改一个并没有拼错的拼写。
  **影响**：这几条从 `PY_SOURCE_CODING_UNKNOWN` 变成 `PY_SOURCE_CODING_UNUSABLE`，
  `SOURCE_CODING_SUPPORT` 新增取值 `unusable`，`VERDICT` 仍是 `FAIL`、
  退出码仍是 2——只改诊断，没放宽。`idna` / `punycode` 这类真·文本 codec
  没有进这张表（前者 ASCII 源码真能编译，后者是解字节失败而不是名字失败）。

### Added

- 夹具 8 个：`py-coding-hz-gb-newline.py` / `-gb-crlf.py`（GB 模式行续接，
  LF 与 CRLF 各一）、`py-coding-shift-jis-bytes.py` / `-truncated.py`、
  `py-coding-big5-bytes.py` / `-truncated.py`、`py-coding-cp1252-bytes.py` /
  `-undefined.py`（完整字符与残缺字节各一）。夹具总数 69 → 77，原有 69 个
  的字节 SHA256 全部未变。
- Pester 新增 3 个 Context、46 例：`codec name table`、`python-only payload
  state`、`HZ state machine boundaries`；收尾又在 `codec name table` 里补 15 例
  ——兼容集合文案 4 例（`cp00858` / `csibm00858` / `shift_jis` / `cp1252`）、
  转换器分类 9 例、未知名与转换器分叉 1 例、`idna` 边界 1 例。Pester 累计 200 例，
  5.1 与 7 各 200/200。
- 集成测试 `TestCodecAliasCoverage`：遍历 `encodings.aliases` 与
  `encodings/` 下的模块名，把每个拼写写成真实源文件，先 `compile()` 再问
  检测器，只比较两边结论是否一致，不写死任何名字的答案。3.13.9 上 471 个
  拼写、380 个可作源码、91 个被拒、0 处分歧；这 471 个是 327 个别名键、
  98 个规范名（都不是键）、121 个模块名（其中 22 个是新的）与 24 个仿写
  拼写去重而来。同一类新增 `TestPythonOnlyPayload`：三对「完整字符 /
  残缺字节」夹具，要求检测器对六者给出同一答案 `WARN + unverified`，同时
  实测解释器对前一半 `rc=0`、后一半 `rc=1`；另加一条 `ansi` 回归——
  `ansi` 是 `mbcs`（本机即 CP936），`ansi_x3.4-1968` / `ansi-x3.4-1968`
  是 `ascii`，同一个 GBK 负载下解释器跑前者、拒后两者，检测器必须跟着分叉。
- 集成新增 `TestUnusableCodecReason` 与 `TestCodecCompatibilitySet`。前者把 18 条
  转换器拼写逐个 `compile()`，确认解释器都在**名字**上拒绝（`is not a text
  encoding`），再要求检测器逐条给 `unusable-codec`；后者把 `cp00858` 的两种宿主
  都写成断言——认识它的宿主与不认识它的宿主都只能是 `WARN` + `unverified`，
  不按解释器版本跳过任何一边。

### Fixed

- **HZ 的 GB 模式行续接按实测钉住。** RFC 1843 允许 `~\n` 在两种模式下都
  续行，CPython 只允许在 ASCII 模式：GB 模式下 `~` 是一个双字节格的起始，
  第二字节必须落在 `0x21–0x7E`，`0x0A` 与 `0x0D` 都不在范围内，于是
  `"~{VP~\nXX~}"` 与 `"~{VP~\r\nXX~}"` 都报 `UnicodeDecodeError`。检测器的
  状态机本来就按这个结论走，缺的是证据——新增两份夹具把 LF 与 CRLF 都钉住，
  只处理 LF 的实现会在 CRLF 那份上放行。
- **诊断里引用的解释器原话改成实测的。** `utf-16` / `utf-32` 那条理由原先写
  「CPython raises SyntaxError: encoding problem: utf-16」，3.11.17 / 3.13.9 /
  3.14.8 / 3.15.0rc3 四个版本实测都不是这句，而是
  `'utf-16-le' codec can't decode byte 0x0a in position 22: truncated data`。
  现在理由只说「不是 ASCII 兼容的源码编码，整份文件都要按它解」，不引一句不存在
  的报错。同时把文档里同类的陈旧引用改掉：未知名字是
  `unknown encoding: <名字>`（不是 `encoding problem:`），字节解不出是
  `'gb2312' codec can't decode byte 0x81 …`。带 BOM 的
  `encoding problem: <名字> with BOM` 是真的，保留。
- 文档：`references/python.md` §7.3 改写为「精确表 + 归一化规则 + 全量回归」，
  新增 payload 三行表与仿写名的负向清单；§7.5 补 GB 模式 `~\r\n` 行与
  RFC 差异的成因。`references/encoding-matrix.md` 补两行「声明里的洞」与
  一段「`WARN` 只表示名字通过」的边界说明。`README.md` 的设计取舍补一条
  「`WARN` 不代表文件能跑」，已验证范围补别名回归的数字。`SKILL.md` 的
  检测器条目补一句 payload 含义（入口文件仍保持只放路由与硬规则）。
- **版本口径全仓库统一。** `cp858` 的别名来源此前三处不一致：脚本注释与 Pester
  写「3.13.17 新增」、集成测试写「3.14 引入」、参考页写「3.13.17 补的」。按上游
  事实统一：gh-149801 引入，3.13 线自 3.13.14、3.14 线自 3.14.6、3.15 线自
  3.15.0b2 起随补丁发布；`ccsid00858` 是 3.15 独有的后续别名。
  `README.md` 的「已验证范围」拆成正式 CI 矩阵 / 额外实测 / 未纳入三档，
  `references/python.md` §7 与 `references/encoding-matrix.md` 同步这套口径，
  明确写出 3.14 / 3.15 不在正式矩阵内。判定逻辑与表未动。

### 已知未覆盖（留给 v1.0.5）

**支持的边界先写在前面**：正式验证矩阵是 Python 3.11 与 3.13（配 Windows
PowerShell 5.1 与 PowerShell 7，共四个作业），外加 UTF-8 模式预览作业与
docs contract；本机另有 3.11.17 / 3.13.9 / 3.13.16 / 3.14.8 / 3.15.0rc3 的
一次性实测。**3.14 与 3.15 不在正式矩阵内**，UTF-8 模式作业模拟的是 3.15 的
默认行为，不是 3.15 兼容测试。

表是 3.11 / 3.13 的并集，再往后的补丁与预览版又扩了别名，检测器还没跟上。
用 `TestCodecAliasCoverage` 在五个解释器上各跑一遍（`compile()` 与检测器双向
对照），分歧数：3.11.17 **0** / 3.13.9 **0** / 3.13.16 **0**（479 个名单）/
3.14.8 **6** / 3.15.0rc3 **58**。
3.14.8 的 6 个是新增的 `cp874` 族（`874` / `ms874` / `windows_874`）与
`cseuckr` / `iso_8859_8_e` / `iso_8859_8_i`；3.15.0rc3 多出的 52 个是整批
`cs*` 拼写（`cswindows1252`、`cswindows31j`…）、`latin_2`…`latin_10`、
`mac`、`utf8-sig`、`windows-936`、`cshproman8`、`ccsid00858` 之类，在 3.15
上都已可解析。
这些名字在 3.11 / 3.13 上确实报 `unknown encoding`，所以现在判 `FAIL` 不是
错判；要改的是表，不是判定逻辑——3.15 正式版发布时按同一套流程重采一次。
在那之前，3.14 / 3.15 上会把个别解释器能编译的文件判 `FAIL`，方向是多说一句，
不是放行。

## [1.0.3] - 2026-11-14

编码别名的准确性修复。检测器把 GBK、GB2312、HZ-GB-2312 和 GB18030 当成
同一个 CP936，于是三种情况都答错了：Python 拒绝的文件被判通过，Python 能跑的
文件被判失败，还有一个根本没被检查。这一版按各自的字节规则分别验证。

### Changed（会改变既有行为，需注意）

- **GBK 网格由检测器自带，不再用 CP936 代验。** 两者差 2149 格：CPython 的
  `gbk` 是 23940 个候选格中的 21791 格，CP936 把剩下的空洞全部映射到私用区
  并往返成功，还把 `0x80` 解成 €、`0xFF` 解成 U+F8F5。`Test-GbkCell` 按实测
  枚举的网格逐格判定（含 `A8` 低区只到 `95`、`A9` 低区缺 `58/5B/5D-5F/89-95/97-A0`
  这些散格），`Test-GbkPayload` 只走这张表。
  **影响**：UTF-8 字节声明 `gbk` 的判定从 `PY_SOURCE_CODING_CONFLICT` 变为
  `PY_SOURCE_CODING_INVALID_BYTES`——那是真解不出（Python 报
  `encoding problem: gbk`）；CP936 合法而 GBK 未分配的格不再被放行。
- **「别的编码也能解」改判歧义，不再判冲突。** `# coding: gb2312` + 一个「茅」
  字（`C3 A9`，UTF-8 里是 é）此前被判 `FAIL`，但 Python 按声明解出「茅」并
  `rc=0`。现在分「唯一匹配 / 歧义 / 声明解不出」三档，歧义走
  `PY_SOURCE_CODING_AMBIGUOUS`（`WARN`）。
  **影响**：`gb2312` / `gbk` / `gb18030` 声明 + 恰好也是合法 UTF-8 的字节，
  从 `FAIL` 变成 `WARN`。真解不出的仍然 `FAIL`，没有降级。
- **Latin-1 的两处判定统一。** `Test-CodingDecodes` 直接 `return $true`，
  repertoire 表却只列 `ascii`，于是任何非 ASCII 的 latin-1 文件都撞成
  `CONFLICT`。现在两处都说「latin-1 描述全部 256 个单字节值」：
  **影响**：非 ASCII 的 latin-1 声明从 `FAIL` 变成 `WARN`（`DECLARED`，检测
  结论是 UTF-8 时给 `AMBIGUOUS`）；纯 ASCII 仍 `OK`；带 BOM 仍 `FAIL`。
- **codec 名字分四档，新增 `SOURCE_CODING_SUPPORT=`。** 原先 `$null` 同时表示
  「Python 不认识」和「检测器不支持」，于是 `cp1252`、`shift_jis`、`big5`
  （Python 实测 `rc=0`）被判 `FAIL UNKNOWN`。现在返回 `supported` /
  `python-only` / `unknown` 三档，外加独立的 BOM 冲突分支。名字表按族重写，
  327 个别名键加 121 个 `encodings/` 模块名、共 448 个拼写逐个跑解释器核对，
  0 例不一致：
  **影响**：`cp1252` / `shift_jis` / `big5` / `euc-jp` / `mac-roman` /
  `csisolatin2` / `latin2` / `1252` / `ansi` 等从 `FAIL` 变成 `WARN`
  （`PY_SOURCE_CODING_UNVERIFIED`，明确说「检测器没有该表」）；
  `utf-8-sig` 从 `FAIL UNKNOWN` 变成 `OK`；`utf-8-unix`、`utf-8-bogus`
  这类只有 tokenizer 归一化才认的写法也从 `FAIL` 变成 `WARN`；`utf-8`/
  `utf-8-sig` 之外的编码名与 BOM 同现时理由码改为
  `PY_SOURCE_CODING_BOM_CONFLICT`（原 `PY_SOURCE_CODING_CONFLICT`），并且
  `utf8` 这种拼写 + BOM 也归入此类（Python 实报 `encoding problem: utf8 with
  BOM`）。反方向没放松：`latin-2`（连字符形式全族如此）、`cp424`、`gb-2312`、
  `base64` 这类实际跑不了的名字仍判 `FAIL`。检测器不引 Python 运行时。
- **HZ 状态机按 CPython 的实际行为重写。** CPython 的 `hz` 比 RFC 1843 严：
  `~~` 和 `~\n` 只在 ASCII 段合法（GB 段内报 `UnicodeDecodeError`），`~}` 在
  ASCII 段非法，GB 段内 `0x7E` 可作为第二字节（`56 7E` = 「筑」），而文件结束
  停在 GB 段但最后一对完整时**接受**。
  **影响**：`py-coding-hz-open.py` 这类「未闭合但可运行」的文件从
  `FAIL INVALID_BYTES` 变成 `WARN` + 理由里注明 «ends inside GB mode»；
  段内非法转义与悬挂半字符的仍 `FAIL`。
- **`gb2312` / `euc-cn` 不再归并为 GBK。** 它们是 GB2312 的别名，而 GB2312 是
  GBK 的真子集：Windows 没有 GB2312 代码页，原先用 CP936 代验，CP936 分配得
  比 GB2312 宽得多（`81 40`、`AA A1`、`F8 A1` 都是 CP936 合法格、GB2312 空位）。
  现在用一张按 CPython 3.13 逐格枚举的分配表（7445 格）校验。
  **影响**：声明 `gb2312` 而字节里含 GBK 扩展字符的文件，判定从 `WARN` 变成
  `FAIL`（`PY_SOURCE_CODING_INVALID_BYTES`）——Python 对这类文件报
  `SyntaxError: encoding problem: gb2312`，旧判定是假阳性。
  `SourceCodingName` 也从 `gbk` 改为 `gb2312`。
- **`hz` 单独成族，不再当 GBK。** HZ-GB-2312 是 GB2312 的七位转义写法，整个
  文件不含任何高位字节，原先只被判成 `ascii` 然后 `OK`——等于没检查。
  现在跑一个七位状态机：`~{` / `~}` / `~~` / `~\n` 的配对、GB 段内每个字节对
  是否落在 GB2312 分配表内、文件结束时是否还在 GB 段内。
  **影响**：合法的 HZ 源文件从 `OK` 变成 `WARN`（`PY_SOURCE_CODING_HZ`，
  Python 跑得动，但编辑器和 git 看到的是转义文本）；未闭合或含非法格的 HZ
  从 `OK` 变成 `FAIL`。
- **`gb18030` 的判定不再是无条件冲突。** 四字节序列（如 `90 30 81 30`）解不成
  CP936，字节检测给出 `unknown`，旧代码把「检测结果不在已知集合里」当成声明
  与字节冲突，于是合法的 GB18030 源文件被判 `FAIL`。
  **影响**：含四字节序列的 GB18030 源文件从 `FAIL` 变成 `WARN`。
- **`windows-936` 与 `cp54936` 不再被接受。** 这两个是代码页编号，不是
  CPython 的编解码器名——`codecs.lookup()` 对它们抛 `LookupError`，Python 连
  文件都不读就报 `SyntaxError: encoding problem: <名字>`。
  **影响**：这两个声明从 `WARN` 变成 `FAIL`（`PY_SOURCE_CODING_UNKNOWN`）。
  真正的别名是 `cp936` / `ms936` / `936` 和 `gb18030` / `gb18030-2000`。
- **`Test-ScriptEncoding.ps1` 的文本模式新增 `SOURCE_CODING_KIND=`。** 取值
  `unknown-name` / `unusable-codec` / `bytes-mismatch`，只在有
  `SOURCE_CODING_PROBLEM` 时输出，用来分清「名字解析不了」和「字节不合规」。
  JSON 直接给出 `SourceCodingKind`。
- **`gb18030` 的别名收紧。** 只保留实测成立的 `gb18030` 与 `gb18030-2000`；
  `cp54936` / `54936` 见下一条。

### Added

- 夹具 8 个：`py-coding-gb2312.py`、`py-coding-euc-cn.py`、`py-coding-hz.py`、
  `py-coding-hz-truncated.py`、`py-coding-gb18030.py`、
  `py-coding-gbk-as-gb2312.py`、`py-coding-windows936.py`、`py-coding-cp54936.py`。
- 夹具 22 个，覆盖四个修复面：HZ 转义与截断
  （`py-coding-hz-tilde-in-gb` / `-escape-in-gb` / `-close-in-ascii` /
  `-continuation` / `-open`）、编码重叠
  （`py-coding-{gb2312,gbk,gb18030}-overlap`、`py-coding-utf8-as-{gbk,gb2312}`）、
  Latin-1（`py-coding-latin1` / `-ascii` / `-utf8` / `-bom`）、codec 名字
  （`py-coding-{cp1252,shift-jis,big5,54936,hzgb2312,cn-gb,utf8-sig,utf8-spelling-bom}`）。
  夹具总数 46 → 68，原有 46 个的字节 SHA256 全部未变。
- Pester 新增 4 个 Context、26 例：`HZ state machine`、`overlapping encodings`、
  `Latin-1 declarations`、`codec name classification`。Pester 总数 108 → 134。
- 集成测试 `TestGb2312Grid`：用 CPython 自己的 codec 拼出全部 7445 个已分配格
  与若干 GBK 独有格，分别要求检测器给 `WARN` 与 `FAIL`。手工维护的码表会漂移，
  这是唯一能发现漏行的检查。
- 集成测试 `TestGbkGrid`：把 21791 个可解格拼成一个源文件要求放行，再对每个
  有洞的首字节取一格要求拒绝，并单独验证 `0x80` / `0xFF`。这条测试第一次跑就
  抓出了 `A8` / `A9` 低区的 153 格误拒。
- 集成测试 `TestHzStateMachine`：用 `hz` codec 生成七种字节形态，先跑 Python
  再跑检测器，只比较两边结论是否一致，不硬编码某一版本的行为。
- 集成测试 `TestEncodingOverlap`：重叠、可解、不可解三例，`TestPythonSourceCoding`
  的用例表从 13 条扩到 28 条。
- 集成测试 `TestCodingNameAgreement`：把 28 个 codec 名逐个写进真实源文件，
  先问解释器「这个名字能用吗」，再问检测器，只比较两边答案是否一致。名字表
  漏拼写或 stdlib 改别名时这条会红，而不需要用某个版本的结论当标准答案。

### Fixed

- 文档：`references/encoding-matrix.md` 补 §2.1.1（唯一 / 歧义 / 解不出三档）、
  §2.1.2（Latin-1 单字节语义）、§2.1.3（codec 名字四档）、§2.2.1（GBK 21791
  格与 CP936 的 2149 格差异）、§2.2.2（HZ 状态机逐条实测表）、§2.3
  （`WARN` / `FAIL` 的理由码表）。原文里「等价于 CP936」这句被具体差异取代。
- 文档：`New-EncodedScript.ps1` 的 `-Encoding` 说明不再声称 UTF-8 BOM 是
  「5.1 与 7 唯一能同样解析的形式」（UTF-16 带 BOM 两者也能解析）。改为
  「推荐的跨版本存储格式」，并说明推荐理由是其他工具也认。
  `run_ps.py` 里同一句话同步改写。

## [1.0.2] - 2026-11-13

判定精度与测试可信度的修复。检测器有两处"自信地给出错误答案"的盲区，写入器
把"预览"和"取消"混成同一个退出码，测试矩阵里 5.1 与 7 两个作业实际跑的是同一
个 shell。这一版把四处都修掉，并且每条都先由测试复现。

### Changed（会改变既有行为，需注意）

- **`New-EncodedScript.ps1` 新增退出码 `4`：确认提示被拒绝。** `ShouldProcess`
  返回 `$false` 有两种含义——`-WhatIf`（本来就不该写，退出码 `0`，用法不变）
  和用户按了「否」（调用方要写、没写成）。后者现在退出 `4`，结果新增
  `Status=Previewed|Written|Cancelled|Failed`；文本模式输出 `STATE=`，
  `-Output json` 里是 `Status` 字段。
  **影响**：把"确认被拒"当成功处理的自动化调用方会看到非零退出码，这正是这条
  修改的目的。另外 `-WhatIf` 不再经过 `ShouldProcess`，因为它会往 stdout 打
  "What if:" 横幅，混进 `-Output json`。
- **`Test-ScriptEncoding.ps1` 对 UTF-32 的判定从"UTF-16LE"改为
  `utf32le-bom` / `utf32be-bom` 加 `FAIL`。** `FF FE 00 00` 原先被两字节签名
  抢先匹配，报成 UTF-16LE 且第二个字符是 NUL。四字节签名现在优先比对，负载按
  四字节码点校验（大于 U+10FFFF、落在代理区、长度不是 4 的倍数都算无效）。
  检测器仍然只读，不转码、不修复。
  **影响**：这类文件的 `Encoding` / `Bom` 字段与退出码都会变，旧日志里的
  `utf16le-bom` 结论不再复现。
- **`Test-ScriptEncoding.ps1` 识别 Python 源码编码声明（PEP 263）。** 带
  `coding: gbk` 的 GBK 文件本来跑得动，却和缺声明的 GBK 文件一起被判 `FAIL`。
  现在声明有效且与字节相符 → `WARN`（本机跑得动、别的工具读不懂）；声明与字节
  不符或声明了不认识的编码 → `FAIL`；没有声明的 GBK 仍是 `FAIL`。JSON 新增
  `SourceCoding` / `SourceCodingName` / `SourceCodingLine` / `SourceCodingProblem`。
  **影响**：`-Profile python` 下这类文件的退出码可能从 `2` 变成 `1`（配合
  `-FailOnWarning` 仍是 `2`）。
- **`tests/run-all.ps1` 不再自动安装缺失的测试依赖。** 缺 PyYAML 时输出
  `PYTHON_DEP_MISSING=` 与 `INSTALL_WITH=`，或显式加 `-InstallTestDeps`。
  CI 改为自己执行 `pip install -r tests/requirements-test.txt`。
  **影响**：本机首次跑 `-Suite evals` 前要装一次依赖；任何一次测试运行都不会
  再静默联网。
- **集成测试由调用方的宿主决定子进程。** `tests/run-all.ps1` 导出
  `WSW_PS_HOST` / `WSW_PS_EDITION` 并在每次运行开头打印，
  `test_pipeline.py` 据此选择 `powershell.exe` 或 `pwsh.exe`。
  **影响**：以前在 7 上跑集成测试，实际测的是 5.1；现在两个作业的结果不再
  可以互相顶替，日志里也会写明是哪个二进制出的结果。

### Added

- 检测器文本输出新增 `SOURCE_CODING=` / `SOURCE_CODING_LINE=` /
  `SOURCE_CODING_NAME=` / `SOURCE_CODING_PROBLEM=`。
- `tests/requirements-test.txt`：测试依赖的唯一清单。四个工具本身仍然没有
  第三方运行时依赖。
- 7 个新夹具：UTF-32LE/BE 各一份，PEP 263 的四种声明形态各一份，外加缺声明
  的 GBK。字节固定，因此 `tests/fixtures/data/**` 继续按 `-text` 处理。

### Fixed

- `run_ps.py` 的临时目录清理失败不再静默：给出只含目录名、不含脚本文本的警告，
  子进程退出码保持不变。
- 文档更正四处：`$OutputEncoding` 只管管道送入原生程序的 stdin，不含命令行
  参数；文件、控制台、管道、argv 是四层各自独立的编码；"UTF-8 BOM 是唯一
  两边都对的存法"改为"推荐存法"（带 BOM 的 UTF-16 两个版本都能跑，但别的
  工具读不了）；`Get-WinScriptEnvironment.ps1` 标注为每台机器跑一次即可，
  不必每个任务重复诊断。

## [1.0.1] - 2026-11-12

稳定性修复。1.0.0 的三个编码判定错误、`run_ps.py` 的文件语义含糊、写入器
默认值与它自己的规范互相矛盾，这三类问题都在这一版修掉，并且每条都换成了
"先测量再判定"的实现。

### Changed（会改变既有行为，需注意）

- **`Test-ScriptEncoding.ps1` 对 UTF-16 脚本的判定从 `FAIL` 改为 `WARN`。**
  1.0.0 的理由是"Windows PowerShell 5.1 无法可靠解析 UTF-16 脚本"，这句
  话没有验证过，而且是错的：实测 5.1.26100 与 7.7.0 都能解析执行带 BOM 的
  UTF-16LE 与 UTF-16BE 脚本，中文正确。`WARN` 表达的是"能跑但不推荐"——
  `cmd.exe`、`git diff`、多数编辑器按单字节读。真实不成立的是**没有 BOM**
  的 UTF-16，那个仍然 `FAIL`。
  **影响**：用 `-Profile ps51` / `ps7` 检查 UTF-16LE/BE 文件时退出码从 2
  变成 1；带 `-FailOnWarning` 的调用方退出码仍是 2。
- **`New-EncodedScript.ps1` 的默认编码按扩展名推导。** 1.0.0 对任何目标都
  默认 `utf8-nobom`，于是用它写一个含中文的 `.ps1`，产出的正是检测器
  （`-Profile ps51`）判 `FAIL` 的文件——两个工具互相矛盾。现在 `.ps1` /
  `.psm1` / `.psd1` → `utf8-bom`，`.bat` / `.cmd` → `gbk`，其余 →
  `utf8-nobom`；显式 `-Encoding` 永远优先。结果新增
  `ENCODING_SOURCE=explicit|extension`。
- **`run_ps.py` 的用法错误退出码从 2 改为 3。** argparse 默认用 2 表示用法
  错误，与"子进程退出 2"撞车。

### Added

- **`run_ps.py --invoke-file <path>`：保留真实文件上下文的执行模式。**
  路径原样交给子进程的 `-File`，不读、不解码、不复制、不改写文件，因此
  `$PSScriptRoot`、`$PSCommandPath`、`$MyInvocation.MyCommand.Path`、
  `param()`、`[CmdletBinding()]`、相对 dot-source 全部按原生行为工作。
  `--script-args` 之后的内容原样转发给脚本（argv 列表，无 shell）。
  与 `--console-encoding` / `--input-encoding` / `--command` / `--file` /
  `--stdin` / 位置参数互斥，冲突时退出码 3 并说明原因。
- 检测器输出新增 `PAYLOAD_VALID` 与 `PAYLOAD_PROBLEM` 两个字段；编码名新增
  `utf8-bom-invalid` / `utf16le-bom-invalid` / `utf16be-bom-invalid`。
- `tests/cp936/verify-local.ps1`：在真实 zh-CN 机器上一次性跑完 CP936 门禁
  的全部检查，不需要注册自托管 runner。
- `tests/integration/test_package.py`：解压发布包并实际执行里面的工具。
- `test.yml` 新增 `python-utf8-mode` 作业：用 `PYTHONUTF8=1` 模拟 Python
  3.15 的默认 UTF-8 模式（PEP 686），确认默认值改变后行为不退化。

### Fixed

- **UTF-8 BOM 被当成"文件是 UTF-8"的证据，从不检查后面的字节。**
  `EF BB BF FF`、`EF BB BF C3 28`、`EF BB BF E4 B8` 全部返回
  `ENCODING=utf8-bom`、`STRICT_UTF8=True`、`VERDICT=OK`、退出码 0。BOM 是
  声明，不是内容合法的证明，现在标记之后的字节一律严格解码，失败就
  `FAIL` 并给出首个坏字节的偏移。UTF-16 的 BOM 同理，另外单独拦奇数字节与
  孤立代理项。
- **`-ExpectedEncoding ascii` 与 `utf8-nobom` 被当成互兼容。** 一个含 18 个
  非 ASCII 字节的文件在 `-Profile ps7` 下通过了 `-ExpectedEncoding ascii`，
  输出还会出现 `EXPECTED_MATCH=True` 与 `VERDICT=FAIL` 并存的自相矛盾行。
  现在 ascii 的含义是"每个字节都在 0x00–0x7F"，方向不对称：纯 ASCII 满足
  `utf8-nobom`，反之不成立；带 BOM 不算 ASCII。
- **`run_ps.py --file` 的文件上下文随脚本长度变化。** 短脚本走
  `-EncodedCommand`，`$PSScriptRoot` 为空；长脚本被写成临时文件走 `-File`，
  `$PSScriptRoot` 变成临时目录。同一个脚本因长度不同换语义，且没有任何
  提示。现在降级时在 stderr 打三行 `run_ps.py: note:`，点名
  `--invoke-file`。
- **写入器的备份文件会被覆盖。** 备份名是秒级时间戳，而 `File.Replace`
  会覆盖同名备份，同一秒内两次写入会销毁前一个备份。现在遇到同名自动加
  序号。
- **写入失败仍打印 `WROTE=<路径>`。** 失败路径上"已写入"这一行最容易被
  当真，现在非零退出码不再输出该字段。
- `run_ps.py` 的临时目录创建失败、清理失败不再抛异常：分别返回 3 与保持
  子进程退出码。

### Verified

- Windows PowerShell 5.1.26100（Desktop）与 PowerShell 7.7.0（Core）各跑
  一遍完整矩阵：Pester 77、Python 47、文档契约 38、集成 22、
  PSScriptAnalyzer 12 文件 0 告警。
- CP936：本机 ACP=936，`CP936_ASSERTIONS_EXECUTED`。**GitHub 上的
  `cp936` 工作流仍未运行**——仓库没有注册自托管 runner，也没有设置
  `CP936_RUNNER` 变量，每次 push 的结果都是 `skipped`。跳过不等于通过，
  记录见 `tests/cp936/README.md`。
- Python 3.13.9 在默认模式与 `PYTHONUTF8=1`（`sys.flags.utf8_mode=1`）下
  各跑一遍：Python 47、集成 22，全部通过。**没有 3.15 解释器，Python 3.15
  本身未验证**，`python-utf8-mode` 作业只模拟它的默认值。
- 发布包：18 个条目、全正斜杠、无 `.pyc` 与测试物料，
  每个条目与检出逐字节一致；解压到干净目录后三个工具实跑通过，
  `--invoke-file` 的 `$PSScriptRoot` 指向脚本自身目录。
  （这里不写包体字节数：它随本文档变化，写进来就是自指的。）
- `git diff --check origin/main..HEAD` 无告警。

## [1.0.0] - 2026-11-11

第一个按契约重写的版本。0.1.0 是一份写给人看的规则加两个脚本；1.0.0 把
它拆成"入口 + 参考 + 工具 + 测试"四层，并且每个断言都有实测或测试支撑。

### Added

- `scripts/Get-WinScriptEnvironment.ps1`：只读自检，报告 ACP / OEMCP /
  控制台输入输出代码页 / `$OutputEncoding` / `[Encoding]::Default` /
  CP936 可用性 / 运行时版本 / `EXECUTIONPOLICY`。`-Output Json` 出机器
  可读报告，条件成立时附 `WARNING=` 行。
- `references/` 下 10 份参考，按 Progressive Disclosure 组织：
  `encoding-matrix`、`powershell-51`、`powershell-7`、
  `dual-version-compatibility`、`cmd-bat`、`python`、`git-bash`、
  `execution`、`security`、`troubleshooting`。
- `tests/analyze.ps1` 与 `tests/run-all.ps1 -Suite analyze`：静态分析
  成为测试矩阵的一员，而不是"记得就跑一次"的命令。分析范围从
  `scripts/` 扩到 `scripts/` + `tests/`，其中测试树单独排除
  `PSUseDeclaredVarsMoreThanAssignments`（Pester 5 的 `BeforeAll` 作用域
  会让真用到的变量看起来没用到），`tests/fixtures/data` 作为测试载荷
  整体跳过。
- `tests/package.ps1`：发布打包与 release notes 生成，可本地复跑。CI 的
  发布作业调用它，而不是把逻辑写进 YAML。
- 三个工作流：`test.yml`（5.1 / 7 × Python 3.11 / 3.13 矩阵 + 文档契约）、
  `cp936.yml`（自托管 936 runner，宿主不是 936 时直接失败而不是跳过）、
  `release.yml`（只在推 `v*` 标签时运行）。
- `CONTRIBUTING.md`、本 `CHANGELOG.md`。

### Changed

- `SKILL.md` 从 8.5 KB 的单体规则文本改为 5.3 KB 的入口文件：只保留
  路由表、四条硬规则、工具清单与边界声明。细节全部下沉到 `references/`。
- `README.md` 重写：快速开始、四个工具的退出码契约、安装方式、已验证范围。
- `tests/integration/test_pipeline.py` 不再假设子进程总以 CP936 编码
  stdout。原来直接断言 GBK 字节，只要宿主把控制台改成 UTF-8 就误报失败；
  改为用 `GetConsoleOutputCP()` 取真实代码页再断言字符。

### Fixed

- **`run_ps.py --console-encoding` 让 `param()` 静默失效。** prelude 拼在
  用户脚本前面，而 `param(...)` 与 `[CmdletBinding()]` 只允许是第一条语句，
  于是 PowerShell 报 `param : The term 'param' is not recognized`，**照常
  跑完剩下的语句并退出 0**。带参数块的真实脚本走 `--file` 时会静默丢掉所有
  参数。现在只在需要注入 prelude 时才把脚本体包进 `& { … }`，默认路径一个
  字节都不变。新增三个用例：`param()` 不被挤掉、prelude 在包装内仍然生效、
  末尾注释不会把收尾的 `}` 吃掉。
- **检测器在 `-File` 加重定向 stdin 时静默返回 `files=0`。** Windows
  PowerShell 会跳过 `process` 块但照常绑定参数，脚本因此从未打开文件却
  退出码 0。现在逐文件工作抽成 `Add-Inspection`，`end` 里在
  `$script:pipelineRan` 仍为 false 时补跑。
- **打包脚本把 release notes 写成了乱码。** `Get-Content` 不带
  `-Encoding` 时 5.1 按 CP936 解码这份 UTF-8 的 `CHANGELOG.md`，中文全部
  损坏。这是本仓库记录的第一条断链，出现在本仓库自己的构建脚本里。
- **`Compress-Archive` 在 5.1 上把 zip 条目名写成反斜杠**
  （`win-script-writer\SKILL.md`），不符合 APPNOTE，在按规范处理的解压
  工具上会变成一个文件名含反斜杠的怪文件。改为逐条
  `ZipFileExtensions::CreateEntryFromFile` 并显式把分隔符归一成 `/`，
  打包后重新打开 zip 校验，发现反斜杠即以非零退出码失败。
- **静态分析在参数绑定时只打警告、仍然报 `ANALYZER_CLEAN`。**
  `Invoke-ScriptAnalyzer -Path` 不接受文件数组，绑定失败是非终止错误，
  原来会被吞掉。现在每次调用都 `-ErrorAction Stop`，并且打印
  `ANALYZED_FILES=`，分析 0 个文件也算失败。
- `New-EncodedScript.ps1` 覆盖已有文件时 `File.Replace` 传 `$null` 会报
  "The path is not of a legal form"：`$null` 被绑成空字符串。改为使用
  一次性备份路径并在 `finally` 清理。
- `invalid-bytes.bin` 夹具原本用 `0xFF` 当非法字节，但 CP936 在 .NET 中
  没有未定义字节（`0xFF` → `U+F8F5`），导致它被正确判为 gbk。改用
  `0x81 0x20`（前导字节 + 非法尾字节）。
- 三参数 `Join-Path` 在 5.1 上不可用的写法从测试与工具里全部移除。
- `tests/Common/TestHelpers.ps1` 里的两个死变量（`RepoRootPath`、
  `buffer`）与一个空 `catch` 块。
- **CI 工作流把矩阵表达式喂给了 `shell` 键。** GitHub 在展开矩阵之前就解析
  `jobs.<id>.steps[*].shell`，`shell: ${{ matrix.shell }}` 被判为
  `Unrecognized named-value: 'matrix'`，首次推送 0 秒失败，一个 job 都没起。
  改为每个宿主一个 job，`shell` 一律写字面量。同一处还修掉了 7 把模块装到
  `Documents/PowerShell/Modules` 而 5.1 只查
  `Documents/WindowsPowerShell/Modules` 的问题——共用一个安装步骤等于让 5.1
  那一路退回系统自带的 Pester 3.4。
- **测试依赖的解析散落在每个入口，漏一处就红。** 文档契约要解析工作流文件，
  需要 PyYAML；矩阵 job 装了、发布 job 忘了，于是全绿的分支推 tag 后 1 分 40
  秒失败。改为在测试入口脚本里统一探测并安装，所有入口共用一条路径。过程中
  踩到两个坑：`$ErrorActionPreference = 'Stop'` 会把原生程序的 stderr 变成
  终止错误，于是"预期失败"的探测直接终止脚本；`pip install yaml` 找不到发行
  包——模块名是 `yaml`，发行包名是 `PyYAML`，而且装完必须再探测一次才算数，
  pip 返回 0 从来不能证明 `import` 会成功。
- **发布包里混进了 `scripts/__pycache__/*.pyc`。** 打包直接复制目录，本地检出
  干净，所以十次手跑都是 18 个条目；CI 在同一个检出里先跑测试、留下了字节码
  缓存，实际发出 19 个。现在归档前清掉缓存，并把条目对照扩展名白名单校验
  ——黑名单只能挡住已经想到的东西。同一次发布还暴露了
  `if ($LASTEXITCODE -ne 0)` 把成功的打包判成失败：脚本成功时不设置
  `$LASTEXITCODE`，`$null -ne 0` 成立，报错信息因此打印成 "packaging failed
  with " 后面什么都没有。

### Security

- 明确并文档化六条默认不变的行为：不注入 `-ExecutionPolicy Bypass`、
  不默认覆盖文件、不自动改 `ACP`、不自动提权、`run_ps.py` 不是沙箱、
  不静默替换字符。详见 `references/security.md`。

### Verified

本版所有数字都在下列环境实测：Windows 11 简体中文，ACP=936，OEMCP=936，
Windows PowerShell 5.1.26100（Desktop）、PowerShell 7.6.9（Core），
Pester 5.7.1，PSScriptAnalyzer 1.24.0，Python 3.13。

- Pester：50 项，5.1 与 7 各跑一遍，全通过。
- Python：29 项，全通过。
- 集成：7 项，全通过（其中 CP936 专有 3 项在非 936 宿主上跳过）。
- 文档契约：28 项，全通过。
- PSScriptAnalyzer：`scripts/` 全干净，两个宿主各跑一遍。
- GitHub Actions：`windows-latest` 上 5.1 与 7 各配 Python 3.11 / 3.13，
  四个组合全部 `RESULT=PASSED`；`ubuntu-latest` 跑文档契约。CP936 门禁需要
  带 `self-hosted, windows, cp936` 标签的 runner，未配置时该 job 显示
  skipped，而不是无限排队。

## [0.1.0] - 2026-11-09

首个公开版本。

### Added

- 中文 Windows 编码规则文档（`SKILL.md`）。
- `scripts/Test-ScriptEncoding.ps1`：BOM / 非 ASCII / 严格 UTF-8 检测。
- `scripts/New-EncodedScript.ps1`：按指定编码落盘。
- `scripts/run_ps.py`：UTF-16LE base64 传输，绕开命令行代码页。
- `.bat` / `.cmd` 四种存法的实测对照表。
