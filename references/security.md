# 安全原则

这一页约束的不是"用户能做什么"，而是**工具自己默认做什么**。一个诊断/写入
工具在别人的机器上跑，最容易出事的不是它能不能完成任务，而是它在完成任务
之外顺手改了什么。

六条原则，每条都有对应的实现位置和测试。

## 1. 不默认注入 `-ExecutionPolicy Bypass`

**为什么**：`Bypass` 关掉的是整台机器对"这段脚本能不能跑"的最后一道判断。
把它写进包装器的默认值，等于让每一个调用者都在不知情的情况下放弃了自己的
策略配置。

**怎么做**：`scripts/run_ps.py` 的 `--execution-policy` 是显式可选参数，
不传就不加任何 `-ExecutionPolicy` 参数。help 文本里写明这一点。

**自测**：`tests/python/test_run_ps.py` 断言默认 argv 中不含
`-ExecutionPolicy`。

## 2. 不默认覆盖已有文件

**为什么**：这类工具最常见的损坏方式是"我以为它在检测，其实它在重写"。
一次误调用就可能覆盖掉用户未提交的脚本。

**怎么做**：`scripts/New-EncodedScript.ps1` 发现目标已存在时直接报错
`EXISTS` 并退出，必须显式 `-Force` 才写。写的时候先写临时文件、读回校验、
再原子替换（`File.Replace` / `File.Move`），中途失败不会留下半个文件。

**自测**：`tests/powershell/New-EncodedScript.Tests.ps1` 的"overwrite
protection"用例，断言不带 `-Force` 时目标文件字节不变。

## 3. 不自动修改系统级编码设置

**为什么**：`ACP`、`OEMCP`、系统级 UTF-8 开关都是"改完要重启、且会让旧
软件乱码"的设置。一个写脚本的辅助工具没有任何理由动它们。

**怎么做**：`Get-WinScriptEnvironment.ps1` 只读，报告 `ACP` / `OEMCP` /
`ACPSOURCE`，从不写注册表。所有工具都不调用 `Set-ExecutionPolicy`、
不 `chcp`、不改 `ACP`。

**自测**：该工具的 Pester 用例断言读出来的值与注册表一致，且工具在只读
条件下重复执行不产生副作用。

## 4. 不自动提权

**为什么**：提权后的行为不在用户的预期范围内，也无法回滚。诊断工具提权
只会掩盖"权限不足"这个真实结论。

**怎么做**：所有工具在普通用户权限下完整工作。`Get-WinScriptEnvironment.ps1`
读的是 `HKLM` 下的键，读权限对所有用户开放，不需要管理员。

**失败时的正确表现**：报告"读不到"，而不是"我去提个权"。代码里
`Get-RegistryCodePage` 捕获异常后返回 `$null`，输出 `unknown`。

## 5. 明确声明：`run_ps.py` 不是沙箱

**为什么**：把"编码无关的执行器"误当成"安全执行器"是最危险的误读。它不
限制文件系统、不限制网络、不限制能调用的 API，子进程拥有和调用者一样的
权限。

**怎么做**：模块 docstring 的 "What it does not do" 一节第一句就是
`It is not a sandbox.`；`SKILL.md` 与 `references/execution.md` 各重申一次。

**推论**：不要把 `run_ps.py` 当作"执行不可信代码"的方案。不可信代码需要
的是容器、受限账户或 AppContainer，不是一层 base64。

## 6. 不静默替换字符

**为什么**：把无法编码的字符换成 `?` 再继续跑，会让错误出现在很远的下游
（一个配置文件里多了一个问号，一周后才发现）。静默降级比崩溃更难查。

**怎么做**：

- `New-EncodedScript.ps1` 编码时用 `EncoderFallback.ExceptionFallback`，
  GBK 表达不了的字符直接报 `UNREPRESENTABLE_CHARACTER`，不替换。
- `Test-ScriptEncoding.ps1` 检测 CP936 时要求"解码再编码"字节完全一致，
  才敢标 `gbk`，且只给 `confidence=medium`。
- 工具自身的输出一律 ASCII（`VERDICT=OK`、`ENCODING=gbk`），不依赖任何
  代码页。

**自测**：`tests/powershell/New-EncodedScript.Tests.ps1` 用含 emoji 的
fixture 断言非零退出码与明确的错误码。

## 7. 不记录敏感内容

**为什么**：工具会拿到脚本正文、路径、环境变量。这些内容一旦被写进日志或
被回显，就从"我本地的脚本"变成了"某个日志文件里的脚本"。

**怎么做**：

- 工具不写任何日志文件。
- `run_ps.py` 回显的只有子进程真实的 stdout/stderr 字节，不额外打印
  "我执行的命令是……"。
- 错误信息里只出现路径和错误码，不出现脚本正文。
- `--keep-temp` 只在你显式要求时保留临时目录，且临时目录名不含脚本内容。

## 8. 变更的边界

写这类工具时，以下操作即使在测试里也应该走显式路径，不做"自动修复"：

| 操作 | 默认 | 需要 |
| --- | --- | --- |
| 覆盖文件 | 拒绝 | `-Force` |
| 放宽执行策略 | 不加 | `--execution-policy` |
| 改控制台编码 | 不改 | `--console-encoding` |
| 保留临时文件 | 删除 | `--keep-temp` |
| 改系统代码页 | 永不 | 不做，也不提供开关 |

最后一行是刻意的：有些事不是"默认关掉"就够了，而是不应该有这个功能。
