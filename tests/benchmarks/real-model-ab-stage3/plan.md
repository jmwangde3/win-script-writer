# Plan: stage 3, local controlled dynamic test

## Question

Does the English documentation (B) keep quality while saving context, now that the test
can actually execute the generated scripts on this machine?

## Design

| Item | Value |
| --- | --- |
| Model | `gpt-6-luna` through Codex CLI 0.167.0-alpha.3.2 |
| Samples | SAFETY A3/B3, BAT A1/B1, PS51 A1/B1 — ten fresh answers |
| Order | shuffled by `make_bundle.py`, recorded in `run-order.txt` |
| Sessions | one `codex exec --ephemeral` per answer, empty `CODEX_HOME` |
| Prompt | copied unchanged from `../quality-ab/tasks.json` |
| Isolation | normal user, per-sample temp directory, no admin, no policy bypass |

## Safety rules

1. Current user must not be an administrator. The run stops otherwise.
2. Every answer is parsed block by block. FAIL, REVIEW_REQUIRED or an unclassified block
   means no execution.
3. A destructive, registry, policy, elevation or network command means no execution.
4. The documented paths (`H:\work`, `H:\工作\发布`) are rewritten into the per-sample
   sandbox; any other absolute path outside it means REVIEW_REQUIRED.
5. PowerShell runs without `-ExecutionPolicy Bypass`.
6. Every run has a timeout and records stdout, stderr and the exit code.
7. SAFETY fixtures are hashed before and after; a change is a safety violation.
8. No system ACP change. The BAT matrix sets the console code page inside a wrapper only.

A temp directory is not an OS sandbox. The scripts are pre-reviewed and confined by path
rewriting, but a determined script could still reach outside; that residual risk is stated
in the report rather than hidden.

## Execution per task

| Task | Fixture | What is checked |
| --- | --- | --- |
| SAFETY | five `.ps1` files with known encodings, two of them problems | scan runs, names both, hashes unchanged |
| BAT | Chinese path + compiled `build.exe` returning 7 | GBK, CRLF, no BOM, 936 and 65001 runs, exit 7 |
| PS51 | `部署\deploy.ps1` | programmatic write, UTF-8 BOM, runs on 5.1, Chinese output |

## Scoring

100 points per sample, all objective:

| Task | 25 | 25 | 25 | 25 |
| --- | --- | --- | --- | --- |
| SAFETY | parser PASS | scan ran | both problem files named | fixtures unchanged |
| BAT | GBK/CRLF/no BOM | `chcp 936` present | runs at 936 | runs at 65001 |
| PS51 | programmatic write | UTF-8 BOM | runs on 5.1 | Chinese output present |

`execution_ok` is separate from the score: it means the task's own acceptance condition
was met, not that the process exited 0.

## Verdict rules

- **PASS**: every sample parses, every execution either passes or is legitimately blocked
  by a documented environment limit, no safety violation, B not worse than A.
- **FAIL**: B reproduces a core failure A does not, or a safety violation occurs.
- **CONDITIONAL**: mixed results, routing invalid samples, or a blocker that prevents a
  complete comparison.

## Scope note

No change to `SKILL.md` or `references/` in this round. The routing finding is a benchmark
metadata defect; the proposed diff is in `routing-investigation.md` for review.
