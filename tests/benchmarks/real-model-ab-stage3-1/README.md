# Stage 3.1: benchmark closeout and PS51

Branch: `test/v1.1.0-stage3-closeout`, based on `652afc6`.

This round closes three loose ends from stage 3:

1. the benchmark declared the wrong route for SAFETY;
2. BAT and PS51 had one sample per side;
3. PS51 scored 75/100 in both groups for the same reason.

It does **not** rewrite the skill, the parser or the test framework.

## What changed

| Item | Result |
| --- | --- |
| SAFETY route | `tool-02` now loads `encoding-matrix.md` + `powershell-51.md`; `SKILL.md` untouched |
| Metadata test | `tests/evals/test_stage31_metadata.py`, 5 tests |
| BAT samples | 3 per side (1 existing + 2 new pairs) |
| PS51 samples | 3 per side (1 existing + 2 new pairs) |
| PS51 write test | programmatic UTF-8 BOM write verified on 5.1 and 7.7 |
| Formal Skill | **not modified** |

## PS51 decision

`references/powershell-51.md` already contains the `WriteAllText` + `UTF8Encoding`
pattern, and `SKILL.md` rule 1 states the BOM requirement. Both model answers chose a
manual save dialog anyway. That is a model behaviour gap, not a missing document step, so
the Skill is unchanged. The independent write test proves the method works with a Chinese
path on both hosts. A dedicated task with explicit "write it automatically" wording is the
recommended next step, not a document edit. Details: `ps51-investigation.md`.

## Layout

| Path | Content |
| --- | --- |
| `routing-fix.json` | before/after and evidence for the SAFETY route |
| `ps51-investigation.md` | prompt, rubric, deduction, decision |
| `ps51-write-test.json` | 5.1 / 7.7 BOM write evidence |
| `parser-coverage.json` | per-block results for the eight new answers |
| `token-comparison.json` | PS51/BAT/SAFETY token views |
| `task-results.csv`, `summary.json` | merged BAT/PS51 rows and the aggregate |
| `report.md` | the reading and the verdict |
| `raw/A`, `raw/B` | new answers, unedited |
| `execution/A`, `execution/B` | per-sample parse, run and byte evidence |
| `logs/` | selftest and command logs |
| `scripts/` | bundle builder, write test, assembler |

## Reproduce

```bash
python tests/benchmarks/real-model-ab-stage3-1/scripts/make_bundle.py --root <root>
python tests/benchmarks/real-model-ab-stage3-1/scripts/ps51_write_test.py
# generate the eight answers, then run the stage-3 checker on the new root
python tests/benchmarks/real-model-ab-stage3-1/scripts/assemble.py
```
