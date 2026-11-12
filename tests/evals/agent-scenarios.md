# Agent 触发评测：14 个固定任务

这份清单回答一个问题：**skill 被正确触发、并且只加载该加载的那一份参考了吗。**

它不能自动化。仓库里没有任何东西能观察"某个 agent 在某个会话里读了哪些文件"，
所以这里不写假的通过率，而是给出一份可以照着跑、结论可以逐条打勾的验收表。
自动化能覆盖的部分（路由表里有没有这一份、首次加载体积多大）放在
`tests/evals/test_agent_scenarios.py`，两者分工明确：

| 谁 | 检查什么 |
| --- | --- |
| `test_agent_scenarios.py` | 每个正向任务要用的参考确实在 `SKILL.md` 路由表里；负向任务不点名任何参考；首次加载体积在预算内 |
| 本文档（人工） | agent 真的按这张表加载了吗，有没有多读、有没有重复探测环境、输出是否合规 |

## 怎么跑

对每个任务，在一个**干净会话**里只发"任务"一列的原话，不给任何提示。记录：

1. `skill_loaded`：有没有加载 `win-script-writer`。
2. `refs_read`：实际读了哪些 `references/*.md`。
3. `extra_refs`：读了不该读的份数（期望 0）。
4. `env_probes`：`Get-WinScriptEnvironment.ps1` 跑了几次（期望 ≤1）。
5. `output_ok`：产出的脚本是否满足该任务对应的编码规则。
6. `verified`：是否在交付前跑了 `Test-ScriptEncoding.ps1` 或实际执行一次。
7. `tokens`：宿主能给出真实计费数字时记录真实值。**给不出就写"未测量"，
   不要估算。**

## 正向任务（期望触发）

| # | 任务原话 | 应加载 | 不应加载 | 输出合格判据 |
| --- | --- | --- | --- | --- |
| P1 | 帮我写一个 PowerShell 5.1 脚本，把某目录下所有 .log 按日期归档，里面有中文提示 | `references/powershell-51.md` | 其余 9 份 | 落盘 UTF-8 with BOM；不用 `>` / `Out-File` 写数据；`VERDICT=OK` |
| P2 | 写个 PowerShell 7 的脚本，并发下载一批 URL 并汇总结果 | `references/powershell-7.md` | `powershell-51.md`（除非提到要兼容 5.1） | 不额外加 BOM；`$PSNativeCommandArgumentPassing` 之类 7 专属写法有判空 |
| P3 | 这个脚本要同时能在 5.1 和 7 上跑，帮我改一下 | `references/dual-version-compatibility.md` | 不自动展开读 51/7 两份 | 不出现 7 专属语法；`#Requires -Version 5.1` |
| P4 | 写个 .bat，删掉临时目录里的旧文件，路径里有中文 | `references/cmd-bat.md` | 不读 powershell 两份 | 无 BOM；GBK 或首行 `chcp 65001`；中文路径用引号包住 |
| P5 | 在 PowerShell 里调用一个路径带中文、参数里还有引号的命令，总是报字符串缺少终止符 | `references/execution.md` | 不读 python.md | 给出 `-File` 或 `run_ps.py --invoke-file`，不是继续拼 `-Command` |
| P6 | 帮我看看这个文件到底是什么编码，为什么 5.1 读出来是乱码 | `references/encoding-matrix.md` | 不读 troubleshooting.md 之外的多余份 | 用检测器给 `ENCODING=`/`PAYLOAD_VALID=`/`VERDICT=`，不靠肉眼断言 |
| P7 | 把这段中文内容写进 build.ps1，别把原文件弄坏 | `references/security.md` | 不读 git-bash.md | 用 `New-EncodedScript.ps1`，不传 `-Encoding` 时按扩展名得 utf8-bom；先 `-WhatIf` 或 `-Backup` |
| P8 | 我的 ps1 里中文全是乱码，给我一条命令修好 | `references/troubleshooting.md` | 不读 security.md | 症状定位到具体断链，给一条可执行命令，不笼统说"改编码" |
| P9 | 写个 Python 脚本扫目录、把结果写成 json，在 Windows 上跑 | `references/python.md` | 不读 powershell 两份 | 每个 `open()` 都有 `encoding=`；输出只用 ASCII 或显式 reconfigure |
| P10 | 在 Git Bash 里跑 git status，中文文件名显示成 \344\270\255 | `references/git-bash.md` | 不读 cmd-bat.md | 给 `git -c core.quotepath=false status`，并说明只是显示问题 |

## 负向任务（期望不触发）

| # | 任务原话 | 期望 |
| --- | --- | --- |
| N1 | 写个 bash 脚本，把 /var/log 下超过 7 天的文件删掉 | 不加载本 skill（Linux 无关） |
| N2 | 写一个快速排序的 JavaScript 实现 | 不加载 |
| N3 | 解释一下 TCP 三次握手 | 不加载 |
| N4 | 用 Python 写一个 LRU 缓存类 | 不加载 |

负向任务里出现 `bash`、`Python` 这类词是故意的：它们和本 skill 的关键词
有重叠，能不能忍住不加载，是这套路由是否真的"按任务"而不是"按关键词"的
检验点。

## 结果记录模板

每个任务一行，六列照抄：

```text
task | skill_loaded | refs_read | extra_refs | env_probes | output_ok | verified | tokens
P1   |              |           |            |            |           |          |
```

## 已知限制

- **没有自动化。** 结论依赖人工照表执行，不同执行者的记录不能直接对比。
- **Token 数字默认没有。** 宿主不暴露计费明细时，本表只记录"读了哪些文件"，
  不记录"花了多少 token"。`test_agent_scenarios.py` 报的是**字节数**，那是
  可精确测量的，但字节不等于 token，不要把两者混用。
- **`skill_loaded` 为否不一定是缺陷。** 一个足够小的任务（例如"这个 `>` 和
  `Out-File` 有什么区别"）即使不加载也能答对；这一列用来发现"该加载却没
  加载"，不是用来追求加载率。
