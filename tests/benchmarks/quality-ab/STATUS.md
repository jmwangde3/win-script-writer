# Status: PENDING

| Field | Value |
| --- | --- |
| Quality state | **PENDING** — 0 answers, 0 scores, nothing claimed |
| Toolchain state | **READY** — builds, refusal paths and blind separation tested |
| Date written | 2026-11-14 |
| Plan | `plan.md` |
| Task set | `tasks.json` (11 tasks, 8 areas) |
| Samples per run | 22 — 11 tasks × 2 groups |
| Bundle builder | `prepare.py` |
| Scoring packet | `make_scoring_packet.py` |
| Unblinding | `unseal.py` |
| Answers generated | 0 of 22 |
| Samples scored | 0 of 22 |
| Target model | not selected — no callable model in this environment |
| CI | the toolchain's own tests run in the `docs contract` job |

## Why it is not run

The two things this plan needs are a pinned target model and a client that gives one
isolated session per sample. Neither exists in the environment that produced this release:
the work was done with a local toolchain (tokenizer, Pester, PSScriptAnalyzer, Python
unittest) and no model endpoint is configured. A run started here would have to invent
either the answers or the token counts, which is exactly what the rest of
`tests/benchmarks/` refuses to do.

So the honest state is: **toolchain READY, quality PENDING, gate `CONDITIONAL`.** A ready
toolchain is not a quality result.

## What is verified, without a model

These were run and are reproducible:

- `prepare.py --dry-run` validates both snapshots, prints 22 task ids and sample numbers,
  and prints **no group and no random seed**. With an explicit `--seed` the order is
  reproducible; the production path uses a secure random seed stored only in
  `manifest.json`.
- A full build produces 22 samples: **12 documentation files for group A, 14 for group B**
  (`CHANGELOG.md` is excluded from both), plus `PROMPT.md`, `run-log.csv` and
  `answer.md` per sample, `manifest.json` with a SHA-256 per input and output file, and
  `SEALED-mapping.json`.
- Every task's `loads` / `loads_baseline` resolves to a file that exists in the matching
  snapshot; `bash-01` is present and its prompt, checks and forbidden actions match
  `../tasks.json` verbatim.
- `PROMPT.md` for the two samples of one task is byte-identical, contains no sample id and
  no group, and asks the model for `answer.md` only.
- `run-log.csv` ships with 19 columns, `sample_id` pre-filled per sample and every token
  column empty. The builder has no tokenizer and no estimate path.
- The builder refuses a non-empty target, refuses a path inside the repository, never
  deletes an existing file, and leaves nothing behind when a snapshot is incomplete or a
  copied file's hash does not match.
- `make_scoring_packet.py` refuses an unfinished run, renumbers the answers `R001..R022`,
  and writes a packet with no group, sample id, task id, seed, manifest, skill document or
  run log. `SCORER-KEY.json` is written outside the packet.
- `unseal.py` refuses a missing, blank, duplicated or out-of-range score, restores the
  groups correctly from the key, and reports a reviewer disagreement over 10 points.

## What has to happen for this to become a result

1. Pick the model and pin it (`plan.md` → Fairness rules 1), plus a client that can keep
   one session and one directory per sample.
2. Build the bundle, run 22 isolated sessions, then have the executor fill 22 log rows.
3. Build the packet, score blind with two reviewers, then unseal.
4. Run the Windows execution verification on the answers that will be quoted. A score is
   not an execution result.
5. Replace this table with the per-group means and the delta, and attach the report. If a
   dimension regresses, say so there rather than in a footnote.

Until all five are done, this file stays `PENDING` and no summary anywhere in the
repository may describe the quality of v1.1.0 as validated.
