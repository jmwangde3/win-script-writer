# Status: PASS

| Field | Value |
| --- | --- |
| Verdict | **PASS** — BAT A/B 3/3, PS51 A/B 3/3, no safety violation |
| Date | 2026-11-15 |
| Branch | `test/v1.1.0-stage3-2-validation` (from `dddeede`) |
| Run root | `%TEMP%\wsw-v110-stage3-2\20261115-100407` |
| Model | `gpt-6-luna` via Codex CLI 0.167.0-alpha.3.2 |
| Samples | 12 fresh: BAT A3/B3, PS51 A3/B3 |
| BAT | A 3/3, B 3/3, both code pages 936 and 65001 |
| PS51 | A 3/3, B 3/3, automatic write, BOM, read-back, 5.1 |
| Mean score | BAT 100 / 100, PS51 100 / 100 |
| Safety violations | **0** |
| Parser | 6 PASS (PS51), 6 N/A (BAT), 0 FAIL / REVIEW / unclassified |
| Formal Skill | **not modified** |
| Full report | `report.md` |

## What changed

1. **BAT root cause**: the stage-3.1 S07 failure was a correct GBK file at a 65001 console
   with no `chcp`. The doc already shows `chcp`; the model omitted it. Classification:
   `MODEL_OMISSION`.
2. **BAT task**: a new prompt requires both code pages without manual changes. All six
   answers chose UTF-8 without BOM plus `chcp 65001`; both code pages pass with exit 7,
   `BUILD_OK`, `构建完成` and the Chinese argument.
3. **PS51 task**: a new prompt requires programmatic creation, BOM, read-back and 5.1.
   All six answers pass; the old manual-save gap was prompt ambiguity and model behaviour,
   not a missing document method.
4. **No formal Skill change.** The references already contain the rules and the method.

## Token caveat

For these two new tasks the context saving is **negative**: B opened
`encoding-matrix.md` in addition to the task page, while A opened `execution.md`. The
arithmetic mean is **−30.61%**, weighted **−30.78%** (A 33,272; B 43,513 tokens). This is a
real task-specific cost, not a measurement error. The stage-3 six-task figures remain
positive and are not replaced by this number.

## Routing caveat

6 of 12 samples match the declared plan. A's v1.0.4 routing uses `execution.md` for BAT,
so the plan was written for B. The actual opened list is recorded per sample; routing
match is reported, not used as a quality gate.

## Why PASS

The task's PASS criteria are met: BAT A/B 3/3, PS51 A/B 3/3, no safety violation, and the
relevant tests plus CI pass. The negative token result is a cost observation, not a
functional or safety regression. The absence of an OS sandbox is recorded as a residual
risk, not used to downgrade the verdict.

## Limits

- Temp-directory containment plus pre-review, **not OS isolation**.
- Model `gpt-6-luna`, not DeepSeek; PowerShell 7.7, not 7.4.
- Three samples per side; this is a targeted validation, not a statistical proof.
- The historical `bat-01` and `ps51-01` tasks are unchanged; these are separate tasks.

## Next step

1. Decide whether the negative context cost on these tasks matters for the release claim.
2. Keep the separate auto-write task; do not rewrite the old prompt.
3. Do not merge PR #6 on this evidence alone; the release decision also needs the token
   trade-off review.
