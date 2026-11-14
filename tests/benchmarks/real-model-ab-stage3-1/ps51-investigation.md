# PS51 investigation: the 75/100 shared gap

## What the task actually asks

Prompt (`../quality-ab/tasks.json`, `ps51-01`):

> 在 H:\work\部署 目录下新建 deploy.ps1，里面输出中文提示「开始部署」，并在最后打印完成状态。要求这个脚本在 Windows PowerShell 5.1 上直接双击也能正确显示中文。

Benchmark `expected_behavior`:

> Writes the file as UTF-8 with BOM, uses explicit encoding on all I/O, does not rely on the profile.

The prompt uses 新建 (create). The benchmark contract is explicit that the answer is
expected to write the file, not just describe how to save it.

## What the two answers did

| Sample | How the file is produced | Programmatic write |
| --- | --- | --- |
| A / S01 | "把下面内容保存为 `H:\work\部署\deploy.ps1`。保存时选择 UTF-8 with BOM" | no |
| B / S05 | "把以上内容保存到 `H:\work\部署\deploy.ps1`，并在编辑器的保存编码中明确选择 UTF-8 with BOM" | no |

Both scripts are valid, both run under 5.1, both produce `开始部署` and `部署完成`, and both
end up as UTF-8 with BOM when the harness writes them. The only missing 25 points in the
stage-3 score is the "programmatic write" check:

| Check | A | B |
| --- | ---: | ---: |
| Script parses | 25 | 25 |
| File is UTF-8 BOM | 25 | 25 |
| Runs on 5.1 with Chinese output | 25 | 25 |
| Programmatic write (`WriteAllText` / `UTF8Encoding`) | **0** | **0** |
| Total | 75 | 75 |

## Is the Skill missing the method?

No. `references/powershell-51.md` §2 already shows the sequence:

```powershell
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($temp, $text, $Utf8NoBom)
$back = [System.IO.File]::ReadAllText($temp, $Utf8NoBom)
if ($back -cne $text) { throw 'VERIFY_FAILED' }
```

`SKILL.md` rule 1 states that non-ASCII in a `.ps1` must be UTF-8 with BOM. The BOM
variant is the same call with `$true`; the independent write test
(`ps51-write-test.json`) confirms it works on 5.1 and 7.7 with a Chinese path:

- exit 0 on both hosts
- first bytes `EF BB BF`
- read-back equals the original string
- the file is inside the temp root

So the documentation contains the method and the rule. The models chose a manual save
instruction anyway. That is a **model behavior gap**, not a missing documentation step.

## Decision

**Do not modify the formal Skill in this round.**

- The task prompt's 新建 is not explicit enough to prove a documentation defect, and the
  docs already contain the method.
- Changing `references/powershell-51.md` would invalidate the frozen candidate snapshot
  and require regenerating B samples; the evidence does not justify that cost.
- Adding a BOM example would not fix the observed behavior, because the equivalent
  no-BOM example is already there.

## Recommendation for the next round

Add a dedicated benchmark task that states the requirement unambiguously, for example:

> 用脚本自动把 `deploy.ps1` 写到 `H:\work\部署`，不要让我在编辑器里手动保存；保存后读回文件确认开头是 EF BB BF。

That task would measure the programmatic-write behaviour directly, while the current
`ps51-01` continues to measure the script content and the encoding advice. Do not change
the docs to chase an ambiguous prompt.
