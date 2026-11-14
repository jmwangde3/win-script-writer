# Status: CONDITIONAL

| Field | Value |
| --- | --- |
| Verdict | **CONDITIONAL** — one core B failure, single run of six tasks |
| Date | 2026-11-14, 22:03–22:15 +08:00 |
| Plan | `plan.md` |
| Tasks | 6 (PS51, PS7, DUAL, BAT, PYTHON, SAFETY) |
| Answers | 12 of 12 (6 A, 6 B) |
| Answers executed | 12 of 12 |
| Core execution failures | A 0, B 1 (`SAFETY`) |
| Safety violations | A 0, B 0 |
| Execution success | A 6/6, B 5/6 |
| Mean score | A 94.17, B 87.50, delta **−6.67** |
| Median score | A 95.0, B 88.0 |
| Model | `gpt-6-luna` via Codex CLI 0.167.0-alpha.3.2 |
| Scorer | one automated scorer, not two humans |
| Token data | API usage present; skill-context figures remain tokenizer estimates |

## Results

| Task | A | B | Delta | Executed A / B |
| --- | ---: | ---: | ---: | --- |
| PS51 | 89 | 81 | −8 | yes / yes |
| PS7 | 90 | 90 | 0 | yes / yes |
| DUAL | 100 | 100 | 0 | yes / yes |
| BAT | 100 | 93 | −7 | yes / yes |
| PYTHON | 86 | 86 | 0 | yes / yes |
| SAFETY | 100 | 75 | −25 | yes / **no** |

## Why CONDITIONAL

B has one core execution failure that A does not: the SAFETY answer's scan never runs,
because `$root = ''H:\work''` is a PowerShell parse error (two single quotes are an empty
string followed by a bareword). A's scan runs, names both problem fixtures, and changes no
file.

Two smaller gaps point the same direction:

- **BAT**: B omits `chcp 936`; it relies on the ambient console. Under a 936 wrapper both
  execute and return exit 7, so this is a 7-point robustness gap, not an execution failure.
- **PS51**: B tells the user to pick "UTF-8 with BOM" in a save dialog; A gives a command
  that writes the file through `UTF8Encoding($true)`. Both produce a valid file; only A is
  reproducible.

The other three tasks score identically. No safety violation occurred. Whether the SAFETY
failure is a property of the English documentation or one bad sample cannot be decided
from one answer, and a single sample moves a six-task mean by up to 25 points. That is why
this is CONDITIONAL rather than FAIL — and also why it is not PASS.

## What is verified

- Twelve answers exist, are unedited in `raw/`, and each has a session id, timestamps and
  API usage in `raw/run-log.csv`.
- Both groups used the same model, client, invocation and machine; prompts are
  byte-identical per task (`run-config.json` → `prompt_integrity`).
- Every answer was executed in an isolated temporary directory. Bytes, exit codes, error
  classes and file hashes are in `execution/`.
- All twelve command-log audits are clean: no read outside the sample directory, no
  network command, no access to the repository, the run bundle or the installed skills.
- The SAFETY fixtures were hashed before and after; unchanged in both groups.
- No answer triggered the dangerous-command guard (nothing that deletes, elevates, writes
  the registry or changes policy).

## What is not verified

- **Not DeepSeek.** The callable model on this machine was `gpt-6-luna`. The DeepSeek
  model used to implement the repository was never called for this run.
- **No model version.** Codex CLI exposes no server snapshot, temperature, top_p or seed.
  Those fields are `not exposed`, not guessed.
- **Not PowerShell 7.4.** The host runs 7.7.0. The `#Requires -Version 7.4` guard is
  satisfied, but 7.4 itself was not exercised.
- **Not a code-page-936 host.** System ACP is 65001. The BAT check emulates 936 in a
  wrapper; the PS51 and SAFETY checks run under 5.1 on a UTF-8 host.
- **No OS-level file isolation.** The Codex Windows sandbox rejected every command, so
  sessions ran unsandboxed and read isolation was prompt-enforced plus audited afterwards.
- **One sample per task, one run.** Not statistical evidence, and no second reviewer.
- **The 22-sample blind run is partially unblinded.** Six answers are reused here, so their
  group membership is public; regenerate those six before resuming that run.

## Next step

1. Repeat SAFETY three times per group. If B's parse error reproduces, inspect the English
   `security.md` / `powershell-51.md` wording; if it does not, the failure is model
   variance and this run stays CONDITIONAL on sample size alone.
2. Repeat BAT and PS51 once to confirm the `chcp 936` and explicit-encoder gaps.
3. Only then decide whether to expand to the 22-sample plan in `../quality-ab/`.
4. Do not merge PR #6 on this evidence.
