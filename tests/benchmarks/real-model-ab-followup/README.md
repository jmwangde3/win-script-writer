# Real-model A/B follow-up

This directory answers the reliability questions left open by `../real-model-ab/`:

- does B's SAFETY parse error recur across fresh samples?
- how does the BAT answer behave at console code page 936 and 65001?
- does B still depend on a manual save dialog for PS51?
- what does the skill context cost when measured against the references a session
  actually opened, not the ones a plan declared?

**Status: CONDITIONAL.** The dynamic half is blocked on this host — no Windows Sandbox, no
hypervisor, no container or VM, and Codex's own sandbox rejects every command. Generating
or executing unreviewed model code would require `danger-full-access`, which this follow-up
forbids. See `execution/BLOCKED.md` and `followup-report.md`.

## What is in here

| Path | Content |
| --- | --- |
| `followup-report.md` | the full reading: findings, numbers, limits, verdict |
| `followup-results.csv` | six static rows: parser, execution flags, routing, blocked reason |
| `followup-summary.json` | counts, isolation checks, parser totals |
| `followup-token.json` | per-sample context from `opened_references` and per-task savings |
| `static/{A,B}/<task>.json` | parser output (5.1 and 7) and static facts per sample |
| `static/{A,B}/<task>.ps1` | the extracted script that was parsed (never executed) |
| `execution/BLOCKED.md` | isolation matrix and the BAT code-page test design |
| `scripts/static_checks.py` | produces the static results |
| `scripts/token_actual.py` | produces the token numbers |
| `prompts/` | the three prompts, copied unchanged from the previous run |

The six analysed answers come from `../real-model-ab/raw/`. They are **not** regenerated
samples; the requested ten fresh answers could not be produced.

## Reproduce

```bash
python tests/benchmarks/real-model-ab-followup/scripts/static_checks.py
python tests/benchmarks/real-model-ab-followup/scripts/token_actual.py
```

The first needs `powershell.exe` and `pwsh` (both present); it parses, never executes. The
second needs the official DeepSeek V4 tokenizer, found through the same lookup as
`../compute.py`.

## Key numbers

| Check | A | B |
| --- | --- | --- |
| Parser 5.1 / 7 on PS51 + SAFETY | 2/2 pass | 1/2 pass |
| SAFETY parse error | none | line 1 col 11, both hosts |
| `chcp 936` in the batch | yes | no |
| Programmatic UTF-8 BOM write in PS51 | yes | no |

| Task | Context A | Context B | Saving |
| --- | ---: | ---: | ---: |
| PS51 | 6508 | 6321 | 2.87% |
| BAT | 2916 | 2755 | 5.52% |
| SAFETY | 8632 | 6717 | 22.18% |
| Mean | — | — | **10.19%** |

Context is metadata + `SKILL.md` body + the references the session actually opened, under
the same tokenizer. It is not API usage.
