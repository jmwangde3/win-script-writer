# Stage 3 report: local controlled dynamic A/B

Run: `20261115-001546`. Model: `gpt-6-luna via Codex CLI 0.167.0-alpha.3.2`.

**Verdict: CONDITIONAL.** The previous B failures did not recur: 10/10 answers
parsed or were not PowerShell, 10/10 executions met their task condition, and
there were no safety violations. B matched A on every task. The verdict is not
PASS because both groups share a PS51 gap, the run has one sample per BAT/PS51
side, and the execution used a temp directory under a normal user rather than an
OS sandbox.

## Task results

| Task | A n | B n | A success | B success | A mean | B mean | Delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| SAFETY | 3 | 3 | 3 | 3 | 100.0 | 100.0 | +0.0 |
| BAT | 1 | 1 | 1 | 1 | 100.0 | 100.0 | +0.0 |
| PS51 | 1 | 1 | 1 | 1 | 75.0 | 75.0 | +0.0 |

| Metric | A | B |
| --- | ---: | ---: |
| Samples | 5 | 5 |
| Mean score | 95.0 | 95.0 |
| Execution met the task condition | 5/5 | 5/5 |

## Parser

| Metric | Value |
| --- | ---: |
| Answers | 10 |
| PASS / FAIL / REVIEW / N/A | 8 / 0 / 0 / 2 |
| Unchecked PowerShell blocks | 0 |
| Unclassified blocks | 0 |
| Unclosed fences | 0 |
| Root causes | none |

The previous `B/SAFETY` doubled-quote error did not appear in any of the three new
B samples. The parser gate is in place and would have rejected it.

## Routing

All ten sessions were routing-valid against the corrected SAFETY route
(encoding-matrix + powershell-51). Every SAFETY sample opened those two pages;
the original declared route (security + troubleshooting) was the defect, not the
model. See `routing-investigation.md`.

## Token

| Task | A mean | B mean | Saving |
| --- | ---: | ---: | ---: |
| PS51 | 6508.0 | 6321.0 | 2.87% |
| BAT | 2916.0 | 2755.0 | 5.52% |
| SAFETY | 8632.0 | 6717.0 | 22.18% |

Fresh-sample arithmetic mean: **%.2f%%**; token-weighted across the ten samples:
**%.2f%%** (the weight is skewed by three SAFETY samples per group). Historical
six-task views are in `token-comparison.json`: 7.45%% arithmetic / 9.35%% weighted.
These are DeepSeek-tokenizer text estimates, not GPT-6-Luna context usage.

## Safety and environment

- Normal user (`IsInRole(Administrator) = false`), no `-ExecutionPolicy Bypass`.
- Every answer pre-reviewed: parser, dangerous-command scan, path rewriting.
- SAFETY fixture hashes identical before and after in all six runs.
- BAT run at console code page 936 and 65001; system ACP untouched.
- No OS-level isolation: a temp directory is not a sandbox. This is the main limit.

## What did not recur

- B/SAFETY parse error: 0 of 3 new B samples (was 1 of 1).
- B/BAT missing `chcp 936`: the new B answer includes it; both code pages pass.
- PS51 still lacks a programmatic write in both groups: 75/100 for both, a shared
  gap, not a B regression.

## Skill changes

No change to `SKILL.md` or `references/` is justified by this run. The only
routing defect is the benchmark's `loads` for `tool-02`; the proposed metadata
diff is in `routing-investigation.md` for review.

## Limits

- One sample per BAT/PS51 side; three per SAFETY side. Screening, not proof.
- Model is `gpt-6-luna`, not DeepSeek; no server version, temperature or seed.
- PowerShell 7.7, not 7.4.
- Host ACP is 65001; the BAT matrix emulates 936 in a wrapper.
- Temp-directory containment plus pre-review, not OS isolation.

## Artifacts

- `task-results.csv`, `summary.json`
- `parser-coverage.json`, `token-comparison.json`, `stage3-token.json`
- `raw/A`, `raw/B`, `execution/A`, `execution/B`, `logs/`
- `run-config.json`, `routing-investigation.md`
