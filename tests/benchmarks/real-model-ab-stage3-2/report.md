# Stage 3.2 report: BAT code pages and PS51 automatic write

**Verdict: PASS.**

## Task results

| Task | A n | A success | A mean | B n | B success | B mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BAT | 3 | 3 | 100.0 | 3 | 3 | 100.0 |
| PS51 | 3 | 3 | 100.0 | 3 | 3 | 100.0 |

## Failed checks

- BAT A: none
- BAT B: none
- PS51 A: none
- PS51 B: none

## Parser

| Metric | Value |
| --- | ---: |
| PASS / FAIL / REVIEW / N/A | 6 / 0 / 0 / 6 |
| Unchecked PowerShell blocks | 0 |
| Unclassified blocks | 0 |

## Token

| Task | A mean | B mean | Saving |
| --- | ---: | ---: | ---: |
| BAT | 5792.0 | 7787.3 | -34.45% |
| PS51 | 5298.7 | 6717.0 | -26.77% |

Arithmetic mean **-30.61%**, weighted **-30.78%**. Tokenizer estimates, not GPT-6-Luna context usage.

The saving is **negative** for these two new tasks: B opened `encoding-matrix.md`
in addition to the task page, while A opened `execution.md`. That is a real
task-specific context cost, not a measurement error; the stage-3 six-task numbers
remain positive.

Routing: 6 of 12 samples match the declared plan. A's v1.0.4 routing uses
`execution.md` for BAT, so the plan was written for B. The actual opened list is
recorded per sample; this is not a quality gate.

## Root causes

- BAT: see `bat-root-cause.md`. The stage-3.1 failure was a GBK file at a 65001
  console, fixed by `chcp`; the doc already shows it.
- New BAT task: all six answers chose UTF-8 without BOM plus `chcp 65001`; both
  code pages pass. The explicit requirement, not the encoding choice, closed the gap.
- PS51: see `ps51-root-cause.md`. The old task was ambiguous about automatic
  creation; the new task makes it explicit and all six answers write the file.

## Skill changes

None. No reproducible document defect was found; the failures are model behaviour
against rules or requirements that the prompt and the references already state.

## Limits

- Temp-directory containment, not OS isolation.
- Model `gpt-6-luna`, not DeepSeek; PowerShell 7.7, not 7.4.
