# CP936 verification

Two different things are called "CP936 coverage" in this repository. They are
not interchangeable, and this page exists so nobody confuses them.

## 1. What runs automatically

`.github/workflows/cp936.yml`, triggered on every push to `main` and by
`workflow_dispatch`. It asserts ACP 936, confirms the pinned module versions,
runs the full matrix on 5.1 and on 7, then re-runs `tests/integration` and
fails if the CP936 assertions were skipped instead of executed.

It is gated on a self-hosted runner:

```yaml
if: ${{ vars.CP936_RUNNER == 'enabled' }}
runs-on: [self-hosted, windows, cp936]
```

Measured state of this repository on 2026-11-12:

| Check | Command | Result |
| --- | --- | --- |
| Repository variables | `gh variable list` | empty, so `CP936_RUNNER` is unset |
| Registered runners | `gh api repos/.../actions/runners` | `total_count: 0` |
| Recent runs | `gh run list --workflow=cp936.yml` | `skipped`, 1s, for every push since the workflow landed |

**Conclusion: the automated CP936 gate has never run, and it is not covered by
CI today.** `skipped` is not `passed`. The gate is honest about it (the job
reports skipped rather than queueing forever), but honest and covered are not
the same thing.

Why the runner is not registered: the only zh-CN machine available is the one
the author works on. Installing a persistent runner on a daily-driver desktop
is a decision for its owner, not something a test task should do on its own.

## 2. What was verified locally instead

`tests/cp936/verify-local.ps1` runs the same checks on a real zh-CN host in one
shot, without registering anything:

```powershell
powershell -NoProfile -File tests/cp936/verify-local.ps1
pwsh       -NoProfile -File tests/cp936/verify-local.ps1
```

It refuses to continue when ACP is not 936, prints the environment, runs the
whole matrix with the edition that started it, then re-runs `tests/integration`
and fails if the CP936 assertions were skipped.

### Recorded result, 2026-11-12, this machine

Environment, identical for both runs:

| Item | Value |
| --- | --- |
| OS | Microsoft Windows 11 专业版 10.0.26200 |
| ACP / OEMCP | 936 / 936 |
| Python | 3.13.9 |
| Pester | 5.7.1 |

Windows PowerShell:

| Suite | Result |
| --- | --- |
| Runtime | Desktop 5.1.26100.9711 |
| Pester | 77 passed, 0 failed, 0 skipped |
| PSScriptAnalyzer | 12 files, clean |
| Python unit | 47 passed |
| Docs contract | 38 passed |
| Integration | 22 passed |
| CP936 assertions | `CP936_ASSERTIONS_EXECUTED` |

PowerShell 7:

| Suite | Result |
| --- | --- |
| Runtime | Core 7.7.0 |
| Pester | 77 passed, 0 failed, 0 skipped |
| PSScriptAnalyzer | 12 files, clean |
| Python unit | 47 passed |
| Docs contract | 38 passed |
| Integration | 22 passed |
| CP936 assertions | `CP936_ASSERTIONS_EXECUTED` |

Both runs ended with `RESULT=PASSED` and exit code 0. The transcript carries no
user name, only code page numbers and version strings.

The integration tests that only mean something on 936 hosts and did run here:

- `test_ps51_parses_bomless_utf8_as_gbk` -- without a BOM, 5.1 decodes UTF-8
  bytes with the ANSI code page, so the Chinese text arrives mangled.
- `test_ps51_parses_utf8_bom_correctly` -- with a BOM it is correct.
- `test_writer_round_trip_is_idempotent` -- writing the same content twice
  produces identical bytes.

## 3. What a hosted runner does cover

`windows-latest` is en-US with ANSI code page 1252. Everything in
`tests/integration/TestCp936Host` skips itself there and prints the reason, so
the hosted matrix is real coverage of everything else -- both PowerShell
editions, both Python versions, the detector, the writer, the executor, the
packaging logic -- and no coverage at all of the CP936-only behaviour.

## 4. To close the gap

Register a runner with the labels `self-hosted, windows, cp936` on a zh-CN
Windows machine that is not a daily driver, then set the repository variable:

```bash
gh variable set CP936_RUNNER --body enabled
```

The job stops reporting skipped on the next push and starts gating.
