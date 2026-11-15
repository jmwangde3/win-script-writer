# Stage 3.2: BAT code pages and PS51 automatic write

Branch: `test/v1.1.0-stage3-2-validation`, from `dddeede`.

Two targeted experiments, three samples per side each:

1. **BAT** — one batch must run at console code page 936 and 65001, with a Chinese path,
   a Chinese argument, `构建完成`, and exit code 7, without the user changing the console.
2. **PS51** — a script must create `deploy.ps1` itself with UTF-8 BOM and Chinese content,
   read it back, verify the bytes, and run on Windows PowerShell 5.1.

Both use the frozen v1.0.4 (A) and v1.1.0 (B) snapshots and the same model, prompt and
reasoning level, with shuffled independent sessions.

## Why these tasks

Stage 3.1 showed two gaps: B's BAT omitted `chcp 936` in one of three samples, and
neither the old task nor the old PS51 answers required a programmatic write unambiguously.
These tasks make both requirements explicit and measure them directly. They do not replace
the historical `bat-01` or `ps51-01`; they are separate (`bat-codepage-01`,
`ps51-autowrite-01`).

## Layout

| Path | Content |
| --- | --- |
| `tasks.json` | the two prompts and their required checks |
| `bat-root-cause.md` | S07 evidence and classification |
| `ps51-root-cause.md` | old-task ambiguity and the new explicit task |
| `parser-coverage.json` | per-block parser results |
| `task-results.csv`, `summary.json` | per-sample and aggregate |
| `token-comparison.json` | context estimate, not API usage |
| `report.md` | A/B reading and verdict |
| `raw/A`, `raw/B` | model answers, unedited |
| `execution/A`, `execution/B` | bytes, runs and checks per sample |
| `logs/` | command logs |
| `scripts/` | bundle builder, checker, assembler |

## Reproduce

```bash
python tests/benchmarks/real-model-ab-stage3-2/scripts/make_bundle.py --root <root>
# generate twelve answers with the pinned client
python tests/benchmarks/real-model-ab-stage3-2/scripts/run_checks.py --root <root>
python tests/benchmarks/real-model-ab-stage3-2/scripts/assemble.py
```

No `-ExecutionPolicy Bypass`, no admin, no system ACP change. A temp directory is not an
OS sandbox; the residual risk is stated in `report.md`.
