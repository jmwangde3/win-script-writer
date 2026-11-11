# 参与贡献

## 环境准备

- Windows 10/11 简体中文（本项目的目标环境，也是唯一验证过的环境）
- Windows PowerShell 5.1（系统自带）与 PowerShell 7.4+
- Python 3.9+（只用标准库）
- Pester 5.7.1、PSScriptAnalyzer

```powershell
Install-Module Pester -RequiredVersion 5.7.1 -Scope CurrentUser
Install-Module PSScriptAnalyzer -Scope CurrentUser
```

## 跑测试

```powershell
# 全部，两个宿主各跑一次
powershell -NoProfile -File tests\run-all.ps1
pwsh       -NoProfile -File tests\run-all.ps1

# 单套
powershell -NoProfile -File tests\run-all.ps1 -Suite pester
powershell -NoProfile -File tests\run-all.ps1 -Suite analyze
powershell -NoProfile -File tests\run-all.ps1 -Suite python
powershell -NoProfile -File tests\run-all.ps1 -Suite integration
powershell -NoProfile -File tests\run-all.ps1 -Suite evals
```

**提交前两个宿主都要跑。** 只在一个宿主上通过的改动等于没测——本项目的
每条结论都是双版本成立的。

## 硬性约束

这几条由 `tests/evals/test_skill_contract.py` 强制，不通过会被 CI 拦下。

1. `SKILL.md` ≤ 6000 字节。入口文件一旦变大，progressive disclosure 就
   名存实亡。
2. `references/*.md` 每份 ≤ 16000 字节。
3. 每份参考必须在 `SKILL.md` 里被路由；反过来 `SKILL.md` 不能指向不存在的
   文件。加一份新参考＝同时改 `SKILL.md` 的路由表。
4. `SKILL.md` 里提到的每个脚本名必须在 `scripts/` 下真实存在。
5. 代码块总行数在 `SKILL.md` 里 ≤ 80 行。
6. 不出现本机绝对路径（形如系统盘下的用户目录，或任何固定盘符路径）、
   不出现未完成标记、不出现占位凭据。

## 文件的行尾与编码

仓库级的取舍写在 `.gitattributes`，不要绕过它：

| 文件 | 行尾 | 编码 |
| --- | --- | --- |
| `*.ps1` `*.psm1` `*.psd1` `*.bat` `*.cmd` | CRLF | ASCII（工具自身不写中文） |
| `*.py` `*.sh` `*.md` `*.yml` `*.json` | LF | UTF-8 无 BOM |
| `tests/fixtures/data/**` | 原样 | 原样，`-text` 保护 |

最后一行的意思是：夹具的字节就是被测对象，任何行尾转换都会让整条测试链
失效。改夹具请改 `tests/fixtures/New-Fixtures.ps1` 生成器再重新生成。

`*.ps1` 用 CRLF 是因为目标读者在 Windows 上；工具自身的脚本保持纯 ASCII，
所以不需要 BOM——这是本仓库唯一"不需要 BOM"的场合，因为它们是 ASCII 的。

## 工具脚本的约定

写新的 `scripts/*.ps1` 时：

- 必须能跑在 5.1 和 7 上。避开 `references/dual-version-compatibility.md`
  的语法禁区。
- 输出用 `KEY=value` 或 JSON，**只用 ASCII**。不要把中文放进 stdout。
- 退出码要给文档：0 成功，1 可容忍的警告，2 硬失败，3 参数或 I/O 错误。
- 默认不改系统状态。需要改的走显式参数，见 `references/security.md`。
- 写完用 `tests/run-all.ps1 -Suite analyze` 过一遍静态分析。
- 补一份对应的 `tests/powershell/<Tool>.Tests.ps1`，并且**通过子进程**调用
  被测工具——工具里会 `exit`，进程内调用会终止 Pester 宿主。

## 文档的约定

- 数字必须有出处。要么有测试，要么有实测命令，要么明确写"未实测"。
  不要用"一般来说"、"通常"来掩盖没验证过的事。
- 结论要能落到一条可执行的修法。`troubleshooting.md` 的每一行都应该让
  读者复制粘贴就能试。
- 中文正文，技术术语保留英文原文（`Out-File`、`$OutputEncoding`、
  BOM、CP936）。
- 表格单元格不要塞长句，宁可拆成列表。宽表格在窄窗口里会被截断。

## 提交

- 一个阶段一个提交，提交信息说明**为什么**改，不只是改了什么。
- 提交信息用英文，`type(scope): subject` 形式。
- 不把"顺手格式化"混进功能改动。
- 不动别人的未提交改动。要动先问。

## 实测记录怎么留

新增一条"实测"结论时，同一个提交里要带：

1. 一句说明测试条件（宿主版本、代码页、载荷）。
2. 具体的字节或码点，而不是"正常/不正常"。
3. 如果结论推翻了旧文档，在 `CHANGELOG.md` 的 `Fixed` 里写清楚。

`references/cmd-bat.md` 第 6 节记了一个反面例子：用子串匹配判定 `PATH_OK`
被 echo 回显污染，看起来全绿其实全错。测试判定不要依赖可能被污染的输出。
