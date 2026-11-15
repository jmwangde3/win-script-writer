# Plan: stage 3.2 validation

## Experiments

| Task | A | B | Requirement |
| --- | ---: | ---: | --- |
| `bat-codepage-01` | 3 | 3 | 936 and 65001, Chinese path/argument, exit 7, no manual console change |
| `ps51-autowrite-01` | 3 | 3 | script writes `deploy.ps1` with UTF-8 BOM, reads it back, runs on 5.1 |

Twelve fresh answers, one `codex exec --ephemeral` session each, shuffled order, same
`gpt-6-luna` client and reasoning level, prompts unchanged between A and B.

## BAT checks (100)

| Check | Points |
| --- | ---: |
| GBK, no BOM, CRLF, answer mentions encoding and CRLF | 20 |
| explicit `chcp` (936 for GBK, or 65001 for a UTF-8 file) | 20 |
| runs at 936 with exit 7, `BUILD_OK`, `构建完成` and the argument | 20 |
| runs at 65001 with the same result | 20 |
| Chinese output and argument present in both runs | 20 |

## PS51 checks (100)

| Check | Points |
| --- | ---: |
| programmatic write (`WriteAllText` / `Set-Content` / `Out-File`) | 20 |
| file actually created | 20 |
| UTF-8 BOM (`EF BB BF`) | 20 |
| Chinese read-back matches | 20 |
| runs on Windows PowerShell 5.1 | 20 |

Talking about `WriteAllText` is not enough; a save-dialog instruction is not enough; a file
that is not created is zero for creation, BOM and read-back.

## Controls

- Same model, client, reasoning level and prompt per task.
- A uses only `baseline/v1.0.4`; B uses only `candidate/v1.1.0`.
- Each answer is a fresh session; no old answer is shown to the model.
- Random A/B interleaving; no grouping label in the prompt.
- Actual opened references recorded.

## Safety

- Normal user, no admin, no `-ExecutionPolicy Bypass`.
- Parser gate for PowerShell; dangerous-command scan for both; path rewriting into the
  per-sample temp directory; timeouts; stdout/stderr/exit captured; file hashes recorded.
- A temp directory is not an OS sandbox. That limit is reported, not hidden.

## Verdict

- **PASS**: BAT A/B 3/3 and PS51 A/B 3/3, no safety violation.
- **CONDITIONAL**: a reproducible quality gap remains.
- **FAIL**: a safety regression or a core compatibility failure that cannot be explained.

No formal Skill change unless a reproducible document defect is proven. The current
evidence points to model behaviour against rules already present in the references.
