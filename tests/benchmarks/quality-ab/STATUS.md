# Status: PENDING

| Field | Value |
| --- | --- |
| State | **PENDING** — not run, not scored, not claimed |
| Date written | 2026-11-14 |
| Plan | `plan.md` |
| Task set | `tasks.json` (10 tasks, 7 areas) |
| Bundle builder | `prepare.py` (buildable, verified) |
| Answers generated | 0 of 20 |
| Samples scored | 0 of 20 |
| Target model | not selected — no callable model in this environment |

## Why it is not run

The two things this plan needs are a pinned target model and a client that gives one
isolated session per sample. Neither exists in the environment that produced this release:
the work was done with a local toolchain (tokenizer, Pester, PSScriptAnalyzer, Python
unittest) and no model endpoint is configured. A run started here would have to invent
either the answers or the token counts, which is exactly what the rest of
`tests/benchmarks/` refuses to do.

So the honest state is: **specified, buildable, unexecuted.** The quality gate for v1.1.0
is `CONDITIONAL` on this file, not `PASS`.

## What is already verified

These were run, and they are reproducible without a model:

- `prepare.py --dry-run` assigns 20 blind ids over 10 tasks × 2 snapshots, deterministic
  for a fixed `--seed` (two dry runs with seed 20261114 print the same order).
- A full build copies the documentation only — **12 files for group A, 14 for group B**
  (the two new pages are the intended difference; `CHANGELOG.md` is excluded from both so
  version history is not the thing being read) — and writes `PROMPT.md`, `run-log.csv`,
  an empty `answer.md`, `manifest.json` with a SHA-256 per input file, and
  `scoring-sheet.md` with the rubric and the pass conditions.
- The task set covers all seven areas the release touches (`tasks.json` → `coverage`).
- Both snapshots resolve; every sample build was verified by counting the copied `.md`
  files (12 / 14 as above, no stray files).

## What has to happen for this to become READY

1. Pick the model and pin it (`plan.md` → Fairness rules 1).
2. Build the bundle, run 20 isolated sessions, fill 20 log lines.
3. Score blind, then unblind with `SEALED-mapping.json`.
4. Replace this table with the per-group means and the delta, and attach the scoring
   sheet. If a dimension regresses, say so there rather than in a footnote.

Until all four are done, this file stays `PENDING` and no summary anywhere in the
repository may describe the quality of v1.1.0 as validated.
