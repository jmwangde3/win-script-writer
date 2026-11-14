# Status: CONDITIONAL

| Field | Value |
| --- | --- |
| Verdict | **CONDITIONAL** — no B regression; shared PS51 gap; temp-dir, not OS isolation |
| Date | 2026-11-15 |
| Branch | `test/v1.1.0-stage3` (from `175162c`) |
| Run root | `%TEMP%\wsw-v110-stage3\20261115-001546` |
| Model | `gpt-6-luna` via Codex CLI 0.167.0-alpha.3.2 |
| Samples | 10 fresh: SAFETY A3/B3, BAT A1/B1, PS51 A1/B1 |
| Execution | **10/10 started, 10/10 met the task condition** |
| Parser | 8 PASS, 2 N/A (BAT), 0 FAIL, 0 REVIEW, 0 unchecked, 0 unclassified |
| Routing | **10/10 valid** against the corrected SAFETY route |
| Safety violations | **0**; SAFETY hashes unchanged in all six runs |
| Mean score | A 95.0, B 95.0, delta 0 |
| Stage-3 token saving | arithmetic **10.19%**, token-weighted **17.25%** |
| Previous B/SAFETY parse error | **did not recur** (0 of 3) |
| Previous B/BAT missing `chcp 936` | **did not recur**; both code pages pass |
| Full report | `report.md` |

## What was done

1. **Routing root cause**: `BENCHMARK_ROUTING_DEFECT`. The SAFETY prompt is an encoding
   audit; `SKILL.md` routes it to `encoding-matrix.md` + `powershell-51.md`, which is what
   all six sessions opened. The declared `loads` (`security.md` + `troubleshooting.md`)
   was the wrong copy. Details: `routing-investigation.md`.
2. **Parser**: every fenced block plus inline command spans, per block, 5.1 and 7;
   `POWERSHELL` / `OTHER` / `UNCLASSIFIED`; an unclassified block cannot pass.
3. **Token**: three historical scopes plus a fresh ten-sample scope, arithmetic and
   weighted, tokenizer hash recorded, API usage excluded.
4. **Dynamic test**: harmless selftest first, then ten reviewed model scripts in a
   per-sample temp directory as a normal user, no policy bypass.

## Why not PASS

- Both groups score 75 on PS51 because neither answer provides a programmatic UTF-8 BOM
  write; both tell the user to use the save dialog. It is a shared gap, not a B
  regression, but it means the absolute quality bar is not met.
- One sample per BAT/PS51 side, three per SAFETY side. Screening, not proof.
- Execution containment is a temp directory plus pre-review, **not** an OS sandbox.
- Model is `gpt-6-luna`, not DeepSeek; PowerShell is 7.7, not 7.4; host ACP is 65001.

## Why not FAIL

- No B regression on any task.
- No safety violation.
- Every execution met its task condition.
- The two B failures from the previous round did not reproduce in fresh samples.

## Next step

1. Repeat BAT and PS51 with three samples per side before any release decision.
2. Decide whether the shared PS51 gap deserves a documentation example in both languages
   (a programmatic BOM write, not a save-dialog instruction).
3. Keep the parser gate; keep the corrected SAFETY route in the benchmark metadata.
4. Do not merge PR #6 on this evidence.
