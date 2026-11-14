# Dual-version compatibility: one script on both 5.1 and 7

There is one rule: **either use only what 5.1 also understands, or fork at runtime.
Never mix 7-only syntax into a file that must also run on 5.1.**

The reason is parse timing: 7-only syntax is a **parse error** on 5.1, `try/catch`
cannot intercept it, and the file never starts executing. The graceful degradation
you imagined does not exist.

## 1. Syntax that 5.1 cannot parse

| Construct | Available from | What 5.1 does |
| --- | --- | --- |
| `$a ? $b : $c` ternary | 7.0 | parse error |
| `$a ?? $b` / `$a ??= $b` null-coalescing | 7.0 | parse error |
| `cmd1 && cmd2` / `cmd1 \|\| cmd2` | 7.0 | parse error |
| `Get-Content -AsByteStream` | 6.0 | parameter does not exist (use `-Encoding Byte`) |
| `Join-Path -AdditionalChildPath` | 6.0 | parameter does not exist |
| `ConvertFrom-Json -AsHashtable` | 6.0 | parameter does not exist |
| `Out-File -Encoding utf8BOM` | 6.0 | value not in the set |
| `ForEach-Object -Parallel` | 7.0 | parameter does not exist |
| `$IsWindows` / `$IsLinux` / `$IsMacOS` | 6.0 | variable does not exist (error under StrictMode) |
| `[System.Text.Encoding]::Latin1` | .NET Core | property does not exist |
| `Test-Json` | 6.1 | command does not exist |

## 2. Behaviour that differs while staying syntactically valid

These are more dangerous than the parse errors: the script runs and writes different
bytes.

| Item | 5.1 | 7 |
| --- | --- | --- |
| Encoding used to parse a BOM-less `.ps1` | system ANSI (936) | UTF-8 |
| `Out-File` / `>` default | UTF-16LE with BOM | UTF-8 without BOM |
| `Set-Content` / `Add-Content` default | ANSI without BOM | UTF-8 without BOM |
| `Set-Content -Encoding UTF8` | **with** BOM | **without** BOM |
| `$OutputEncoding` | `us-ascii` | `utf-8` |
| `[Encoding]::Default` | ANSI (936) | `utf-8` |
| `Get-Content` on a GBK file | correct | four `U+FFFD` |
| `Join-Path $a 'b' 'c'` (three arguments) | `A positional parameter cannot be found` | works |

Every row above is backed by measurement; payloads and bytes are in
`references/encoding-matrix.md`.

## 3. What works on both

### 3.1 Stay in the intersection

```powershell
#Requires -Version 5.1
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Utf8Bom = New-Object System.Text.UTF8Encoding($true)

# path joining both versions understand
$dir = Join-Path (Join-Path $root 'sub') 'file.txt'
# or
$dir = [System.IO.Path]::Combine($root, 'sub', 'file.txt')

# encoding expressed the same way on both
[System.IO.File]::WriteAllText($path, $text, $Utf8NoBom)
```

### 3.2 When you must fork, branch on the version first

```powershell
$isCore = $PSVersionTable.PSEdition -eq 'Core'

if ($isCore) {
    $bytes = Get-Content -LiteralPath $path -AsByteStream -TotalCount 4
}
else {
    $bytes = Get-Content -LiteralPath $path -Encoding Byte -TotalCount 4
}
```

The catch: 7-only syntax has to live **inside a separate function or a string in a
separate file**, never on the common code path, or 5.1 fails to parse the file at all.
If you truly need to execute 7-only code, defer parsing with `[scriptblock]::Create()`,
or launch a child process against another file.

## 4. On-disk encoding

A cross-version script itself must be **UTF-8 with BOM** (see
`references/powershell-51.md`, first broken link). That is the recommended spelling,
not the only runnable one: measured, UTF-16LE/BE with BOM parses and runs on both
versions, but git, editors and `cmd.exe` cannot read it, which is why the detector
returns `WARN` instead of `FAIL`. Saving as UTF-16 is not "wrong", it is "usable only
by itself".

Do not drop the BOM to make things cleaner on 7. That is giving up 5.1.

## 5. How to verify

Do not rely on "I remember that is unsupported". Write a probe, run it on both hosts,
compare the output.

What this project does:

```powershell
# same script, two hosts
powershell.exe -NoProfile -File tests\run-all.ps1 -Suite pester
pwsh.exe       -NoProfile -File tests\run-all.ps1 -Suite pester
```

`tests/run-all.ps1` resolves the current host through `(Get-Process -Id $PID).Path`
and every child suite runs on that same edition, so "all green on 5.1" and "all green
on 7" are two runs of one command, not two manual procedures.

For CI, make `runs-on` and the shell a matrix — see `.github/workflows/test.yml`.

## 6. Common misjudgements

- **"I tested it on 7"** — passing on 7 says nothing about 5.1, especially for
  encoding.
- **"Adding `#Requires -Version 7.0` makes it safe"** — that only fails early, it is
  not compatibility. A dual-version script wants `#Requires -Version 5.1`.
- **"Wrapping it in `$PSVersionTable.PSVersion.Major -ge 7` is enough"** — that guards
  the runtime branch; parsing still fails. `if ($true) { $a ? $b : $c }` is a parse
  error on 5.1 regardless.
- **"`-Encoding UTF8` is the portable spelling"** — it writes different bytes on each
  version. This is the single easiest thing to miss in a dual-version script.
