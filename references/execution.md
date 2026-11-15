# Execution: how to get the script running

"Written correctly" and "runs correctly" are two different problems. This page covers
the second, with emphasis on **how Chinese arguments survive the command line**.

## 1. Five ways to launch

| Way | What the command line carries | File context | Use when |
| --- | --- | --- | --- |
| `-Command "<text>"` | the script body | none | one-off simple queries |
| `-File script.ps1` | the path only | yes | the default choice |
| `-EncodedCommand <base64>` | base64 of UTF-16LE | none | the host blocks `-File`, or inline is mandatory |
| `run_ps.py --command/--file/--stdin` | decided by the wrapper | **none** | one entry point for agents and CI |
| `run_ps.py --invoke-file <path>` | the path only | **yes** | when a real `$PSScriptRoot` matters |

### Where Chinese actually gets lost

"The command line is decoded with the ANSI code page" is too coarse — it sends people to
fix the wrong layer. Measured, there are three layers, and only the second and third
lose characters:

| Layer | Mechanism | Loses Chinese? |
| --- | --- | --- |
| Windows process API | `CreateProcessW` takes a UTF-16 command line; an argv-list call lets the runtime assemble it | No. Measured: `-Command 'Write-Output "中文"'` through argv prints correctly |
| Byte layer | a command hard-coded inside a GBK `.bat`, a shell re-joining arguments into a byte string, feeding a file as the command line | Yes. The encoding at these sites is decided by the code page |
| Host decode layer | which code page the captured stdout is decoded with | Decides whether what you *see* is mojibake. 5.1 writes stdout in the console output code page; decoding as UTF-8 shows garbage |

So the real trigger is "**something turned the string into bytes without declaring an
encoding**", not the name `-Command`. The same `-Command` loses nothing through argv and
loses everything when written into a GBK `.bat` and executed. Rule: **if you can avoid
the byte layer, avoid it.**

### Nested quotes are a second, separate risk

Quotes are their own problem: the text of `-Command` is assembled once by the caller and
then parsed again by PowerShell's grammar, and the two quoting rules differ. Whether
`-Command "Write-Output \"a 'b c'\""` works depends on **how the caller assembled it**,
not on how PowerShell parses it.

`-File` passes one value across one boundary — a path, handed over by `CreateProcess` as
Unicode, touching no code page and no syntax parsing.

### Why `-EncodedCommand` is always safe

It encodes the script text as **UTF-16LE** and then base64. The entire command line is
pure ASCII, containing neither Chinese nor quotes, so no layer has to guess an encoding.
PowerShell base64-decodes to UTF-16LE bytes and reconstructs the string losslessly.

The cost is length. A Windows command line is capped at 32767 characters and base64
inflates the payload to roughly 2.7× (two bytes per UTF-16LE unit, 4/3 for base64).
Beyond the cap PowerShell raises `[WinError 206] The filename or extension is too long`
and the script never starts.

`scripts/run_ps.py` uses `MAX_COMMAND_LINE_CHARS = 30000`; past that it writes a temp
`.ps1` (UTF-8 with BOM) and runs it with `-File`. **That fallback changes the file
context**, so the wrapper says so on stderr — see §2.

## 2. `run_ps.py`: two modes, do not mix them

### 2.1 Text mode (`--command` / `--file` / `--stdin` / positional)

The script **body** travels through `-EncodedCommand`. That is not `-File`, so the same
script behaves differently here and under `-File`, and the difference is the file
context (measured here):

```
powershell -File .\probe.ps1     ROOT/CMD/MINE = C:\...\中文目录
run_ps.py --file .\probe.ps1     ROOT/CMD/MINE = "" (empty)
```

`$PSScriptRoot` is empty, `$PSCommandPath` is empty, `$MyInvocation.MyCommand.Path` is
empty, so relative references like `.\helper.ps1` or `"$PSScriptRoot\x.ps1"` all fail.
Text mode suits "run a few lines and see", not a script that depends on where it lives.

When a script exceeds the command-line limit it is written to a temp file and run with
`-File`, at which point `$PSScriptRoot` becomes **the temp directory** — the same script
switches context because of its length. That fallback prints three
`run_ps.py: note:` lines on stderr telling you to use `--invoke-file`. Do not ignore
them.

### 2.2 Real-file mode (`--invoke-file <path>`)

The path goes to the child's `-File` unchanged; the file is **not read, decoded, copied
or rewritten**:

```bash
python scripts/run_ps.py --invoke-file .\script.ps1
python scripts/run_ps.py --invoke-file .\script.ps1 --script-args -Value 11
```

Measured here, same script:

```
ROOT=[C:\...\中文目录]
CMD=[C:\...\中文目录\脚本.ps1]
MINE=[C:\...\中文目录\脚本.ps1]
PARAM=11
HELPER=from-helper      # . "$PSScriptRoot\helper.ps1" works
```

Chinese directories, Chinese filenames, `param()`, `[CmdletBinding()]` and relative
dot-sourcing all behave natively. Arguments after `--script-args` are forwarded to the
script as given, still through an argv list, with no shell involved.

It does **not** inject `-ExecutionPolicy Bypass`. When policy blocks the script you get
the policy error and a non-zero exit code, not a silent bypass:

```bash
python scripts/run_ps.py --invoke-file .\script.ps1 --execution-policy Restricted
# File ... cannot be loaded because running scripts is disabled on this system.
# exit 1
```

Incompatible combinations fail loudly (exit 3) instead of being ignored: `--invoke-file`
is mutually exclusive with `--console-encoding`, `--input-encoding`, `--command`,
`--file`, `--stdin` and positional arguments. The first two rewrite file content, and
this mode promises not to.

### 2.3 Common switches

```bash
# a positional argument is the script body
python scripts/run_ps.py 'Write-Output "hello"'

# explicit long options
python scripts/run_ps.py --command 'Get-ChildItem -LiteralPath "D:\work\项目"'
python scripts/run_ps.py --file .\script.ps1
python scripts/run_ps.py - < script.ps1
echo 'Get-Date' | python scripts/run_ps.py --stdin

# choose the host
python scripts/run_ps.py --shell pwsh --command '$PSVersionTable.PSEdition'
python scripts/run_ps.py --shell powershell 'chcp'
```

Default behaviour: **inject nothing**. No `-ExecutionPolicy Bypass`, no change to
`[Console]::OutputEncoding`, no change to `$OutputEncoding`. Ask explicitly:

```bash
python scripts/run_ps.py --execution-policy Bypass --command '...'
python scripts/run_ps.py --console-encoding utf8 --command '...'
```

Input encoding defaults to `utf-8-sig` (which swallows a BOM). For non-UTF-8 source:

```bash
python scripts/run_ps.py --input-encoding gbk --file legacy.ps1
```

Timeout defaults to 300 seconds; `--timeout 0` means no limit:

```bash
python scripts/run_ps.py --timeout 30 --command '...'
```

### `--console-encoding` wraps your script

`--console-encoding` has to insert statements before your script runs. But `param(...)`
and `[CmdletBinding()]` are only legal as the **first statement** of a script or script
block, so prefixing directly makes PowerShell raise
`param : The term 'param' is not recognized` — and then **finish the remaining
statements and exit 0**, a silent failure.

So with that flag the script is wrapped as:

```powershell
<prelude>; & {
<your script>
}
```

Two visible effects: reported line numbers shift by one or more, and the body runs in a
child scope (`$script:` still targets the outer script scope, `exit` still ends the whole
process). Without `--console-encoding` the wrapper is not added and the script runs as
written.

### `#< CLIXML` may appear on stderr

When its output streams are redirected, PowerShell serialises progress records such as
`Write-Progress` as CLIXML onto stderr. It is not an error and `run_ps.py` did not add
it — those are the child's real stderr bytes. It shows up most on a first run, while
modules load.

For clean stderr, write this at the top of your own script:

```powershell
$ProgressPreference = 'SilentlyContinue'
```

`run_ps.py` does not set it for you, because that would change the script's own visible
behaviour.

## 3. Exit codes

The exit codes of `run_ps.py` are a **contract**; do not change them:

| Code | Meaning |
| --- | --- |
| the child's own | passed through untouched |
| 3 | wrapper-local failure: usage error, mutually exclusive arguments, unreadable file, input that does not decode with the declared encoding |
| 124 | timeout |
| 127 | the host named by `--shell` was not found |

Usage errors return 3 rather than argparse's default 2, because 2 would collide with "the
child exited 2". All four are covered by `tests/python/test_run_ps.py`. Version 0.x used
to return 0 for a failed child; the rewrite fixed that specifically.

## 4. Two traps of `-File`

### Trap 1: the `process` block may not run at all

Launched with `-File` and with stdin redirected by the host, Windows PowerShell 5.1
skips the `process` block while binding parameters successfully. The symptom is a script
that "ran, reported nothing, did nothing".

For tool scripts with `[Parameter(ValueFromPipeline)]`, see the fallback pattern in
`references/powershell-51.md`.

### Trap 2: `exit` does not end the process

`exit 7` inside `& child.ps1` only sets `$LASTEXITCODE`; the parent keeps running. To
surface a real exit code from a test or a wrapper, write `exit $LASTEXITCODE` explicitly.

## 5. The reality of execution policy

Agent hosts usually start with `-NoProfile -NonInteractive` but **without**
`-ExecutionPolicy`. Whether a script runs depends on the policy in effect for the
process; read it from `EXECUTIONPOLICY` in `Get-WinScriptEnvironment.ps1`.

The position of this skill: **a tool does not relax policy on the user's behalf.**

- Tools carry no `Bypass` in their defaults; the reasoning is in `references/security.md`.
- When relaxation is needed, the caller passes it explicitly, and that line should sit
  near the call site where review can see it.
- Never write `Set-ExecutionPolicy` into a script: it changes machine state, not this one
  invocation.

## 6. Which mode to pick

1. The script is already a file and needs its own location → `run_ps.py --invoke-file`
   (or plain `-File`).
2. The script is a few lines but contains Chinese → save it as a UTF-8-with-BOM `.ps1`
   and use `-File`.
3. The host blocks `-File`, or inline is mandatory → positional / `--command`, accepting
   that there is no file context.
4. The same run must cover both hosts (5.1 and 7) → one `run_ps.py` command, changing
   only `--shell`.
5. You need "tell me which files are wrong" → use the structured output and exit codes,
   never parse Chinese out of human-readable text.
