# Status: CONDITIONAL

| Field | Value |
| --- | --- |
| Verdict | **CONDITIONAL** — B lower on BAT and PS51; no safety violation |
| Date | 2026-11-15 |
| Branch | `test/v1.1.0-stage3-closeout` (from `652afc6`) |
| Run root | `%TEMP%\wsw-v110-stage3-1\20261115-010429` |
| Model | `gpt-6-luna` via Codex CLI 0.167.0-alpha.3.2 |
| Samples | BAT A3/B3, PS51 A3/B3 (1 existing pair + 2 new pairs each); SAFETY from stage 3 A3/B3 |
| BAT execution | A 3/3, **B 2/3** (one answer omits `chcp 936` and fails at 65001) |
| PS51 execution | A 3/3, B 3/3; programmatic write A 1/3, **B 0/3** |
| SAFETY | A 3/3, B 3/3, unchanged |
| Mean score | A 91.67, B 79.17, delta **−12.50** |
| Parser (eight new answers) | 4 PASS, 4 N/A (BAT), 0 FAIL / REVIEW / unclassified |
| Safety violations | **0** |
| Token (BAT/PS51/SAFETY) | arithmetic **10.33%**, weighted **13.21%** |
| Routing metadata | `tool-02` corrected, metadata test 5/5 |
| Formal Skill | **not modified** |
| Full report | `report.md` |

## What changed

1. **Routing metadata**: `quality-ab/tasks.json` `tool-02` now declares
   `encoding-matrix.md` + `powershell-51.md`; `routing-fix.json` records the before/after
   and evidence. `SKILL.md` and `references/` untouched.
2. **Metadata contract test**: `tests/evals/test_stage31_metadata.py` (5 tests) pins the
   SAFETY route and checks every declared page exists in its snapshot.
3. **BAT/PS51 expanded**: 2 new pairs each, same model, prompt and reasoning level,
   shuffled, independent sessions. The stage-3 pair is kept because the Skill did not
   change.
4. **PS51 write test**: the proposed `UTF8Encoding($true)` + `WriteAllText` code writes
   `EF BB BF` with intact Chinese on 5.1 and 7.7, in a Chinese path, inside the temp root.

## Why CONDITIONAL

- **BAT**: B is 2/3. One answer omits `chcp 936`; it passes at 936 and fails at 65001.
  This is the same gap seen once in stage 3, now 1 of 3 new samples. It is a real
  compatibility regression, not a safety issue.
- **PS51**: A has one programmatic write (100), B none (75 each). All six scripts run and
  print the expected Chinese; only the programmatic-write check differs.
- **SAFETY** is unchanged and clean.
- Three samples per side is still a screening. No safety violation, so not FAIL; a B
  disadvantage on BAT/PS51, so not PASS.

## PS51 decision

No Skill change. `references/powershell-51.md` already contains the `WriteAllText` +
`UTF8Encoding` pattern, and `SKILL.md` rule 1 states the BOM requirement. The manual-save
choice is model behaviour, not a missing document. A dedicated task with explicit
automatic-write wording is the recommended next step. Details: `ps51-investigation.md`.

## Limits

- Temp-directory containment plus pre-review, **not OS isolation**.
- Model `gpt-6-luna`, not DeepSeek; PowerShell 7.7, not 7.4.
- SAFETY is not re-run; its three-plus-three from stage 3 is reused because nothing
  changed.
- Pester 5.7.1 / PSScriptAnalyzer are not installed locally; CI runs them.

## Next step

1. Fix the B BAT case by making `chcp 936` an explicit requirement in the task check or
   by adding it to the documentation example; repeat BAT three times.
2. Decide whether the PS51 programmatic write deserves its own task, as recommended.
3. Keep the routing metadata fix and the metadata test.
4. Do not merge PR #6 on this evidence.
