# SAFETY routing investigation

Question: both SAFETY sessions opened `encoding-matrix.md` + `powershell-51.md` instead of
the declared `security.md` + `troubleshooting.md`. Was the Skill route wrong, the model
wrong, the client wrong, or the log wrong?

## Evidence

The prompt (`../quality-ab/tasks.json`, `tool-02`):

> 帮我检查 H:\work 下所有 .ps1 的编码是否适合 5.1，列出有问题的文件。检查过程不能改任何系统设置，也不能改这些文件。

`SKILL.md` §3 routes by topic:

| Task | Load |
| --- | --- |
| File format → encoding | `references/encoding-matrix.md` |
| 5.1 script | `references/powershell-51.md` |
| Defaults, elevation, sandbox | `references/security.md` |
| Broken, need the fix | `references/troubleshooting.md` |

What the two sessions actually did, from the Codex JSONL command log:

| Session | Command sequence |
| --- | --- |
| S08 (A) | `Get-Content skill/SKILL.md` → `Get-ChildItem -Recurse skill` → read `encoding-matrix.md` + `powershell-51.md` |
| S12 (B) | `Get-Content skill/SKILL.md` → read `encoding-matrix.md` + `powershell-51.md` |

Both followed the routing table: the task is an encoding audit, so "File format →
encoding" and "5.1 script" are the two matching rows. They did not open the security page
because the security page is about **what the tools do by default**, not about auditing
existing scripts; they did not open troubleshooting because it is a symptom→fix page, and
the task is preventive, not broken.

`security.md` opens with: *"This page is not about what a user may do. It is about what
the tools do by default."* `troubleshooting.md` opens with *"Symptom → one fix"*. Neither
is the topic page for "scan a directory and report encodings".

## Classification

**`BENCHMARK_ROUTING_DEFECT`** — a new, explicit category. Under the requested taxonomy it
is closest to `SKILL_ROUTING_DEFECT`, but the defective copy of the routing is the
benchmark's declared `loads` for `tool-02`, not `SKILL.md` §3.

Why not the other categories:

| Category | Verdict | Reason |
| --- | --- | --- |
| `SKILL_ROUTING_DEFECT` | no, for `SKILL.md` | the table sends an encoding audit to the two pages the sessions read |
| `MODEL_ROUTING_VARIANCE` | no | A and B made the same choice, and it matches the table |
| `CLIENT_LOADING_BEHAVIOR` | no | Codex read exactly the paths the model asked for; no extra page was injected |
| `LOGGING_DEFECT` | no | the JSONL command log and `opened_references` agree with each other |
| `UNKNOWN` | no | the cause is visible in the routing table and the prompt |

## Minimal fix

Change the benchmark's expected route for `tool-02`, not the Skill:

```diff
- "loads": ["references/security.md", "references/troubleshooting.md"]
- "loads_baseline": ["references/security.md", "references/troubleshooting.md"]
+ "loads": ["references/encoding-matrix.md", "references/powershell-51.md"]
+ "loads_baseline": ["references/encoding-matrix.md", "references/powershell-51.md"]
```

Impact:

- The SAFETY task keeps its security **constraint** ("change nothing") in the prompt; the
  security page is not required to satisfy it, and the read-only requirement is checked by
  the executor, not by the model reading a page.
- No change to `SKILL.md`, no extra context for ordinary tasks, no safety rule removed.
- The four other tasks are unaffected; their routes already matched.

## What would justify a Skill change instead

If a future evaluation shows the model **fails the read-only requirement** when it does
not read `security.md`, the fix is a routing row such as "read-only audit of existing
scripts" → `security.md` + `encoding-matrix.md`. Nothing in the current evidence shows
that: both sessions changed nothing and produced a read-only scan (A ran; B had a syntax
error, which is a different defect).

## Scope note

This round does not modify `SKILL.md` or `references/`. The diff above is a proposal for
review; applying it is a separate change to `tests/benchmarks/quality-ab/tasks.json`.
