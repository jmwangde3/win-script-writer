# Status: CONDITIONAL (dynamic stage blocked)

| Field | Value |
| --- | --- |
| Verdict | **CONDITIONAL** — one deterministic B parser failure, no new samples |
| Date | 2026-11-14 |
| Branch | `test/v1.1.0-reliability-followup` |
| Regenerated samples | **0 of 10** (SAFETY 6, BAT 2, PS51 2) |
| Model calls | **0** |
| Static re-check | 6 answers from the 2026-11-14 run, clearly labelled as not regenerated |
| Parser (5.1 and 7) | A 2/2 pass, B 1/2 pass |
| B parser failure | `SAFETY`: `$root = ''H:\work''`, line 1 col 11, both hosts |
| Dynamic execution | **0**, blocked: no Windows Sandbox, no hypervisor, no Docker/VM |
| Safety violations | 0 static |
| Actual-routing token saving | PS51 2.87%, BAT 5.52%, SAFETY 22.18%, mean **10.19%** |
| Full report | `followup-report.md` |

## What is done

- `Parser.ParseFile` gate added to the benchmark, for 5.1 and 7, with no execution.
- Execution status split into `attempted`, `parsed`, `execution_started`, `execution_ok`,
  `safety_violation`; the old STATUS wording that called attempts "executed" is gone.
- `planned_references` and `opened_references` are separate columns and are never
  substituted for each other.
- Skill context recomputed from the actually opened references, using the same tokenizer;
  API `input_tokens` excluded.
- Static re-check of PS51, BAT and SAFETY, with per-sample parser output in `static/`.

## What is not done

- The ten requested samples were not regenerated. Codex's Windows sandbox rejects every
  command in both `read-only` and `workspace-write`; generating fresh samples would need
  `danger-full-access`, which this task forbids.
- No script was executed. Windows Sandbox is absent, the hypervisor is off, and no
  container or VM is installed.
- The BAT matrix at code page 936 and 65001 is designed (`execution/BLOCKED.md`) but not
  observed.
- A second and third SAFETY answer per group do not exist, so recurrence is unmeasured.

## Why CONDITIONAL

The parser gate turns the previous "scan did not run" into a deterministic verdict: B's
script is syntactically invalid on both hosts, A's is not. That is a real defect. It is
also one sample, and the requested repeats could not be produced. No dynamic result
exists, so PASS is impossible; no safety violation exists, so FAIL would overstate the
evidence.
