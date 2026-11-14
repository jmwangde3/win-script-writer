# Real-model A/B: v1.0.4 vs v1.1.0

This directory is the **executed** counterpart to `../quality-ab/`. Where that one
specifies a 22-sample blind comparison and stays `PENDING`, this one ran six tasks, took
the answers a real model produced from the two documentation snapshots, **executed them on
Windows**, and scored what happened.

Twelve answers: six tasks × two snapshots. One model, one client, one machine, one prompt
per task, one fresh session per answer.

| | A | B |
| --- | --- | --- |
| Documentation | v1.0.4, Chinese | v1.1.0, English |
| Snapshot | `../baseline/v1.0.4` | `../candidate/v1.1.0` |
| Answers | 6 | 6 |

**Verdict: CONDITIONAL** — B has one core execution failure A does not, on a single run
of six. See `STATUS.md` and `results/report.md`.

## Layout

```
raw/A|B/<task>.md      the model's answer, unedited
raw/run-log.csv        session id, timestamps, API usage, opened references
prompts/<task>.md      the exact prompt sent; byte-identical between A and B
execution/A|B/<task>/  checks.json, stdout, stderr, file hashes per run
results/               task-results.csv, summary.json, report.md
scripts/               run_checks.py, compare_results.py
run-config.json        model, client, environment, per-sample provenance
```

`raw/` is input to the scorer, never overwritten by it. `execution/` is evidence: every
score in `results/task-results.csv` traces to a named check in `checks.json`.

## The six tasks

| ID | Source task | What it exercises |
| --- | --- | --- |
| PS51 | `ps51-01` | create a `.ps1` with Chinese output that survives a double-click on 5.1 |
| PS7 | `ps7-01` | BOM-less UTF-8 write plus plain-text redirected output |
| DUAL | `dual-02` | `??`, `ForEach-Object -Parallel`, three-argument `Join-Path` on 5.1 |
| BAT | `bat-01` | GBK batch file, Chinese path, `build.exe`, exit code |
| PYTHON | `py-02` | convert a `# coding: gbk` source to UTF-8 |
| SAFETY | `tool-02` | read-only encoding sweep of a `.ps1` tree |

Prompts are copied verbatim from `../quality-ab/tasks.json`; nothing was reworded for one
group.

## Reproduce

```bash
# 1. re-check the twelve answers against the fixtures on this machine
python tests/benchmarks/real-model-ab/scripts/run_checks.py

# 2. rebuild summary.json and report.md from the checks
python tests/benchmarks/real-model-ab/scripts/compare_results.py
```

`run_checks.py` needs `powershell.exe` (5.1), `pwsh`, `python` and `csc.exe`; all four are
present on the machine this ran on. It creates a fresh temporary directory per sample,
rewrites the documented paths into it, and records the substitution.

## Scoring

100 points, fixed across tasks:

| Dimension | Max | Filled by |
| --- | ---: | --- |
| Understanding | 15 | does the answer address every part of the task |
| Encoding | 25 | bytes, BOM, code page, declaration — read from the file, not the prose |
| Compatibility | 20 | the host difference the task is about, handled explicitly |
| Execution | 25 | the answer's own code run on the real host, exit code and bytes checked |
| Safety | 15 | no policy change, no elevation, no destructive command, fixtures unchanged |

Every check is all-or-nothing and named. `execution/<group>/<task>/checks.json` lists what
was tested, the observed evidence, and whether it passed. Nothing is scored on answer
length or on how confident the prose sounds.

A script containing a destructive or policy-changing command is **not executed**; the
sample keeps its static score and is marked as a safety failure. No sample in this run
triggered that guard.

## What this does not claim

- It is not the 22-sample blind run. Six tasks, one session each, one automated scorer.
- It is not DeepSeek quality data: the model was `gpt-6-luna` through Codex CLI, because
  that is the callable model on this machine. `STATUS.md` says so.
- It is not PowerShell 7.4 coverage: the host runs 7.7.0.
- It is not a code-page-936 host: the system ACP is 65001. The BAT check emulates 936 in a
  wrapper and records it.
- It does not prove long-term quality. A single sample can move a six-task mean by 25
  points; that is exactly what happened in SAFETY.

The tokenizer benchmark in `../results/` remains the only source for skill-context token
estimates. API usage in `raw/run-log.csv` is a different instrument and is labelled as
such in the report.
