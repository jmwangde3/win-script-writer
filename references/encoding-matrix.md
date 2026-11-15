# Encoding matrix: which file takes which encoding

A lookup table. Every row marked *measured* is bytes actually produced on this zh-CN /
CP936 host or in CI.

## 1. Four settings that are not the same thing

| Name | Meaning | Who uses it | Where to read it |
| --- | --- | --- | --- |
| ACP | system ANSI code page | 5.1 parsing a BOM-less script; `Encoding.Default` (.NET Framework) | `ACP` from `Get-WinScriptEnvironment.ps1` |
| OEMCP | system OEM code page | cmd.exe parsing a batch file; the console's default character set | `OEMCP`, same tool |
| Console code page | the current window's input/output code page | what `chcp` changes; `[Console]::OutputEncoding` follows it | `CONSOLEOUTCP`, same tool |
| `$OutputEncoding` | encoding used when PowerShell writes a string to a **native program's stdin** | piped input only: `'中文' \| git hash-object --stdin` | `OUTPUTENCODING`, same tool |

All four come from `Get-WinScriptEnvironment.ps1`. Typical here: ACP=936, OEMCP=936, the
console output code page possibly switched to 65001 by the host, `$OutputEncoding` =
`us-ascii` on 5.1 and `utf-8` on 7.

### 1.1 Four kinds of "encoding", never conflated

Each breaks differently. **File** encoding is set by whoever wrote it, and breaks when a
reader decodes it otherwise (§2). **Console** encoding is `chcp` /
`[Console]::OutputEncoding`, and breaks when a host decodes stdout with the wrong one.
**Pipeline** encoding is `$OutputEncoding`, applying **only** to a native program's
stdin. **Command-line** encoding is UTF-16 via `CreateProcessW`, and breaks only when a
command becomes **bytes** handed to a shell (a GBK `.bat`, a hand-built string).

**`$OutputEncoding` plays no part in argv.** Arguments reach the child as Unicode;
`'中文'` as an argument never passes through it. It governs the stdin of the native
program on the right of `|`. The widespread advice "change `$OutputEncoding` to fix
Chinese arguments" merges two separate things: measured here,
`-Command 'Write-Output "中文"'` is correct on both 5.1 and 7 regardless of its value.

**Rule: when you see mojibake, first ask which of these four broke. Never say
"encoding problem" as if it were one thing.**

## 2. File type → encoding

| File | Save as | BOM | Why |
| --- | --- | --- | --- |
| `.ps1` / `.psm1` / `.psd1` with non-ASCII | UTF-8 | **required** | 5.1 parses BOM-less as ACP (936); 7 parses BOM-less as UTF-8. With a BOM both agree |
| `.ps1` / `.psm1` / `.psd1`, pure ASCII | UTF-8 or ASCII | irrelevant | with no non-ASCII bytes the BOM is the only difference |
| `.bat` / `.cmd` | ANSI (GBK 936) | **must not have one** | cmd.exe does not recognise a BOM; `<EF BB BF>@echo` becomes "not recognized as an internal or external command" |
| `.bat` / `.cmd`, UTF-8 mandatory | UTF-8 | **must not have one**, first line `chcp 65001 >nul` | works on this host; older Windows 10 has defects in `for /f` and pipes under 65001 — retest elsewhere |
| `.py` | UTF-8 | **no** | PEP 263 defaults to UTF-8; a BOM breaks "first line" tooling |
| `.sh` / `.bash` | UTF-8 | **no** | the BOM lands before the shebang and the file stops being executable |
| `.json` / `.yaml` / `.ini` / `.csv` | UTF-8 | **no** | many parsers reject a BOM outright |
| data files read by other programs | UTF-8 | **no** | an explicit `latin` beats the system default |
| any `.ps1` as UTF-16LE/BE | do not | a BOM is needed to run at all | see §3.1: it executes, nobody can review it, and retooling costs more than it saves |

One-line rule: **only scripts that 5.1 must run need a BOM; everything else takes
none.**

### 2.1 Python source encoding declarations (PEP 263)

A `# coding: <name>` comment in the first two lines overrides UTF-8, and the verdict on it
is decided by the interpreter, not by "does it decode": unique match is `WARN`, a second
family that also decodes is `WARN` + `AMBIGUOUS`, and only bytes the declared codec
cannot decode are `FAIL`. The table (18 measured declaration cases), the eight reason
codes and the four `Support` states are in `references/python-source-encoding.md`; the
byte-level evidence is in `references/appendix-codec-evidence.md`.

Two rows that belong in this file's own frame: a `.py` that declares a codec other than
`utf-8` / `utf-8-sig` while carrying a BOM is always `FAIL` + `BOM_CONFLICT`, and a
non-UTF-8 `.py` with no declaration at all is `FAIL` + `CP936_PYTHON` — the interpreter
refuses both outright.

### 2.2 GBK, GB2312, HZ and GB18030 are not one encoding

These four families are often treated as "four spellings of 936". Measured, they are
not:

- **GB2312** (EUC-CN) is a proper subset of GBK: 7445 double-byte cells with holes in
  the grid.
- **HZ-GB-2312** is the 7-bit escaped form of GB2312 (`~{` … `~}`); **the file contains
  no high bytes at all**, so a detector that only asks "is there a non-ASCII byte" calls
  it pure ASCII.
- **GB18030** adds 4-byte sequences on top of GBK; every valid GBK byte sequence is also
  valid GB18030.
- **GBK** is a close relative of CP936 but **not equal** to it — they differ in 2149
  cells, see `references/appendix-codec-evidence.md` §2.

So "verify GB2312 with CP936" passes files Python rejects, and HZ stays invisible;
folding GB2312 into GBK produces false alarms. The rule is that **the declaration must
match the bytes**, not that "it decodes" — a UTF-8 file declaring `coding: gbk` also
decodes, as mojibake. Both steps (`Test-CodingDecodes` + `Test-PythonCodingAgrees`) must
pass before `WARN`. This project still saves its own `.py` as UTF-8.

## 3. BOM byte signatures

| Encoding | Leading bytes | Note |
| --- | --- | --- |
| UTF-8 with BOM | `EF BB BF` | what this skill requires of `.ps1` |
| UTF-8 without BOM | no signature | decidable only by strict UTF-8 validity |
| UTF-16 LE | `FF FE` | what 5.1's `Out-File` / `>` produce by default |
| UTF-16 BE | `FE FF` | rare but real |
| UTF-32 LE | `FF FE 00 00` | **must be matched before `FF FE`**, or it is read as UTF-16LE |
| UTF-32 BE | `00 00 FE FF` | same: the four-byte signature wins |
| GBK / CP936 | no signature | Chinese is two bytes, lead `81–FE`, trail `40–FE` |

Four-byte signatures come first: the leading two bytes of `FF FE 00 00` are `FF FE`, so
a two-byte-first implementation reports UTF-32LE as "corrupt UTF-16LE". The detector
tests four bytes and fails UTF-32 with `UTF32_UNSUPPORTED` — no runtime reads UTF-32
source.

CP936 in .NET has **no undefined bytes**: `0xFF` maps to `U+F8F5`, so "not valid UTF-8"
proves nothing about GBK. A file is labelled `gbk` only on a byte-exact CP936 round
trip, and even then at `confidence=medium`.

## 3.1 "Runs" and "recommended" are different questions

A BOM records what the producer declared, not whether the content is legal text.
Failing to separate the two errs in both directions: a broken file marked OK, or a
runnable file marked unusable. The table below was produced by running 5.1.26100 and
7.7.0 once each:

| Form | Parses and runs? | Recommended | Detector |
| --- | --- | --- | --- |
| UTF-8 + BOM, content is valid UTF-8 | yes | ✅ the standard `.ps1` form | `OK` |
| UTF-8 + BOM, content invalid (`EF BB BF FF`) | runs half the file, errors, exits 0 | ❌ the file is already corrupt | `FAIL` (`INVALID_ENCODING_PAYLOAD`) |
| UTF-16LE + BOM | yes, Chinese correct | ⚠️ runs, do not use | `WARN` |
| UTF-16BE + BOM | yes, Chinese correct | ⚠️ runs, do not use | `WARN` |
| UTF-16 without BOM | **no**: split per byte, dead at the first character, still exits 0 | ❌ | `FAIL` |
| UTF-16 + BOM with an odd byte count or a lone surrogate | runs the readable first half, exits 0 | ❌ not text | `FAIL` |

Two conclusions: **"PowerShell does not support UTF-16 scripts" is wrong** — LE/BE with a
BOM both run, and the objection is ecosystem-wide (`cmd.exe`, `git diff` and most editors
read single bytes, so nobody can review it). And **exit code 0 does not prove success**:
three rows above run or half-run and all exit 0, so readability lives only in the bytes —
which is why this detector exists.

## 4. Measured write behaviour (same line, different bytes per version)

Payload is two Chinese characters (U+4E2D U+6587), content two lines. The table lists
**actual bytes on disk**.

| Expression | Windows PowerShell 5.1 | PowerShell 7.6 |
| --- | --- | --- |
| `$s \| Out-File -Path f` | `FF FE …` UTF-16LE + BOM | UTF-8 without BOM |
| `$s > f` | `FF FE …` UTF-16LE + BOM | UTF-8 without BOM |
| `Set-Content -Path f -Value $s` | `D6 D0 CE C4` GBK without BOM | UTF-8 without BOM |
| `Set-Content … -Encoding UTF8` | `EF BB BF …` **with BOM** | UTF-8 **without BOM** |
| `Add-Content -Path f -Value $s` | `D6 D0 CE C4` GBK without BOM | UTF-8 without BOM |
| `Out-File … -Encoding utf8` | `EF BB BF …` **with BOM** | UTF-8 **without BOM** |
| `[IO.File]::WriteAllText(f, $s)` | UTF-8 without BOM | UTF-8 without BOM |
| `[IO.File]::WriteAllText(f, $s, $utf8NoBom)` | UTF-8 without BOM | UTF-8 without BOM |

Two points:

1. `-Encoding UTF8` **writes different bytes** on 5.1 and 7 (one has a BOM, one does
   not). Never use it in a cross-version script to mean "with BOM" or "without BOM" —
   construct `UTF8Encoding($true/$false)` explicitly.
2. `WriteAllText` without an encoding argument also writes UTF-8 without BOM on .NET
   Framework 4.x, but that is an implementation detail, not a contract — pass
   `$utf8NoBom` so readers do not guess.

## 5. Measured read behaviour

| Scenario | 5.1 default `Get-Content` | 5.1 `-Encoding UTF8` | 7 default |
| --- | --- | --- | --- |
| UTF-8 without BOM | **mojibake** (decoded as 936) | correct | correct |
| UTF-8 with BOM | correct | correct | correct |
| GBK file | correct | mojibake | **all U+FFFD** |

7 reads a GBK file as replacement characters (measured: four `U+FFFD`), **not an
error** — "read a GBK config with 7" loses data silently, so stop it at detection.

## 6. Decision flow

1. `Get-WinScriptEnvironment.ps1` — confirm ACP, console code page, `$OutputEncoding`.
2. `Test-ScriptEncoding.ps1 -Path <file>` — read `ENCODING=`, `BOM=`, `STRICT_UTF8=`,
   `PAYLOAD_VALID=`, `GBK_ROUNDTRIP=`, not just the verdict. For `.py` also
   `SOURCE_CODING`, `_NAME`, `_SUPPORT`, `_KIND`, plus `_PAYLOAD=unverified` under
   `python-only`.
3. Pick the target from §2 and write with `New-EncodedScript.ps1`, never an editor's
   "save as". Without `-Encoding` it chooses by extension (`.ps1/.psm1/.psd1` →
   `utf8-bom`, `.bat/.cmd` → `gbk`, else `utf8-nobom`), reporting
   `ENCODING_SOURCE=extension`.
4. Detect again: require `VERDICT=OK`, exit 0. When execution matters, do not stop at
   the detector.
