# win-script-writer

Encoding rules and four tools for writing scripts on Simplified Chinese Windows
(zh-CN / code page 936 / GBK). Built for AI agents, useful to humans.

## What it solves

These symptoms keep showing up on Simplified Chinese Windows and look like four
different problems. They are four independent broken links:

- `Get-Content` reading a UTF-8 file as `涓` or `锟斤拷`
- a txt written by `Out-File` / `>` that Python and Node cannot read
- Chinese arguments reaching `git.exe` or `python.exe` as `?`
- Chinese string literals inside a `.ps1` turning into mojibake
- line 1 of a `.bat` reporting "not recognized as an internal or external command"
- a Chinese path plus nested quotes raising "string is missing the terminator"
- Python blowing up because `open()` got no `encoding`
- a script exiting 0 having done nothing

## Requirements

Windows 10/11 Simplified Chinese, system ANSI code page 936, Windows PowerShell 5.1,
PowerShell 7.4+, system-wide UTF-8 disabled; the Git Bash / MSYS2 side is UTF-8.

Other languages or code pages use the same decision rules — read the actual numbers from
`scripts/Get-WinScriptEnvironment.ps1`.

## Quick start

```bash
git clone https://github.com/jmwangde3/win-script-writer.git
cd win-script-writer
```

Read the host first (read-only, no administrator needed):

```powershell
powershell -NoProfile -File scripts/Get-WinScriptEnvironment.ps1
```

The output is a series of `KEY=value` lines. Four of them matter most:

```
ACP=936                 # system ANSI code page; 5.1 uses it to parse BOM-less scripts
CONSOLEOUTCP=936        # current console output code page
OUTPUTENCODING=us-ascii # what 5.1 uses for a native program's stdin (not argv)
PSEDITION=Desktop       # Desktop = 5.1, Core = 7
```

Check what a file actually is:

```powershell
powershell -NoProfile -File scripts/Test-ScriptEncoding.ps1 -Path .\build.ps1
```

Write it in a chosen encoding (refuses to overwrite by default; without `-Encoding` the
choice follows the extension):

```powershell
# .ps1 gets utf8-bom, the one form both 5.1 and 7 accept
powershell -NoProfile -File scripts/New-EncodedScript.ps1 `
    -Path .\build.ps1 -ContentFile .\source.txt

# ask for another encoding explicitly
powershell -NoProfile -File scripts/New-EncodedScript.ps1 `
    -Path .\legacy.cmd -ContentFile .\source.txt -Encoding gbk -Force -Backup
```

Run a snippet that carries Chinese:

```bash
python scripts/run_ps.py 'Write-Output "hello"'
python scripts/run_ps.py --shell pwsh --command '$PSVersionTable.PSEdition'

# when a real file context is needed ($PSScriptRoot, relative dot-source):
python scripts/run_ps.py --invoke-file .\script.ps1
```

## The four tools

| Tool | Purpose | Read-only |
| --- | --- | --- |
| `scripts/Get-WinScriptEnvironment.ps1` | reports ACP / OEMCP / console code page / `$OutputEncoding` / runtime edition | yes |
| `scripts/Test-ScriptEncoding.ps1` | byte-level detection: validates the payload after the BOM, recognises the four-byte UTF-32 signatures and Python's PEP 263 declarations, returns OK/WARN/FAIL per target consumer | yes |
| `scripts/New-EncodedScript.ps1` | writes in a chosen encoding via temp file, read-back check and atomic replace; the default encoding is derived from the extension | no — overwriting needs `-Force` |
| `scripts/run_ps.py` | executes code without code page loss; text mode goes through UTF-16LE base64, `--invoke-file` uses native `-File` | no — it executes what you give it |

Exit codes are a contract: detector `0/1/2/3`; writer `0/2/3` plus `4` (the user
answered "no" at the confirmation prompt, **nothing was written**; `-WhatIf` still
returns 0, it only previews); `run_ps.py` passes the child's code through and adds
`3/124/127`.

## Installing as a skill

Claude Code, personal or project scope:

```bash
# personal
mkdir -p ~/.claude/skills/win-script-writer
cp -r SKILL.md references scripts ~/.claude/skills/win-script-writer/

# project
mkdir -p .claude/skills/win-script-writer
cp -r SKILL.md references scripts .claude/skills/win-script-writer/
```

The directory name (or the frontmatter `name`) becomes the `/win-script-writer` command.
Claude Code decides when to load it automatically from `description`.

Hosts that only read rule files such as `AGENTS.md` / `CLAUDE.md`: put the *path* to
`SKILL.md` there, for example "read `<repo>/SKILL.md` before writing Windows scripts".
Do not copy the content into the rule file — a copy drifts.

## Layout

```
SKILL.md                      entry point: routing table and the four rules only
references/                   12 details, loaded on demand
  encoding-matrix.md          which file takes which encoding (with measured bytes)
  powershell-51.md            the four broken links and the correct forms
  powershell-7.md             what 7 fixed, what still breaks
  dual-version-compatibility.md  the no-go list for one script on both versions
  cmd-bat.md                  four ways to save a .bat, measured
  python.md                   the default encoding is not UTF-8
  python-source-encoding.md   what a `# coding:` line actually does
  git-bash.md                 MSYS path conversion and git quotepath
  execution.md                choosing among the launch modes
  security.md                 what the tools refuse to do by default
  troubleshooting.md          symptom → one fix
  appendix-codec-evidence.md  measurements behind a codec verdict (second hop)
scripts/                      the four tools
tests/                        Pester + unittest + contract checks
```

`SKILL.md` has to stay small (about 5.3 KB today) with every detail in `references/`.
That is the premise of progressive disclosure: a large entry file means a full load every
time.

## Design decisions

- **Evidence, not guessing.** Failing UTF-8 does not prove GBK — CP936 in .NET has no
  undefined bytes and maps `0xFF` to `U+F8F5`. A file is labelled `gbk` only when
  decode-then-encode is byte-identical, and only at medium confidence.
- **`WARN` does not mean the file runs.** Python's codec name table is wider than what
  the detector can verify: names such as `cp1252`, `shift_jis`, `big5` hold on the
  CPython versions this project sampled, but the detector has no byte table for them and
  cannot see illegal bytes in the payload. Those report `WARN` +
  `SOURCE_CODING_PAYLOAD=unverified` (JSON `SourceCodingPayload`) — "the name is in the
  compatibility set, the current interpreter may not resolve it, the payload is
  unverified" — rather than pretending `OK`. The name table itself is an exact table
  organised by family, not a prefix regex: imitations such as `mac-bogus` are `FAIL`.
  Conversely `base64` / `rot13`, which resolve but cannot serve as source encoding, are
  `FAIL` + `PY_SOURCE_CODING_UNUSABLE`, reported apart from "name unknown".
- **No system state changes by default.** No injected `-ExecutionPolicy Bypass`, no
  auto-elevation, no `ACP` change, no overwriting existing files, no replacing
  unencodable characters with `?`. Reasoning in `references/security.md`.
- **No `Add-Type`.** Reading the Win32 code page would compile C# at runtime, and some
  security policies forbid exactly that. A diagnostic tool must run in restricted
  environments, so it reads the registry and the .NET console layer instead, and records
  which source it used (`ACPSOURCE=`).
- **Both editions must pass.** Every stage runs the same suite under Windows PowerShell
  5.1 and PowerShell 7. "Theoretically compatible" is not accepted.

## Tests

```powershell
# everything
powershell -NoProfile -File tests\run-all.ps1
pwsh       -NoProfile -File tests\run-all.ps1

# one suite
powershell -NoProfile -File tests\run-all.ps1 -Suite pester
powershell -NoProfile -File tests\run-all.ps1 -Suite analyze
powershell -NoProfile -File tests\run-all.ps1 -Suite python
powershell -NoProfile -File tests\run-all.ps1 -Suite integration
powershell -NoProfile -File tests\run-all.ps1 -Suite evals
```

The Python side uses the standard library `unittest`; no `pip install` needed. Pester
5.7.1 is required:

```powershell
Install-Module Pester -RequiredVersion 5.7.1 -Scope CurrentUser
Install-Module PSScriptAnalyzer -Scope CurrentUser
```

## Verified scope

Keep three things apart, or "I ran it once" turns into "it is supported".

**Official matrix (six CI jobs, every push)**: Windows PowerShell 5.1 with Python 3.11,
5.1 with 3.13, PowerShell 7 with 3.11, PowerShell 7 with 3.13, a UTF-8 mode preview
(Python 3.13 + `PYTHONUTF8=1`), and docs contract. The hosted runner is en-US / ACP 1252,
so CP936 cases skip themselves there; CP936 assertions hold only on a self-hosted runner
(`cp936.yml` — no such runner is registered yet, so it has never run) or on this machine.
**Skipped is not passed.**

**Additional measurements (run by hand, not in CI)**: Windows 11 Simplified Chinese with
ACP=936 / OEMCP=936, PowerShell 5.1.26100 (Desktop) and 7.7.0 (Core), Pester 5.7.1,
PSScriptAnalyzer 1.24.0, Python 3.11.17 / 3.13.9 / 3.13.16 / 3.14.8 / 3.15.0rc3.

**Not in the official matrix**: Python 3.14 and 3.15. Their alias tables are wider than
what this project sampled and the detector has not caught up: the same alias regression
shows 6 disagreements on 3.14.8 and 58 on 3.15.0rc3 (the list is in the "known not
covered" section of `CHANGELOG.md`). The UTF-8 mode job simulates 3.15's *default
behaviour*; it is **not** a 3.15 compatibility test. On those versions the detector marks
a few files `FAIL` that the interpreter can compile — erring towards saying too much,
not towards passing.

Nothing else has been measured. The rules carry over; get the numbers from
`Get-WinScriptEnvironment.ps1` yourself.

The full codec alias regression hard-codes no names: it walks `encodings.aliases` and the
module names under `encodings/` at test time, `compile()`s each and then asks the
detector. On 3.13.9 that is 471 spellings (327 alias keys + 98 canonical names + 121
module names + 24 imitation spellings, after deduplication), 380 usable as source, 91
refused, 0 disagreements; on 3.13.16 it is 479 (the extras are the leading-zero aliases
gh-149801 gave `cp858` / `cp1140`, available from 3.13.14), also 0 disagreements. The
numbers move with the interpreter; the rule does not.

The one-off verification record for this host (ACP=936) and the "skipped is not covered"
argument live in `tests/cp936/README.md`.

## License

MIT — see `LICENSE`.
