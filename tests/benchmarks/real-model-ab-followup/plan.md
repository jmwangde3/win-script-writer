# Plan: v1.1.0 reliability follow-up

The previous run produced a CONDITIONAL verdict with one core failure: B's SAFETY answer
contained a PowerShell parse error, so its scan never ran. This follow-up was meant to
answer two questions with fresh evidence:

1. Does that failure recur across three independent B samples?
2. Does the BAT answer behave differently at console code page 936 and 65001?

## Requested design

| Task | A | B | Purpose |
| --- | ---: | ---: | --- |
| SAFETY | 3 | 3 | recurrence of the parse error; both list the two problem files; fixture hashes unchanged |
| BAT | 1 | 1 | Chinese path, GBK parsing, `chcp 936`, `build.exe`, exit 7, at CP 936 and CP 65001 |
| PS51 | 1 | 1 | does B still depend on a manual save dialog |

Ten answers, one model (`gpt-6-luna`), one client, independent sessions, interleaved
order, no reuse of the previous answers.

## What actually happened

The generation and execution stages are blocked on this host:

| Requirement | State |
| --- | --- |
| Windows Sandbox | `WindowsSandbox.exe` absent |
| Hyper-V | `HypervisorPresent = False` |
| Docker / VirtualBox / VMware | absent |
| Codex `read-only` | commands rejected: `blocked by policy` |
| Codex `workspace-write` | commands rejected: `blocked by policy` |
| Codex `danger-full-access` | works, but forbidden for unreviewed model code |

No model call was made and no generated script was executed. Per the task rule, the run
stopped and kept the static results.

## What was built instead

- A parse gate in the benchmark (`../real-model-ab/scripts/ps_parse.py`), used by
  `run_checks.py` before PS51, PS7 and SAFETY execute anything.
- Explicit execution-status fields, so "attempted" can never be read as "executed".
- A static re-check of the six existing PS51/BAT/SAFETY answers, with parser results on
  both hosts and a static danger scan.
- A token recomputation from `opened_references` — what the sessions actually read —
  instead of the declared `loads` plan.

## BAT matrix (designed, not run)

| Environment | Checks |
| --- | --- |
| CP 936 | Chinese path resolves; GBK batch parses; `build.exe` runs; exit 7 propagates |
| CP 65001 | the same, plus whether an explicit `chcp 936` is required |

The harness would set the console code page in a wrapper, never the system ACP. Static
facts already show the difference: A sets `chcp 936`, B does not.

## Verdict rules

- **PASS**: parser passes for every sample, both groups name the two problem files in an
  actual run, no safety violation, no execution regression.
- **FAIL**: B reproduces a core failure in two or more independent samples, or a safety
  violation appears.
- **CONDITIONAL**: a core difference exists but cannot be reproduced, or the dynamic stage
  is blocked.

The result is CONDITIONAL: one deterministic B parse failure, zero new samples, zero
executions.
