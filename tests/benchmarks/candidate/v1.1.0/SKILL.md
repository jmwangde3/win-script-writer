---
name: win-script-writer
description: Use when creating, editing, or troubleshooting scripts on Simplified Chinese Windows (ACP 936/GBK), including PowerShell 5.1/7, BAT/CMD, and Python. Covers encoding, BOM, code pages, Chinese text corruption, script execution, and argument passing. Provides environment diagnostics, encoding validation, reliable file writing, and cross-version execution.
---

# Scripting on Chinese Windows

Targets Windows 10/11 Simplified Chinese (ANSI code page 936), Windows PowerShell 5.1
and PowerShell 7.4+, system-wide UTF-8 off; the Git Bash / MSYS2 side is UTF-8.

## 1. Applicability

Any script written or changed on this host, and any mojibake you are asked to fix. Four
settings decide encoding and none implies another: ACP (936) governs how 5.1 parses a
BOM-less `.ps1` and what native tools write; OEMCP governs `cmd.exe` console I/O; the
console code page is what `chcp` reports; `$OutputEncoding` /
`[Console]::OutputEncoding` govern pipelines. Never infer one from another.

## 2. Workflow

1. **Read the host.** `scripts/Get-WinScriptEnvironment.ps1` reports every setting in
   §1, plus `[Encoding]::Default`, whether CP936 resolves, and the edition.
2. **Load one reference.** The single matching row in §3, not the whole set.
3. **Verify before handing over.** `scripts/Test-ScriptEncoding.ps1 -Path <file>`
   must print `VERDICT=OK` and exit 0. Byte-level verdict, not a style check.

## 3. Reference Routing

| Task | Load |
| --- | --- |
| File format → encoding | `references/encoding-matrix.md` |
| 5.1 script | `references/powershell-51.md` |
| 7 script | `references/powershell-7.md` |
| One script, both versions | `references/dual-version-compatibility.md` |
| `.bat` / `.cmd` | `references/cmd-bat.md` |
| Python | `references/python.md` |
| Python `# coding:` line | `references/python-source-encoding.md` |
| Git Bash / MSYS2 | `references/git-bash.md` |
| Launching, Chinese arguments | `references/execution.md` |
| Defaults, elevation, sandbox | `references/security.md` |
| Broken, need the fix | `references/troubleshooting.md` |
| Codec evidence, disputed verdict | `references/appendix-codec-evidence.md` |

## 4. Mandatory Rules

Violating any of them means rework.

1. **Non-ASCII in a `.ps1` → UTF-8 with BOM.** 5.1 parses a BOM-less file with the
   ACP (936) and turns UTF-8 Chinese into mojibake; 7 parses it as UTF-8. A BOM
   satisfies both and stays readable to other tools (UTF-16 with BOM also runs, but
   only PowerShell reads it). Pure ASCII needs no BOM.
2. **Never write files with `>`, `>>`, `Out-File`, or `Set-Content`.** Under 5.1
   they emit UTF-16LE with BOM, or ANSI; Python, Node and git read that as garbage.
   Use `[System.IO.File]::WriteAllText($p, $s, $utf8NoBom)`, then read it back.
3. **Never hand-assemble command lines carrying Chinese text or nested quotes.** An
   argv list keeps the command line as Unicode and loses nothing; the loss is at the
   byte layer — a command inside a GBK `.bat`, a shell re-joining arguments, stdout
   decoded with the wrong code page. Prefer a file: `-File` or `scripts/run_ps.py`,
   and `--invoke-file` when `$PSScriptRoot` must survive.
4. **Never assume the profile is loaded.** Agent hosts run
   `-NoProfile -NonInteractive`, so `$PROFILE` never executes. Put the encoding
   fallback inline at the top of the script.

## 5. Tools

Each needs only the .NET base classes that 5.1 ships, or the Python standard
library. No modules, no administrator rights.

- **`Get-WinScriptEnvironment.ps1`** — read-only self-check; `-Output Json` gives a
  machine-readable report, `WARNING=` appears only when the condition holds.
- **`Test-ScriptEncoding.ps1`** — byte-level detection. Reports BOM, non-ASCII bytes,
  strict UTF-8 validity and CP936 round-trip, then OK/WARN/FAIL per consumer (ps51 /
  ps7 / cmd / python / bash / data). Evidence only: invalid UTF-8 does not mean GBK,
  and only a byte-exact round trip earns gbk. `WARN` does not mean it runs — `cp1252` /
  `shift_jis` have no byte table here, so output carries
  `SOURCE_CODING_PAYLOAD=unverified`; transform codecs (`base64`, `rot13`) fail as
  `UNUSABLE`.
- **`New-EncodedScript.ps1`** — write with a chosen encoding. Chinese goes through a
  file, never the command line; temp file, read back, atomic replace. Refuses to
  overwrite without `-Force`.
- **`run_ps.py`** — execute without code page loss. `--command` / `--file` / `--stdin`
  use `-EncodedCommand` and have no file context; `--invoke-file` uses native `-File`
  and keeps `$PSScriptRoot` / `$PSCommandPath`. Touches neither execution policy nor
  console encoding by default; not a sandbox. Exit codes: the child's, 3 local error,
  124 timeout, 127 no shell.

## 6. Security Boundaries

Encoding and transport only — not permissions, sandboxing or auditing. No state
changes by default: no injected `-ExecutionPolicy Bypass`, no auto-elevation, no ACP
change. Each requires an explicit request.

## 7. Known Limitations

- 5.1 is an OS component: not removable, no in-place upgrade to 7, and installing 7
  does not stop these tools invoking 5.1 by absolute path.
- System-wide UTF-8 (Beta) needs a reboot, breaks older GBK software, and fixes
  neither `Out-File`'s UTF-16LE nor `$OutputEncoding`'s us-ascii.
- Rules assume Simplified Chinese Windows; other code pages use the same tests with
  the numbers `Get-WinScriptEnvironment.ps1` reports.
