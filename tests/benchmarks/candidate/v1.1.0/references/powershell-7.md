# PowerShell 7 (Core)

7 fixes three and a half of the four bad defaults in 5.1 — **not all of them** — and it
fixes them in a way that makes the same script write different bytes on each version.
This page covers only the encoding-related differences and the cases that still break
on 7.

## 1. What 7 got right

| Item | 5.1 | 7.4+ |
| --- | --- | --- |
| What a BOM-less `.ps1` is parsed as | system ANSI (936) | UTF-8 |
| `Out-File` / `>` / `>>` default | UTF-16LE with BOM | UTF-8 without BOM |
| `Set-Content` / `Add-Content` default | ANSI (936) without BOM | UTF-8 without BOM |
| `$OutputEncoding` | `us-ascii` | `utf-8` |
| `[Encoding]::Default` | ANSI (936) | `utf-8` (carries no information) |
| `-Encoding UTF8` | with BOM | without BOM |

Payload is two Chinese characters; the resulting bytes are in
`references/encoding-matrix.md` §4.

Note the last row: `-Encoding UTF8` **writes different bytes** on each version. Do not
use it in a cross-version script — construct the encoding explicitly with
`New-Object System.Text.UTF8Encoding($true|$false)`.

### UTF-16 scripts: they run, do not use them

Like 5.1, 7 parses and runs UTF-16LE / UTF-16BE scripts with a BOM (Chinese comes out
correct in measurement). Without a BOM they fail: the file is split per byte, the first
character kills it, and the exit code is still 0.

"Runs" is not a reason. `git diff` treats a UTF-16 file as binary, most editors and
`Select-String` read mojibake, and a repository holding UTF-16 scripts has no
reviewable diffs. That is why the detector returns `WARN` rather than `OK` for them.

## 2. What still breaks on 7

### Reading a GBK file: silent replacement characters

7 reads BOM-less files as UTF-8. A GBK-encoded `.ps1` or `.json` does not error on 7 —
each invalid byte becomes `U+FFFD`. Measured with two Chinese characters (4 bytes in
GBK): `65533,65533,65533,65533`.

The result is worse than a crash: Chinese in a config file becomes four replacement
boxes and the program keeps running.

Rule: any input file that might be GBK gets checked with `Test-ScriptEncoding.ps1` for
`utf8-nobom` or `ascii` before 7 touches it.

### Console code page inherited from 5.1

7 sends its own stdout as UTF-8, but `[Console]::InputEncoding` can still inherit the
console's 936. When 7 hands stdin to a native program, that boundary may still decode
as 936.

Rule: when passing Chinese across processes, do not rely on defaults — write
`-Encoding utf8` explicitly or use `scripts/run_ps.py`.

### No need for base64 beyond `-EncodedCommand`

`-File` plus a UTF-8-with-BOM script is enough on 7. base64 is only needed when the
command line itself is untrustworthy (see `references/execution.md`).

## 3. Three switches worth knowing on 7

### `$PSNativeCommandArgumentPassing`

This variable exists on newer 7.x (it does not exist on 5.1); measured `Windows` on
7.6.9 here. It decides how PowerShell passes arguments to native programs: `Legacy` is
the old behaviour (re-join the command line, swallow quotes), `Standard` is the new
one, `Windows` is the default compromise on this platform.

When arguments containing quotes or Chinese misbehave on the way to `git.exe`, check
this value first:

```powershell
$PSNativeCommandArgumentPassing   # want Standard or Windows, not Legacy
```

To change it locally: `$PSNativeCommandArgumentPassing = 'Standard'` (applies in the
script scope). A cross-version script must test for existence before reading it, or
5.1 raises a missing-variable error.

### `$PSStyle` and output decoration

Newer 7.x adds ANSI escape sequences to `Write-Host` and error records by default;
measured `Host` for `$PSStyle.OutputRendering` on 7.6.9 here. Redirected output then
carries `ESC[` bytes and dirties downstream diffs. For batch work:

```powershell
$PSStyle.OutputRendering = 'PlainText'
```

Again: does not exist on 5.1.

### The full set of `-Encoding` values

Measured on 7.6.9, `Set-Content` / `Out-File` accept these names:

| Value | Bytes written (single Chinese character) | Note |
| --- | --- | --- |
| `utf8` | `E4 B8 AD` | no BOM, same as `utf8NoBOM` |
| `utf8NoBOM` | `E4 B8 AD` | no BOM |
| `utf8BOM` | `EF BB BF E4 B8 AD` | with BOM |
| `ansi` | `D6 D0` | system ANSI, GBK here |
| `oem` | `D6 D0` | system OEM, also 936 here |
| `bigendianutf32` | `00 00 FE FF …` | rare; listed only to show the breadth |

When you want a BOM use `utf8BOM`; 5.1 does not accept that value, so cross-version
code is still safest with the `UTF8Encoding` constructor.

## 4. Writing a 7-only script

```powershell
#Requires -Version 7.4
$ErrorActionPreference = 'Stop'

# be explicit on both read and write; do not lean on "7 is UTF-8 anyway"
$text = Get-Content -LiteralPath $path -Raw -Encoding utf8
[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))

# settle the pipeline encoding before handing data to a native program
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
```

"7 defaults to UTF-8" is a statement about a **default**, not a **guarantee**: a user
profile, a host, or `chcp` can change it. A 7-only script still writes its encodings
explicitly.

## 5. Three things to stop doing

- Do not add a BOM to a 7-only script for 5.1's sake: it is unnecessary and some tools
  treat it as content (any parser that reads "the first line").
- Do not use `[Encoding]::Default` to detect the machine code page: it is always utf-8
  on 7.
- Do not assume installing 7 fixes 5.1: when the caller starts 5.1 by absolute path, 7
  plays no part.
