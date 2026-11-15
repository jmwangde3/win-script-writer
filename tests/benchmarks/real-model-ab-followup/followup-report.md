# Follow-up report: v1.1.0 reliability re-check

Date: 2026-11-14. Branch: `test/v1.1.0-reliability-followup`. Base: `13063b9`.

**Verdict: CONDITIONAL.** The benchmark now refuses a script that fails the engine's own
parser before anything runs, and the existing B/SAFETY answer fails that parser on both
hosts while A passes. That is a real defect, but it is one observation: the requested
six SAFETY samples, two BAT samples and two PS51 samples could not be regenerated or
executed because this host has no usable isolation. Nothing here supports a PASS, and one
sample cannot prove a systematic regression.

## 1. Why the dynamic part stopped

| Isolation option | Result |
| --- | --- |
| Windows Sandbox | `WindowsSandbox.exe` not present |
| Hyper-V | `HypervisorPresent = False` |
| Docker / VirtualBox / VMware | not installed |
| Codex `read-only` sandbox | every command rejected: `blocked by policy` |
| Codex `workspace-write` sandbox | every command rejected: `blocked by policy` |

Only `danger-full-access` executes commands on this host. Running unreviewed model code
that way is exactly what this follow-up forbids, so no model call was made and no script
was executed. Details: `execution/BLOCKED.md`.

Consequences:

- **0** regenerated samples (requested: 10).
- **0** model calls.
- **0** dynamic execution results.
- The static analysis below re-reads the twelve answers from the 2026-11-14 run. Those are
  **not** the requested fresh samples; every row says so.

## 2. Benchmark fixes

| Fix | Where | Effect |
| --- | --- | --- |
| `Parser.ParseFile` gate | `../real-model-ab/scripts/ps_parse.py` | parses under 5.1 and 7, records line/column/message, executes nothing |
| Parse before execute | `../real-model-ab/scripts/run_checks.py` | PS51, PS7 and SAFETY now parse first; a syntax failure sets `execution_started=false` and blocks the run |
| Status fields | `run_checks.py`, `task-results.csv` | `attempted`, `parsed`, `execution_started`, `execution_ok`, `safety_violation` are separate columns |
| STATUS wording | `../real-model-ab/STATUS.md` | "attempted" and "execution started" are no longer called "successfully executed" |
| Routing fields | `run_checks.py` output, `../real-model-ab/raw/run-log.csv` | `planned_references` and `opened_references` are carried separately and never substituted for each other |
| Token method | `scripts/token_actual.py` | context recomputed from the references a session actually opened, not from the plan; API input tokens are explicitly excluded |

## 3. Static re-check of PS51, BAT and SAFETY

Source: `../real-model-ab/raw/{A,B}/{ps51,bat,safety}.md`. Per-sample evidence:
`static/{A,B}/{task}.json`, summary: `followup-results.csv`.

| Task | Group | Parser 5.1 | Parser 7 | Execution started | Finding |
| --- | --- | --- | --- | --- | --- |
| PS51 | A | pass | pass | no (blocked) | gives a `UTF8Encoding($true)` write command |
| PS51 | B | pass | pass | no (blocked) | tells the user to save with the dialog; no programmatic write |
| BAT | A | n/a | n/a | no (blocked) | `chcp 936`, GBK, no BOM |
| BAT | B | n/a | n/a | no (blocked) | **no `chcp 936`**, GBK, no BOM |
| SAFETY | A | pass | pass | no (blocked) | scan would run |
| SAFETY | B | **fail** | **fail** | no (blocked) | `$root = ''H:\work''` |

The B/SAFETY parser error, verbatim:

```
line 1 col 11: Unexpected token 'H:\work''' in expression or statement.
line 7 col 20: Unexpected token '无法枚举' in expression or statement.
```

Both hosts agree. The second error follows from the same doubled-quote mistake later in
the script. A has no parse error.

Safety scan: no destructive or policy-changing command in any of the six answers, so no
static safety violation.

## 4. Token recomputation on actual routing

Method: metadata + `SKILL.md` body + the files listed in `opened_references` for that
session, counted with the official DeepSeek V4 offline tokenizer. This is still a
tokenizer estimate, but of the files the session touched. API `input_tokens` is not used.

| Task | A tokens | B tokens | Saving |
| --- | ---: | ---: | ---: |
| PS51 | 6508 | 6321 | **2.87%** |
| BAT | 2916 | 2755 | **5.52%** |
| SAFETY | 8632 | 6717 | **22.18%** |
| Mean (3 tasks) | — | — | **10.19%** |

For comparison, the declared-plan estimate in `../results/` is 15.5% mean over 20 tasks.
The two numbers answer different questions: one is a plan, the other is what these six
sessions actually opened. Do not substitute one for the other.

Per-sample detail, including the opened file list, is in `followup-token.json`.

**The plan and the sessions disagree, and that matters.** For SAFETY the declared routing
is `security.md` + `troubleshooting.md`, but both sessions actually opened
`encoding-matrix.md` + `powershell-51.md`. For PS51 the plan names one page and the
sessions opened two (`powershell-51.md` + `execution.md`). A benchmark that counts the
plan is therefore measuring a routing decision the model did not make. The numbers above
use what the sessions opened; the 15.5% figure in `../results/` still uses the plan. Both
are labelled; neither is presented as the other.

## 5. What the data does and does not say

**Does not say:** that v1.1.0 causes a systematic quality regression. The only new
quality signal is one deterministic parse failure in one B answer. It was already present
in the previous run; it did not recur in a new sample because no new sample exists.

**Does say:** the failure is not a flaky execution artefact. Both PowerShell hosts reject
the file before a single line runs, and a parser gate would have caught it at build time.
For a documentation-first skill, that is the kind of defect the pipeline must catch
mechanically.

**Does not say:** that the English documents caused the mistake. Neither snapshot contains
`''H:\work''`; the doubled quotes are the model's own formatting error. Whether English
wording makes that error more likely is untested.

**Does say:** B still saves context on the files a session actually opens, including the
SAFETY task where it opened the same two references as A and used 22% fewer tokens.

## 6. The four questions

**Is there a systematic quality regression?**
Not proven. One deterministic B failure, zero new repetitions. The result is a warning,
not a trend.

**Is it worth keeping the English skill?**
Keep it, do not ship it yet. The context saving is real on both the plan and the opened
files; the quality evidence is thinner and contains one hard failure. The right next step
is a repair and a repeat, not a revert.

**Is syntax-check capability needed?**
Yes, and it is now implemented. `Parser.ParseFile` on 5.1 and 7 catches this class of
failure without executing anything, and it belongs in the gate before any dynamic run.

**Can the 22-sample full test start?**
No. Three blockers: no isolation for execution, no way to generate fresh samples without
`danger-full-access`, and the 22-sample blind run is partially unblinded because six of
its answers are published in `../real-model-ab/raw/`.

## 7. Artifacts

| File | Content |
| --- | --- |
| `followup-results.csv` | six static rows: task, group, parsed, execution flags, routing, blocked reason |
| `followup-summary.json` | counts, isolation checks, parser totals, verdict |
| `followup-token.json` | per-sample actual-routing context and per-task savings |
| `static/{A,B}/<task>.json` | parser output and static facts per sample |
| `execution/BLOCKED.md` | isolation matrix and BAT code-page test design |
| `scripts/static_checks.py` | produces the results above |
| `scripts/token_actual.py` | produces the token numbers above |

## 8. Next step

1. Provision a disposable Windows environment (Windows Sandbox enabled, or a Hyper-V VM).
2. Regenerate the ten samples there, with the same prompts and model, and run the BAT
   matrix at 936 and 65001.
3. Re-run the parser gate on all ten before execution; it should reject B/SAFETY again if
   the defect is systematic.
4. Only then decide whether the 22-sample run is worth restarting, and regenerate the six
   published samples first.
