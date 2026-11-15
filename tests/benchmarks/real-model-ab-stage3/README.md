# Stage 3: local controlled dynamic test

Branch: `test/v1.1.0-stage3`, based on `175162c`.
Run root: `%TEMP%\wsw-v110-stage3\<run-id>` (not in the repository).

This round does what the two previous ones could not: it regenerates ten answers, runs
the reviewed scripts in a throwaway directory as a normal user, and compares A/B on bytes
and exit codes. It does **not** pretend that a temp directory is an OS sandbox; the limits
are written down in `plan.md`.

## What is here

| Path | Content |
| --- | --- |
| `routing-investigation.md` | why SAFETY read encoding-matrix + powershell-51, with the root cause |
| `token-comparison.json` | six-task, five-task and three-task token views, arithmetic and weighted |
| `parser-coverage.json` | per-block parser results for the ten new answers |
| `run-config.json` | model, client, environment, permissions, run root |
| `raw/A`, `raw/B` | the ten fresh answers, copied from the bundle unedited |
| `execution/A`, `execution/B` | per-sample result: parse, pre-review, run, bytes, hashes |
| `logs/` | selftest and per-sample stdout/stderr |
| `task-results.csv`, `summary.json` | one row per sample and the aggregate |
| `report.md` | the A/B reading and the verdict |
| `scripts/` | bundle builder, harmless selftest, parser coverage, model checks, token report |

## Environment

- Windows 11, normal user (`IsInRole(Administrator) = false`)
- Windows PowerShell 5.1 and PowerShell 7.7
- Python 3.13
- No `-ExecutionPolicy Bypass`; the machine policy is RemoteSigned
- System ACP is 65001; the BAT tests set the **console** code page in a wrapper and never
  touch the system setting

## Reproduce

```bash
python tests/benchmarks/real-model-ab-stage3/scripts/make_bundle.py --root <root>
# generate the ten answers with the pinned client
python tests/benchmarks/real-model-ab-stage3/scripts/selftest.py --root <root>
python tests/benchmarks/real-model-ab-stage3/scripts/stage3_parser_coverage.py --root <root>
python tests/benchmarks/real-model-ab-stage3/scripts/run_model_checks.py --root <root>
python tests/benchmarks/real-model-ab-stage3/scripts/token_report.py
```

`run_model_checks.py` refuses to run an answer whose parser status is not PASS, whose
blocks are unclassified, or whose code contains a destructive, registry, policy, elevation
or network command. There is no override flag.
