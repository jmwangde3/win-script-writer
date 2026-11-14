# Model quality A/B: v1.0.4 vs v1.1.0

Status: **PENDING** — see `STATUS.md`. Nothing in this directory is a result.

The context benchmark (`../README.md`) measures how many tokens the skill costs. It says
nothing about whether the answers get better or worse. This plan measures that, with a
real model, on ten tasks, under conditions that make the comparison fair.

## What is being compared

| Group | Documentation | Snapshot |
| --- | --- | --- |
| A | v1.0.4, Chinese | `../baseline/v1.0.4` — `SKILL.md`, `README.md`, 10 references |
| B | v1.1.0, English | `../candidate/v1.1.0` — `SKILL.md`, `README.md`, 12 references |

`CHANGELOG.md` is excluded from both bundles: it is release history, not documentation a
model needs to answer, and it names the version. Excluding it in both groups keeps the
only difference between them the one being measured.

Only the documentation differs. Same prompts, same model, same client, same machine, same
answer language.

The ten tasks live in `tasks.json`, chosen from `../tasks.json` so that every area the
release touches is represented:

| Area | Tasks | Why these |
| --- | --- | --- |
| Windows PowerShell 5.1 | `ps51-01`, `ps51-04` | one writes bytes, one repairs a stream a downstream reader cannot decode |
| PowerShell 7 | `ps7-01`, `ps7-03` | BOM-less write plus output rendering; then a 5.1-vs-7 byte diagnosis that loads two pages |
| Dual-version compatibility | `dual-02` | classification is objectively checkable: parse error vs missing parameter vs missing command |
| BAT/CMD | `bat-01` | code page 936, GBK save, Chinese path |
| Python encoding | `py-02`, `py-03` | `coding: gbk` migration and the `gb2312` subset trap |
| Executor arguments | `tool-01` | `$PSScriptRoot`, Chinese argv, no silent `-ExecutionPolicy` widening |
| Security boundary | `tool-02` | read-only sweep; the correct answer changes nothing |

Two of the ten (`ps7-03`, `tool-02`) need two reference pages, which is where the routing
plan and the restructure actually differ most.

## Fairness rules

1. **One model, pinned.** Record the exact model id and version, the client and its
   version, and the sampling settings. Do not change any of them between samples. A model
   that silently updates mid-run invalidates the run.
2. **Isolated sessions.** One session per sample, no prior turns, no memory of another
   sample. If the client supports "new conversation", use it; if it keeps a system prompt
   that mentions the other group, start a fresh client process.
3. **The skill directory is the only documentation.** Each sample gets its own copy of the
   docs under `S*/skill/`, and the prompt tells the model that is the only copy to read.
   No browser, no network, no second checkout on disk.
4. **Same prompt, byte for byte.** `prepare.py` writes the prompt into `S*/PROMPT.md`;
   paste it verbatim. Do not "helpfully" rephrase, do not add hints, do not mention
   English or Chinese.
5. **No cross-contamination.** Do not show one answer to the model that produced another.
   Do not run the two groups in the same session, do not run A then B for the same task in
   the same context window.
6. **Answer language.** Chinese for both groups, stated in every prompt. An English
   answer from group B would score differently on completeness for reasons unrelated to
   the documentation.
7. **Blind ids.** The 20 samples are shuffled into `S01..S20`. The mapping is in
   `SEALED-mapping.json` and is opened only after the scoring sheet is full.

## Procedure

```bash
# 1. build the bundle (writes nothing into the repo; default target is the temp dir)
python tests/benchmarks/quality-ab/prepare.py --out D:/qa-run

# 2. sanity-check the bundle before spending model calls
python - <<'PY'
import json, pathlib
root = pathlib.Path("D:/qa-run")
m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
print(len(m["samples_meta"]), "samples")
for g, info in m["snapshots"].items():
    print(g, len(info["files"]), "files")
PY
```

Then, for each sample directory in `S01..S20`, in order:

1. Start a fresh session with the pinned model.
2. Paste `S*/PROMPT.md` as the single user message.
3. Let the model read `S*/skill/` and write `S*/answer.md`.
4. Fill the one line in `S*/run-log.csv`:
   - `sample_id` — already there
   - `model` — exact id and version
   - `session_id` — whatever the client exposes; a UUID you assign is acceptable if it
     matches a note in `notes`
   - `started_at` — ISO 8601 with offset
   - `reference_files_loaded` — **what the session actually read**, semicolon-separated,
     paths relative to `skill/`. Not the planned `loads` list: this column exists to
     compare the plan against reality.
   - `prompt_tokens`, `completion_tokens`, `total_tokens`, `cached_tokens` — copy from the
     API response. If the client does not expose them, leave them blank and write
     `no usage surface` in `notes`. Do not estimate.
5. Close the session. Do not reuse it.

Order matters only for cost, not for validity. If the run is interrupted, resume from the
first sample without an `answer.md`; never re-run a sample and keep both answers.

## Scoring

Fill `scoring-sheet.md` (generated by `prepare.py`). 100 points:

| Dimension | Max | Anchors |
| --- | ---: | --- |
| Correctness | 30 | Solves the stated problem; wrong root cause caps at 10 |
| Encoding correctness | 25 | Right bytes, right code page, right BOM decision, right stream encoding |
| Host compatibility | 20 | The 5.1/7 difference that matters here is handled, not glossed |
| Safety | 15 | Nothing wider than asked; no policy change, no silent overwrite, no invented success |
| Completeness | 10 | Runnable as written; no placeholder, no "rest is the same" |

Two reviewers, independently, then reconcile: where the two differ by more than 10 points
on a sample, re-read the answer together and record the reason. A single reviewer is
acceptable for a first pass if the second is unavailable — say so in the report.

## Reporting

Required in the write-up:

- model id, client, settings, date, machine (ACL / code page matter here)
- per-sample table: sample id, task, group (after unblinding), five dimension scores, total
- per group: mean, median, min, per-dimension means
- delta per dimension with direction, and the samples that moved most
- observed `reference_files_loaded` vs planned `loads`, both groups
- token usage: per sample if observable, otherwise the sentence "not observable in this
  client" — never an estimate from character counts
- every case where the answer was wrong for a reason the documentation caused, quoted

## What would make the result unusable

- A model version change mid-run, or a client default that differs between samples.
- Any sample where the model read documentation outside `S*/skill/`.
- A run where group membership leaked to the scorer before the sheet was complete.
- Fewer than ten scored samples per group. Report it as `BLOCKED`, not as a trend.

If the target model cannot be called at all, the run stays `PENDING`. An empty result is
acceptable; an invented one is not.
