# Troubleshooting: symptom → one fix

Run `Get-WinScriptEnvironment.ps1` once and record four values: `ACP`,
`CONSOLEOUTCP`, `OUTPUTENCODING`, `PSEDITION`. Every judgement below rests on those four
values, not on recollection.

**Once is enough.** These are properties of a machine and do not drift inside a session.
A host already confirmed as ACP=936, OEMCP=936 does not need a fresh diagnosis every
round. Re-check only after changing machines, switching hosts (5.1 ↔ 7), or running
`chcp` yourself.

## 1. Locate the layer first

| Symptom | Most likely layer |
| --- | --- |
| Chinese shows as boxes or question marks in the terminal | Link 4: stdout encoding |
| The file is fine on disk but a program reads garbage | Link 1: decoding on read |
| A file you wrote cannot be read by Python or Node | Link 2: encoding on write |
| Chinese arguments reach the program as `?` | Link 3: `$OutputEncoding` |
| The whole script reports "string is missing the terminator" | Command transport: `-Command` |
| Line 1 of a `.bat` reports "is not recognized as an internal or external command" | A BOM inside a `.bat` |
| The script reports no error and does nothing | The `process` block was skipped |

## 2. Fixes, one at a time

### Terminal shows mojibake but the file is correct

Stop printing Chinese to stdout. Use ASCII labels:

```powershell
Write-Output 'VERDICT=OK'
```

When Chinese output is mandatory, align both ends first:

```powershell
$OutputEncoding = [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
```

Note this only covers **the current process**; how the host decodes is outside your
control. Production scripts emit ASCII.

### `Get-Content` returns `涓` or `锟斤拷`

```powershell
Get-Content -LiteralPath $p -Raw -Encoding UTF8
```

Root cause: 5.1 parses BOM-less files as ANSI (936). The permanent fix is saving the
file as UTF-8 with BOM (`.ps1`) or declaring the encoding explicitly (data files).

### A written txt/docx/json will not open

```powershell
[System.IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding($false)))
```

Root cause: `>`, `>>` and `Out-File` produce UTF-16LE with BOM on 5.1.

### Chinese piped to git or python becomes `?`

```powershell
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
```

Root cause: `$OutputEncoding` is `us-ascii` on 5.1 (measured: `中` becomes `3F`).

### Chinese path plus nested quotes raises "string is missing the terminator"

Do not build a `-Command` string. Save the script as a UTF-8-with-BOM `.ps1` and run it
with `-File`, or:

```bash
python scripts/run_ps.py --command '<your command>'
```

### Arguments inside `-Command` are split apart

Same as above. Also check `$PSNativeCommandArgumentPassing` (7 only): if it is
`Legacy`, switch it to `Standard`.

### Line 1 of a `.bat` says "is not recognized as an internal or external command"

The file has a UTF-8 BOM. Remove the BOM and save as GBK without BOM — see
`references/cmd-bat.md`.

### `if exist` cannot find a Chinese path inside a `.bat`

The file is not GBK. Save as ANSI/GBK (936) without BOM, or put `chcp 65001 >nul` on
line 1 with no BOM in the file.

### Exit code 0 and nothing happened

Two candidates:

1. The tool uses `begin/process/end`, was launched with `-File`, and stdin is
   redirected — so the `process` block never ran. Add the fallback in `end` (see
   `references/powershell-51.md`).
2. `exit 7` inside `& child.ps1` only sets `$LASTEXITCODE`; the parent process
   continues.

Diagnosis: have the script print `files=<n>` in `end`. If `n` is 0 while arguments
clearly arrived, it is case 1.

### Python raises `UnicodeDecodeError`

```python
open(path, encoding="utf-8")   # on every open
```

If the file really is GBK, write `encoding="gbk"`. Never rely on environment variables.

### Python `print()` raises `UnicodeEncodeError`

In a bare environment `sys.stdout.encoding` is `gbk` (measured). Add:

```python
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
```

Or print ASCII only.

### The same Python script works under the agent but not on double-click

The agent host sets `PYTHONUTF8=1`; the user environment does not. Measured, two
environments write UTF-8 and GBK bytes respectively for
`open(p,'w').write('中文')`. Fix per `references/python.md`: hard-code `encoding=`.

### `git status` shows Chinese filenames as `\344\270\255`

```bash
git -c core.quotepath=false status
```

Display only; the repository content is intact.

### `New-EncodedScript.ps1` raises `UNREPRESENTABLE_CHARACTER`

The target encoding cannot express a character in the source text (emoji into GBK, for
example). This is **deliberate**: fail rather than silently substitute `?`. Switch to
`utf8-nobom` or `utf8-bom`.

### `Test-ScriptEncoding.ps1` exits 3

Argument or I/O problem: missing path, a directory, unreadable file. Read the stderr
code — `ERROR=NOT_FOUND` / `ERROR=IS_DIRECTORY` / `ERROR=READ_FAILED`.

### The two versions disagree

First check the syntax list in `references/dual-version-compatibility.md` — those are
**parse-time** errors that `try/catch` cannot catch on 5.1.

### `Test-ScriptEncoding.ps1` reports `PAYLOAD_VALID=False`

A BOM is present but the bytes after it are not valid UTF-8 / UTF-16. The file is
broken; the detector is not being strict:

```text
ENCODING=utf8-bom-invalid
PAYLOAD_VALID=False
PAYLOAD_PROBLEM=UTF-8 BOM followed by invalid UTF-8 at byte 3: ...
```

The only fix is rewriting: save the content as UTF-8 again. Do not touch the BOM and do
not treat the file as ASCII — something like `EF BB BF FF` runs its first half on 5.1
and exits 0.

### The detector reports `WARN` for a UTF-16 file

UTF-16LE/BE with BOM runs on both versions, hence `WARN` rather than `FAIL`. WARN means
"it runs, do not use it": `git diff` treats it as binary, editors read mojibake, and
`cmd.exe` does not recognise it at all. Convert by saving as UTF-8 with BOM.

`FAIL` is reserved for UTF-16 **without** BOM (`UTF16_NO_BOM`) — that genuinely does
not run, and exits 0 while doing so.

### `$PSScriptRoot` is empty under `run_ps.py --file`

Text mode has no file context by design: the body travels through `-EncodedCommand`
and no such script exists on disk. Use the real-file mode:

```bash
python scripts/run_ps.py --invoke-file .\script.ps1
```

### `run_ps.py` prints three `note:` lines on stderr and `$PSScriptRoot` becomes a temp directory

The script exceeded the command-line limit and was written to a temp file, then run with
`-File`. That is the only legal degradation, but the context changed, so it says so.
Switch to `--invoke-file` for the real location.

### `run_ps.py` says `--invoke-file cannot honour ...`

`--invoke-file` is mutually exclusive with `--console-encoding` / `--input-encoding` /
`--command` / `--file` / `--stdin`: those rewrite the script body while the real-file
mode promises not to. Drop one side.

### The writer reports `REPLACE_FAILED`

The temp file was written and read back correctly, but replacing the target failed —
usually a read-only or locked target. The original file is untouched and the error
carries the original .NET message.

### `New-EncodedScript.ps1` wrote an encoding I did not ask for

Without `-Encoding` the choice follows the extension: `.ps1/.psm1/.psd1` → `utf8-bom`,
`.bat/.cmd` → `gbk`, everything else → `utf8-nobom`. The result carries
`ENCODING_SOURCE=extension|explicit` to tell you which rule applied.

## 3. Three-step location

1. **Look at the machine**: `Get-WinScriptEnvironment.ps1` → four code pages plus the
   version.
2. **Look at the file**: `Test-ScriptEncoding.ps1 -Path <file>` → read `ENCODING=` and
   `VERDICT=`, not just the conclusion.
3. **Look at the transport**: rerun the Chinese-bearing call through `run_ps.py`. If it
   then works, the fault is in the command-line layer.

## 4. Do not do these

- Do not "fix" file encoding with `chcp 65001`: that changes the window, not the file.
- Do not re-probe the environment in a trial-and-error loop: four values settle it.
- Do not treat "reinstall PowerShell 7" as a solution: 5.1 remains, and so do its traps.
- Do not change `ACP` after fixing a symptom: that is system state, not a product of
  this task.
