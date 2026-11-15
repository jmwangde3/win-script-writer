# Stage 3.1 report: benchmark closeout and PS51

**Verdict: CONDITIONAL.**

B is lower on BAT and PS51; there is no safety violation. Three samples per side
is still a screening, so this is CONDITIONAL, not PASS. The BAT gap is the one to
watch: it reproduces the stage-3 observation in one of three new B answers.

## Task results

| Task | A n | B n | A success | B success | A mean | B mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SAFETY | 3 | 3 | 3 | 3 | 100.0 | 100.0 |
| BAT | 3 | 3 | 3 | 2 | 100.0 | 83.3 |
| PS51 | 3 | 3 | 3 | 3 | 83.3 | 75.0 |

## Parser on the eight new samples

| Metric | Value |
| --- | ---: |
| PASS / FAIL / REVIEW / N/A | 4 / 0 / 0 / 4 |
| Unchecked PowerShell blocks | 0 |
| Unclassified blocks | 0 |
| Unclosed fences | 0 |

## Token

| Task | A mean | B mean | Saving |
| --- | ---: | ---: | ---: |
| PS51 | 5549.3 | 5367.3 | 3.28% |
| BAT | 2916.0 | 2755.0 | 5.52% |
| SAFETY | 8632.0 | 6717.0 | 22.18% |

Arithmetic mean: **10.33%**; weighted: **13.21%**. These are tokenizer estimates, not GPT-6-Luna context usage.

## Findings

- **BAT:** A is 3/3 at both code pages. B is 2/3: one answer omits `chcp 936`, so
  it passes at 936 and fails at 65001. This repeats the stage-3 single observation
  and is now a 1-of-3 rate, not a one-off.
- **PS51:** A provides a programmatic `WriteAllText` in 1 of 3 samples (score 100);
  B provides none (75 each). All six scripts run and produce the expected Chinese
  output; the difference is only the programmatic-write check.
- **SAFETY:** unchanged from stage 3, 3/3 for both groups, no safety violation.

## PS51

`references/powershell-51.md` already shows the `WriteAllText` + `UTF8Encoding`
pattern, and `SKILL.md` rule 1 states the BOM requirement. The models still chose
a manual save dialog in 5 of 6 samples. This is model behaviour, not a missing
document step, so the Skill is unchanged. The independent write test
(`ps51-write-test.json`) proves the method works with a Chinese path on 5.1 and
7.7. A dedicated task with explicit automatic-write wording is the recommended
next step.

## Routing

`tool-02` now declares `encoding-matrix.md` + `powershell-51.md`; the metadata test
and `routing-fix.json` record the change. No Skill change.

## Limits

- Temp-directory containment, not OS isolation.
- Model `gpt-6-luna`, not DeepSeek; PowerShell 7.7, not 7.4.
- BAT/PS51 now 3 samples per side; SAFETY remains the stage-3 3+3.
