# PS51 root cause: manual save vs automatic write

## The old task

`ps51-01` prompt: "在 H:\work\部署 目录下新建 deploy.ps1..." — 新建 means create, but it
does not say "write it with a script, not a save dialog". The benchmark's
`expected_behavior` is stronger: "Writes the file as UTF-8 with BOM, uses explicit
encoding on all I/O".

Stage 3.1 result across three samples per side:

| Group | Programmatic write | Manual save | Mean |
| --- | ---: | ---: | ---: |
| A (v1.0.4) | 1 / 3 | 2 / 3 | 83.33 |
| B (v1.1.0) | 0 / 3 | 3 / 3 | 75.00 |

The documents already contain the method:

- `references/powershell-51.md` §2 shows `WriteAllText` with
  `New-Object System.Text.UTF8Encoding($false)`, a read-back and an atomic replace.
- `SKILL.md` rule 1 states that non-ASCII in a `.ps1` must be UTF-8 with BOM.

The models chose a save-dialog instruction anyway. The capability is not missing; the
**requirement** was ambiguous.

## The new task

`ps51-autowrite-01` makes it explicit:

- the script must create `deploy.ps1` itself;
- no save dialog;
- UTF-8 BOM;
- Chinese content;
- read it back and verify the bytes;
- run on Windows PowerShell 5.1.

Stage 3.2 result, three fresh samples per side:

| Group | File created | BOM | Chinese read-back | 5.1 runs | Mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 100 |
| B | 3 / 3 | 3 / 3 | 3 / 3 | 3 / 3 | 100 |

All six wrote the file themselves, with `EF BB BF` and matching Chinese content, and ran
on 5.1. No sample used a save dialog.

## Classification

**`MODEL_INSTRUCTION_FOLLOWING` under an ambiguous requirement.** Once the requirement is
unambiguous, both groups comply. This is not a documentation defect: the method and the
BOM rule are present, and the explicit task does not add new documentation. No Skill change
is justified.

## Consequence

Keep `ps51-01` as the general script-and-encoding task, and keep
`ps51-autowrite-01` as the separate task that measures automatic creation. Do not fold the
auto-write requirement into the old prompt retroactively; that would make historical
results incomparable.
