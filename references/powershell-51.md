# Windows PowerShell 5.1 (Desktop)

5.1 is not "an older PowerShell". Four of its **default behaviours** around encoding
run against intuition. This project calls them the four broken links, because a break
anywhere on the chain surfaces as "mojibake" or "the file will not open" — yet each one
has a different fix.

## 1. The four broken links

### Link 1 — reading: a BOM-less UTF-8 file is parsed as ANSI

The `.ps1` file itself: the parser checks the BOM first. `EF BB BF` means UTF-8,
`FF FE` means UTF-16LE, `FE FF` means UTF-16BE. **With no BOM it falls back to the
system ANSI code page**, which is 936 on zh-CN.

Measured, a UTF-8 file without BOM containing only `中` (U+4E2D):
- `Get-Content` with defaults reads code point `28051` (`U+6D93`) — not an error, a
  wrong character
- `Get-Content -Encoding UTF8` reads `20013`, which is correct

The same applies to Chinese literals and comments inside the script. If the file has no
BOM the strings are already wrong; no runtime repair helps.

UTF-16 deserves its own sentence because the folklore is wrong: **5.1 does run UTF-16
scripts with a BOM**, both LE and BE, with correct Chinese in measurement. What fails
is UTF-16 **without** a BOM (split per byte, dead at the first character). Running is
not a reason to use it — `cmd.exe`, `git diff` and most editors read single bytes. See
`references/encoding-matrix.md` §3.1.

### Link 2 — writing: `>`, `>>` and `Out-File` produce UTF-16LE with BOM

Measured with a two-character payload:
- `$s > f` and `$s | Out-File f` both write `FF FE 2D 4E 87 65 …`, i.e. UTF-16LE
- `Set-Content` fails differently: a new file lands as ANSI (`D6 D0 CE C4`)
- `Add-Content` matches `Set-Content`

Consequence: Python's `json.load`, Node's `fs.readFileSync` and `git diff` either crash
or read mojibake. And `-Encoding UTF8` on 5.1 **adds a BOM**, the opposite of 7.

### Link 3 — piping to a native program: `$OutputEncoding` is `us-ascii`

Measured: `[char]0x4E2D | python -c "..."` receives `3F` on stdin, i.e. `?`. Non-ASCII
is replaced with a question mark the moment it leaves PowerShell, **with no warning**.

**This only affects piped stdin, not command-line arguments.** The distinction is
routinely stated wrongly, so it is worth splitting out:

| Channel | Who decides the encoding | Does `$OutputEncoding` matter? |
| --- | --- | --- |
| Piped stdin (`... \| native.exe`) | `$OutputEncoding`, `us-ascii` by default | Yes — this is the truncation point |
| Command-line arguments (`native.exe 中文`) | `CreateProcess` passes wide characters; the process converts | No |
| PowerShell's own stdout | `[Console]::OutputEncoding` | No |
| File writes (`Out-File` / `>`) | the `-Encoding` parameter, UTF-16LE by default | No |

So when mojibake appears, first establish which layer broke. Chinese in arguments
arrives whole even when `$OutputEncoding` is `us-ascii`; conversely, setting
`$OutputEncoding` to UTF-8 does not fix the argument layer — problems there come from
the target program decoding argv with the ACP, or from how the caller passed it. stdin,
stdout, files and argv are four separate encodings and none compensates for another;
check them one at a time.

### Link 4 — its own stdout: encoded with the console output code page

5.1 writes stdout using `[Console]::OutputEncoding`, which comes from the console output
code page (936 / gb2312 on a normal zh-CN console). A host that decodes those bytes as
UTF-8 gets the classic `锟斤拷`.

Measured caveat: on a session where the host switched to 65001, 5.1's
`[Console]::OutputEncoding` followed to `utf-8`. So **do not memorise "5.1 is gb2312"** —
read the current value with `Get-WinScriptEnvironment.ps1`.

## 2. The four correct forms

```powershell
#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# read: declare the encoding, do not let the parser guess
$text = Get-Content -LiteralPath $path -Raw -Encoding UTF8

# write: temp file -> read back -> atomic replace
[System.IO.File]::WriteAllText($temp, $text, $Utf8NoBom)
$back = [System.IO.File]::ReadAllText($temp, $Utf8NoBom)
if ($back -cne $text) { throw 'VERIFY_FAILED' }
[System.IO.File]::Replace($temp, $path, $backupPath, $true)

# before piping to a native program, switch it to UTF-8
$OutputEncoding = $Utf8NoBom
```

That sequence is exactly what `scripts/New-EncodedScript.ps1` implements, including the
detail that `File.Replace` needs a real backup path — passing `$null` binds to an empty
string and raises `The path is not of a legal form`.

## 3. Other 5.1 behaviour you have to know

### The `process` block may not run at all

When launched with `-File` and the host has redirected stdin, 5.1 **skips the `process`
block** while still binding parameters successfully. The symptom is
`files=0 exit=0` — a silent false pass.

Tool scripts either avoid `begin/process/end` or add a fallback in `end`:

```powershell
process { $script:pipelineRan = $true; ... }
end { if (-not $script:pipelineRan) { ... handle $Path ... } }
```

This was measured on this project: the integration suite was green for a while because
the detector never looked at the file.

### Three-argument `Join-Path` does not exist

`Join-Path $a 'b' 'c'` raises
`A positional parameter cannot be found that accepts argument 'b'` on 5.1. Use
`Join-Path (Join-Path $a 'b') 'c'` or `[IO.Path]::Combine($a,'b','c')`.

### `exit` inside a child script does not terminate the process

`exit 7` inside `& child.ps1` only sets `$LASTEXITCODE` to 7; the parent keeps going.
Measured. To surface a real exit code from a test, write `exit $LASTEXITCODE`
explicitly.

### Code page provider

`[Text.Encoding]::GetEncoding(936)` works out of the box on .NET Framework. On .NET
Core it needs `CodePagesEncodingProvider` (PowerShell 7 registers it; a bare host may
not). Tool scripts wrap it in try/catch and register explicitly — see
`Get-CodePageEncoding` in `scripts/Test-ScriptEncoding.ps1`.

### `[Encoding]::Default`

On 5.1 it equals the system ANSI code page (`gb2312` measured here). On 7 it is always
`utf-8` and carries no information about the machine — so "probe the ACP with
`[Encoding]::Default`" holds only on 5.1.

## 4. Do not do these

- Do not "fix" 5.1 mojibake with `chcp 65001`: that changes the console code page, not
  `Out-File`'s UTF-16LE and not `$OutputEncoding`'s us-ascii.
- Do not rely on `$PROFILE`: agent hosts start with `-NoProfile`.
- Do not treat `[Console]::OutputEncoding` as an in-script encoding setting: it governs
  stdout only.
- Do not expect to "upgrade" 5.1 to 7: it is an OS component with no in-place path.
