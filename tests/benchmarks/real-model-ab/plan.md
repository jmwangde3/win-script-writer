# Plan: six-task real-model A/B with executed answers

Status: **executed, verdict CONDITIONAL**. Results: `results/report.md`.

## Objective

Answer one question with evidence rather than prose: did v1.1.0 keep the quality of the
answers while cutting the skill context? The answer is produced by a real model from a
given documentation snapshot, then **executed** on Windows, so the score rests on bytes
and exit codes.

This is a screening run, not the 22-sample blind comparison in `../quality-ab/`. That
toolchain stays as it is, `PENDING`, for a larger run.

## Task selection

Six tasks, one per category the release touches, all taken from
`../quality-ab/tasks.json` without rewording:

| ID | Source | Why this one |
| --- | --- | --- |
| PS51 | `ps51-01` | the only 5.1 task that both writes the file and must survive a double-click |
| PS7 | `ps7-01` | covers the BOM-less write and the redirect/colour behaviour in one script |
| DUAL | `dual-02` | three constructs with objectively checkable error classes |
| BAT | `bat-01` | GBK save, code page, Chinese path, exit code |
| PYTHON | `py-02` | byte conversion plus declaration rewrite |
| SAFETY | `tool-02` | read-only requirement is testable by hashing the fixtures |

`py-02` covers the GBK declaration and the UTF-8 conversion. The GB2312-subset trap lives
in `py-03`, which is not part of this six; that is a known gap, recorded in STATUS.

## Model and client

| Field | Value |
| --- | --- |
| Model | `gpt-6-luna` (GPT-6-Luna) |
| Version | not exposed by Codex CLI |
| Client | Codex CLI 0.167.0-alpha.3.2, bundled with the desktop install |
| Auth | ChatGPT session |
| Temperature / top_p / max output / seed | not exposed by the client |
| Reasoning effort | CLI default (medium) |

Both groups use the same binary, the same auth, the same invocation and the same machine.
No model change occurred during the run.

## Isolation

Each sample is a separate `codex exec` process:

```
CODEX_HOME=<empty dir with credentials only>   # no AGENTS.md, no memory, no config
codex exec --ephemeral --json --skip-git-repo-check --ignore-user-config \
           -C <run>/S## -s danger-full-access -m gpt-6-luna -
```

- `PROMPT.md` on stdin, byte-identical for the two samples of a task (SHA-256 in
  `run-config.json`).
- `-C` is the sample directory; only that directory contains a `skill/` tree, and A and B
  receive different snapshots.
- `CHANGELOG.md` is in neither sample.
- `--ephemeral` leaves no session file, so nothing carries over to the next answer.
- The answer is the only thing the model writes.

The host's Codex Windows sandbox (`workspace-write`) rejected every command, so the run
used `danger-full-access`. Read isolation is therefore **prompt-enforced and audited after
the fact** from the JSONL command log: any command touching the repository, the run
bundle, the installed skill copies or the network marks the sample as a scope violation.
All twelve audits came back clean.

## Order

The answers come from the 22-sample bundle `prepare.py` built, whose sample order is a
shuffled permutation. Nine answers existed from an interrupted batch; the six A/B sides
that were still missing were run in sample-id order, which the seed had already
randomised. No task was hand-placed next to its counterpart.

## Execution design

One temporary directory per (task, group). The model's documented path is rewritten into
it and the substitution is recorded in `checks.json`.

| Task | Fixture | Run |
| --- | --- | --- |
| PS51 | `<tmp>\部署\` | the answer's creation command, then `deploy.ps1` under 5.1 with empty stdin for `Read-Host` |
| PS7 | `<tmp>\` | the answer's script under 7.7; every new `.txt` is byte-checked |
| DUAL | three probe scripts | each construct under 5.1 and 7.7; observed error class compared to the answer's claim |
| BAT | `<tmp>\工作\发布\` with a compiled `build.exe` returning 7 | `cmd /c` a wrapper that sets code page 936 and `call`s the answer's batch file |
| PYTHON | GBK `old.py` / `legacy.py` | the answer's converter, then `py_compile` |
| SAFETY | `<tmp>\work\` with five `.ps1` files of known encodings | the answer's scan under 5.1; fixture hashes compared before and after |

Two harness decisions are recorded because they change what "pass" means:

1. **BAT line endings are normalised to CRLF.** Markdown blocks are LF; `cmd`'s `call`
   misparses an LF-only batch file, while direct execution happens to work. A Windows
   editor would save CRLF, so the harness does the same.
2. **The BAT child runs with console code page 936.** The host ACP is 65001, not the
   skill's target. A wrapper sets 936 before calling the answer's file. A missing
   `chcp 936` in the answer is still penalised by a static check, but does not by itself
   fail execution.

A script containing `Remove-Item` on an absolute path, a registry write, a policy change,
a network call or elevation is not executed at all; it keeps its static score and is
marked as a safety failure.

## Scoring

100 points: understanding 15, encoding 25, compatibility 20, execution 25, safety 15.
Each dimension is filled by named all-or-nothing checks; the mapping is in
`scripts/run_checks.py` and the result is in `checks.json` per sample.

The scoring is automated and single-reviewer. That is stated rather than dressed up as a
two-reviewer blind review.

## Deviations from the original 22-sample plan

- 6 tasks, not 11; 12 answers, not 22.
- One session per sample, not three repetitions.
- The model is the one callable on this machine, not a DeepSeek endpoint. It is recorded
  by exact id, but no server version is exposed.
- The automated scorer replaces the human 100-point blind review for this screening run.
  It cannot judge "is this explanation clear", only whether the answer does the job.
- Six of the twelve answers are reused from the interrupted 22-sample batch. Publishing
  them here reveals their group membership, so that batch is no longer blind for those six
  samples. Regenerate them if the 22-sample run is resumed.
