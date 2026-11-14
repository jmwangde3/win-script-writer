# Model quality A/B: v1.0.4 vs v1.1.0

Status: **PENDING** — see `STATUS.md`. Nothing in this directory is a result.

The context benchmark (`../README.md`) estimates how many tokens the skill costs. It says
nothing about whether the answers get better or worse. This plan measures that, with a
real model, on eleven tasks, under conditions that make the comparison fair and the
scoring blind.

## What is being compared

| Group | Documentation | Snapshot | Copied into a sample |
| --- | --- | --- | ---: |
| A | v1.0.4, Chinese | `../baseline/v1.0.4` | 12 files |
| B | v1.1.0, English | `../candidate/v1.1.0` | 14 files |

`CHANGELOG.md` is excluded from both bundles: it is release history, not documentation a
model needs to answer, and it names the version. Excluding it in both groups keeps the
only difference between them the one being measured. `prepare.py` verifies both snapshots
against an explicit file list — a missing page or an unexpected extra file aborts the
build instead of producing a quietly different bundle.

Only the documentation differs. Same prompts, same model, same client, same machine, same
answer language.

The eleven tasks live in `tasks.json`, chosen from `../tasks.json` so that every one of
the eight categories is represented:

| Area | Tasks | Why these |
| --- | --- | --- |
| Windows PowerShell 5.1 | `ps51-01`, `ps51-04` | one writes bytes, one repairs a stream a downstream reader cannot decode |
| PowerShell 7 | `ps7-01`, `ps7-03` | BOM-less write plus output rendering; then a 5.1-vs-7 byte diagnosis that loads two pages |
| Dual-version compatibility | `dual-02` | classification is objectively checkable: parse error vs missing parameter vs missing command |
| BAT/CMD | `bat-01` | code page 936, GBK save, Chinese path |
| Python encoding | `py-02`, `py-03` | `coding: gbk` migration and the `gb2312` subset trap |
| Git Bash | `bash-01` | MSYS path conversion across `python.exe` and `powershell.exe` |
| Executor arguments | `tool-01` | `$PSScriptRoot`, Chinese argv, no silent `-ExecutionPolicy` widening |
| Security boundary | `tool-02` | read-only sweep; the correct answer changes nothing |

`bash-01` is copied verbatim from `../tasks.json`: prompt, `expected_behavior`,
`required_checks`, `forbidden_actions` and `loads` are byte-identical, and a test fails if
they drift. It was missing from the first draft of this set even though Git Bash is one of
the eight categories the release touches.

Two of the eleven (`ps7-03`, `tool-02`) need two reference pages, which is where the
routing plan and the restructure actually differ most.

## Two directories, two people

The run is split so that the person scoring never sees which documentation produced an
answer.

**Executor bundle** — `prepare.py --out <dir>`:

```
S01/  skill/  PROMPT.md  answer.md  run-log.csv
...
S22/
manifest.json          seed, per-file SHA-256, per-sample hash record
SEALED-mapping.json    sample -> task -> group
```

`SEALED-mapping.json` is **access-control isolation, not encryption**. It is a separate
file held by the executor; anyone who receives a copy can unblind the run. Do not describe
it as cryptographically sealed.

**Scoring packet** — `make_scoring_packet.py --run <bundle> --out <dir>`, run only after
all 22 answers exist:

```
answers/R001.md ... R022.md    randomly renumbered
SCORING-GUIDE.md               prompt, pass conditions, must-not, rubric
scores-reviewer-1.csv          empty, pre-filled answer ids
scores-reviewer-2.csv          empty, pre-filled answer ids
README.md                      the rules
```

The packet contains no group letter, no sample id, no task id, no seed, no manifest, no
skill document, no run log and no token usage. `SCORER-KEY.json` is written outside the
packet and belongs to the executor; `unseal.py` is the only tool that reads it.

## Fairness rules

1. **One model, pinned.** Record the exact model id and server version (if the API exposes
   one), the client and its version, and the sampling settings: temperature, top_p, max
   output tokens, sampling seed if the client supports it, and the test date. Do not change
   any of them between samples. A model that silently updates mid-run invalidates the run.
   "DeepSeek" alone is not a model id; the model that implemented this repository is not
   automatically the model under test.
2. **Isolated sessions.** One session per sample, no prior turns, no memory of another
   sample. If the client keeps a system prompt that mentions the other documentation set,
   start a fresh client process.
3. **The skill directory is the only documentation.** Each sample gets its own copy under
   `S*/skill/`, and the prompt says that is the only copy to read. No browser, no network,
   no second checkout on disk. If the client cannot restrict file access to that directory,
   it cannot support this test — say so rather than running it anyway.
4. **Same prompt, byte for byte.** `prepare.py` writes `S*/PROMPT.md` with no sample id and
   no group. The two samples of one task must have identical SHA-256; the builder refuses
   to finish if they do not, and a test re-checks it.
5. **No cross-contamination.** Do not show one answer to the model that produced another.
   Do not run the two groups in the same session, and do not run A then B for the same
   task in one context window.
6. **Answer language.** Chinese for both groups, stated in every prompt. An English answer
   from group B would score differently for reasons unrelated to the documentation.
7. **Blind ids, random seed.** The 22 samples are shuffled into `S01..S22` with a seed that
   is random by default and stored only in the executor's `manifest.json`. `--seed` exists
   for reproducible tests, not for production. `--dry-run` prints task ids and sample
   numbers and never prints the group.
8. **Repetitions are planned, not improvised.** Phase 1 is 22 samples — a screening run and
   a procedure test. If the groups come out close, unstable, or the result is going to
   carry a release decision, phase 2 repeats all eleven tasks × two groups × three times
   = 66 answers. Do not add repeats to the group that looks worse.

## Procedure

```bash
# 1. build the executor bundle (default target is the system temp dir)
python tests/benchmarks/quality-ab/prepare.py --out D:/qa-run

# 2. run 22 isolated sessions, one per S*/PROMPT.md, writing S*/answer.md
#    the executor fills S*/run-log.csv afterwards -- the model writes only answer.md

# 3. after every answer exists, build the anonymous packet
python tests/benchmarks/quality-ab/make_scoring_packet.py \
    --run D:/qa-run --out D:/qa-packet

# 4. two reviewers fill scores-reviewer-1.csv / -2.csv independently

# 5. unblind and aggregate
python tests/benchmarks/quality-ab/unseal.py \
    --packet D:/qa-packet --key D:/qa-run-SCORER-KEY.json \
    --scores D:/qa-packet/scores-reviewer-1.csv \
    --scores D:/qa-packet/scores-reviewer-2.csv \
    --run D:/qa-run --out D:/qa-results.md
```

Order matters only for cost, not for validity. If the run is interrupted, resume from the
first sample without an `answer.md`; never re-run a sample and keep both answers.

### The run log

The model writes `answer.md` and nothing else. The executor fills `run-log.csv`, one
pre-filled row per sample, with these fields:

| Field | Meaning |
| --- | --- |
| `sample_id` | pre-filled by the builder; never typed by hand |
| `model` | exact model id |
| `model_version` | server or snapshot version, if exposed |
| `client` | client name |
| `client_version` | client version |
| `session_id` | the id the client actually exposes |
| `started_at`, `finished_at` | ISO 8601 with offset |
| `temperature`, `top_p` | the settings used, not the defaults you assume |
| `prompt_tokens`, `completion_tokens`, `total_tokens`, `cached_tokens` | copied from the API `usage` object, or left empty |
| `planned_references` | pre-filled from `loads` / `loads_baseline` |
| `provided_references` | what the harness actually put in front of the model |
| `opened_references` | what a file-access log shows was opened |
| `load_evidence` | `client-file-log`, `self-reported`, or `not observable` |
| `notes` | anything that would otherwise be lost |

Two rules, because both have been violated by benchmark write-ups before:

- **A model saying "I read `references/x.md`" is not a file-access record.** If the client
  has no file log, write `not observable` in `opened_references` and `self-reported` in
  `load_evidence`. Never upgrade a self-report to an observation.
- **Never invent token usage.** If the client does not expose `usage`, leave the token
  cells empty. Character counts, file sizes and tokenizer estimates are not API usage and
  must not be written in those columns.

## Scoring

100 points:

| Dimension | Max | Anchors |
| --- | ---: | --- |
| Correctness | 30 | Solves the stated problem; wrong root cause caps at 10 |
| Encoding correctness | 25 | Right bytes, right code page, right BOM decision, right stream encoding |
| Host compatibility | 20 | The 5.1/7 difference that matters here is handled, not glossed |
| Safety | 15 | Nothing wider than asked; no policy change, no silent overwrite, no invented success |
| Completeness | 10 | Runnable as written; no placeholder, no "rest is the same" |

Two reviewers, independently, then reconcile: where the two differ by more than 10 points
on an answer, re-read it together and record the reason. A single reviewer is acceptable
only for a screening pass — say so in the report, and the quality state does not become
`PASS` on one reviewer's numbers.

An answer that mentions "the English documentation", quotes an English heading, or
otherwise reveals which set it came from gets **no bonus and no penalty** for that. Score
the technical content; note the meta-commentary separately if it matters.

## Reporting

`unseal.py` writes the report; `--meta` supplies the run identity. It must contain:

1. model id and version
2. client and version
3. environment (OS, ACL, code page)
4. sampling parameters
5. tasks tested
6. every answer's five dimension scores, after unblinding
7. group A mean, median, minimum
8. group B mean, median, minimum
9. per-dimension means
10. the A/B delta, with direction
11. the samples that moved most
12. encoding error cases
13. compatibility error cases
14. safety-boundary error cases
15. the reference files actually provided
16. the file-loading evidence actually observed
17. whether token usage was observable
18. limitations
19. the final quality conclusion

If B regresses on any of correctness, encoding correctness or safety, say so by name. A
higher total does not offset a safety regression.

## Windows execution verification (separate from scoring)

A model answer scoring well is not the same as code that runs. After scoring, take the
answers that will be quoted and execute them in an isolated temporary directory on a real
Chinese Windows host. Do not use production data and do not change system-wide settings.

| Answer type | What to verify |
| --- | --- |
| PowerShell | Windows PowerShell 5.1 and PowerShell 7.4, actual bytes, BOM, Chinese display, UTF-8 / UTF-16LE / GBK, the version difference the answer claims |
| BAT/CMD | GBK without BOM, a Chinese path, code page 936, argument quoting, `exit /b` code |
| Python | source encoding declaration, GBK→UTF-8 conversion, GB2312 vs GBK, subprocess argv and output decoding |
| Tooling | real `$PSScriptRoot`, Chinese argv, no implicit `-ExecutionPolicy` widening |
| Security | read-only behaviour, no file rewrite, no ACP change, no execution-policy change |

If no such host is available, mark the stage **not executed**. Static review is not a
substitute and must not be reported as one.

## What would make the result unusable

- A model version change mid-run, or a client default that differs between samples.
- Any sample where the model read documentation outside `S*/skill/`.
- A run where group membership leaked to the scorer before both sheets were complete.
- Fewer than eleven scored answers per group. Report it as `BLOCKED`, not as a trend.
- A packet built before every answer existed, or a score file with a blank dimension.

If the target model cannot be called at all, the run stays `PENDING`. An empty result is
acceptable; an invented one is not.
