# Second follow-up: parser coverage, token weighting, routing audit

Date: 2026-11-14. Branch: `test/v1.1.0-reliability-followup`. Base: `981f618`.

**Verdict: CONDITIONAL (unchanged).** The test system is stronger, but no dynamic run
happened: there is still no usable isolation, so no fresh sample was generated and no
model code was executed. This report answers the five questions with static evidence only.

## 1. Does the parser cover every generated block?

Yes. `parser_coverage.py` walks all fenced blocks in all twelve answers, records the
markdown position of each, and parses every block that is PowerShell — by language tag,
or by content when the tag is missing. It never runs the code.

| Metric | Value |
| --- | ---: |
| Answers scanned | 12 |
| Blocks found | 16 |
| PowerShell blocks | 9 |
| PowerShell blocks parsed | 9 |
| Unchecked PowerShell blocks | **0** |
| Unclosed fences | **0** |
| Answer status PASS / FAIL / N/A | 7 / 1 / 4 |
| Answer SHA-256 recorded | 12 of 12 |
| Block SHA-256 recorded | 16 of 16 |

The one FAIL is `B/SAFETY`. Its block fails on both hosts at line 1 column 11. The four
N/A answers are BAT and Python, which contain no PowerShell.

A block that is not checked, or a fence left open, forces `status != PASS`; there is no
path where missing coverage is reported as success.

## 2. Is there a cascade-counting problem?

Yes, and it is now handled. `B/SAFETY` produces **45 diagnostics per host**, but they come
from one mistake:

| Count | Value |
| --- | ---: |
| Diagnostics (5.1) | 45 |
| Independent | **1** |
| Cascade | 44 |
| Root causes | **1** (`doubled-single-quote`) |

The first diagnostic is `Unexpected token 'H:\work'''`. The rest are
`MissingEndCurlyBrace`, `MissingCatchOrFinally`, `IncompleteHashLiteral` and further
`UnexpectedToken` lines that follow from the broken quoting. Counting 45 defects would
have inflated one typo into a pattern. The classifier reports both numbers: diagnostics
for the log, root causes for the judgement.

## 3. What is the weighted token saving?

Both averages are reported because they differ.

| Scope | Arithmetic mean | Weighted (sum A − sum B) / sum A | A total | B total |
| --- | ---: | ---: | ---: | ---: |
| Three follow-up tasks (PS51, BAT, SAFETY) | 10.19% | **12.53%** | 18,056 | 15,793 |
| All six task pairs | 7.45% | **9.35%** | 31,093 | 28,187 |

Per task:

| Task | A | B | Saving |
| --- | ---: | ---: | ---: |
| PS51 | 6508 | 6321 | 2.87% |
| PS7 | 3290 | 3149 | 4.29% |
| DUAL | 3191 | 3056 | 4.23% |
| BAT | 2916 | 2755 | 5.52% |
| PYTHON | 6556 | 6189 | 5.60% |
| SAFETY | 8632 | 6717 | 22.18% |

These are tokenizer estimates over `opened_references`, not API usage. The tokenizer is
the official DeepSeek V4 offline tokenizer; its file SHA-256 is recorded in
`token-comparison.json`. API `input_tokens` is not used anywhere in this table.

## 4. Did the sessions open what the plan expected?

No, and the mismatch is concentrated in SAFETY.

| Sample | Status | Missing required | Extra | Duplicates |
| --- | --- | --- | --- | ---: |
| PS51 A / B | PASS | — | `references/execution.md` | 0 |
| PS7 A / B | PASS | — | — | 0 |
| DUAL A / B | PASS | — | — | 0 |
| BAT A / B | PASS | — | — | 0 |
| PYTHON A | PASS | — | — | 0 |
| PYTHON B | PASS | — | `references/python.md` | 0 |
| SAFETY A / B | **FAIL** | `security.md`, `troubleshooting.md` | `encoding-matrix.md`, `powershell-51.md` | 0 |

- **Read order** comes from the Codex JSONL command log, which was available for all 12
  samples. `SKILL.md` is the entry point and is reported separately, not as an extra load.
- **Duplicates**: none. No reference was read twice in any session.
- **Missing**: both SAFETY sessions skipped the two pages the plan named. A and B did the
  same thing, so this is a plan-versus-reality gap, not an A/B difference.
- **Extra**: PS51 read `execution.md` in addition to the planned page; B/PYTHON also read
  the older `python.md` before the new `python-source-encoding.md`.

Consequence: the token number that uses `loads` is measuring a routing the model did not
follow. The `opened_references` number in section 3 is the faithful one for these
sessions.

## 5. Is the system ready for a dynamic re-test?

**No — BLOCKED.** The same isolation checks as the first follow-up still fail:

| Option | State |
| --- | --- |
| Windows Sandbox | absent |
| Hyper-V | hypervisor not running |
| Docker / VirtualBox / VMware | absent |
| Codex `read-only` / `workspace-write` | every command rejected: `blocked by policy` |

No sample was generated and no model code was executed. The parser gate is ready and would
reject `B/SAFETY` before a run, but a gate is not a substitute for the run.

## Benchmark changes in this round

| Change | File |
| --- | --- |
| per-block extraction with markdown position and block SHA-256 | `scripts/parser_coverage.py` |
| PowerShell detection by tag or content | same |
| cascade / root-cause classification | same |
| `execution_allowed()` gate | same |
| arithmetic and weighted token saving | `scripts/token_comparison.py` |
| routing audit with missing, extra, order, duplicates | `scripts/routing_audit.py` |
| 20 automated tests | `tests/evals/test_real_model_ab_followup.py` |

## Test results

| Suite | Result |
| --- | --- |
| New follow-up tests | 20/20 |
| evals | see the branch CI run |
| python | see the branch CI run |
| integration | see the branch CI run |

## Artifacts

- `parser-coverage.json`
- `token-comparison.json`
- `routing-audit.json`
- `tests/evals/test_real_model_ab_followup.py`

## What is still blocked

- 10 fresh answers (SAFETY 6, BAT 2, PS51 2)
- the BAT matrix at code page 936 and 65001
- any claim about execution success or a quality PASS

Until a disposable Windows environment exists, the quality state remains CONDITIONAL and
the dynamic stage remains BLOCKED.
