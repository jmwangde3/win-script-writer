# Git Bash / MSYS2

The cleanest link in the chain. UTF-8 is the default there, and Chinese paths work —
the boundary is the moment you call a Windows program from Bash.

## 1. Environment baseline (measured on this host)

```
LANG=en_US.UTF-8
LC_ALL=C.UTF-8
MSYSTEM=UCRT64
```

`printf '中文\n' > 中文测试.txt` lands as `E4 B8 AD E6 96 87 0A`, and `cat` reads it
back correctly. **Inside Bash no encoding handling is needed at all.**

Declare it per script rather than trusting the caller:

```bash
#!/usr/bin/env bash
set -euo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8
```

Prefer `C.UTF-8` over `en_US.UTF-8`: the former always exists in Git Bash, the latter
depends on whether that locale was generated.

## 2. Two path spellings

| Spelling | Who understands it |
| --- | --- |
| `/h/AI工作区/project` | MSYS programs (bash, coreutils, git, grep…) |
| `H:/AI工作区/project` or `H:\AI工作区\project` | Native Windows programs (`python.exe`, `powershell.exe`…) |

**MSYS rewrites the argument when it hands it to a native program**: pass
`/h/temp/x.txt` to `python.exe` and it receives `H:/temp/x.txt`. Measured:

```
python.exe -c "print(sys.argv[1])" /h/temp/中文测试.txt
  -> H:/temp/中文测试.txt          (rewritten, correct)
MSYS_NO_PATHCONV=1 python.exe ...
  -> /h/temp/中文测试.txt          (rewriting off, native program cannot use it)
```

Rules of thumb:

- Passing to a native program → either spelling works, but do **not** rewrite it
  yourself on top.
- Passing to an MSYS program → must be `/h/...`; `H:/...` is rejected.
- When an argument looks like a path but is not one (`-X`, `//server/share`), disable
  rewriting locally with `MSYS_NO_PATHCONV=1`, never globally.

## 3. Chinese filenames turn into `\344\270\255` in git

`core.quotepath` is on by default, so `git status` / `git diff` escape non-ASCII
filenames as octal:

```
git diff --cached --name-only
  -> "\344\270\255\346\226\207\346\226\207\344\273\266.txt"

git -c core.quotepath=false diff --cached --name-only
  -> 中文文件.txt
```

Two ways to handle it:

```bash
# see the real names for one command
git -c core.quotepath=false status

# or turn it off for this machine (changes display in every repo, use with care)
git config --global core.quotepath false
```

This is **display only**: committed paths are UTF-8 bytes either way, so repository
content does not change.

## 4. Calling PowerShell from Bash

```bash
# preferred: put the script on disk and run it with -File
powershell.exe -NoProfile -NonInteractive -File "H:/work/step1.ps1"

# with Chinese arguments: do not build a -Command string
powershell.exe -NoProfile -Command "Write-Output '中文'"   # may already be broken
```

The content of `-Command` is decoded through the command line, so Chinese text and
nested quotes corrupt in transit. With Chinese involved, use `-File` on a UTF-8-with-BOM
`.ps1`, or go through `scripts/run_ps.py` (see `references/execution.md`).

The reverse direction (PowerShell calling bash) is the same story: convert paths to
`/h/...` and pass strings through a file.

## 5. Reading files a Windows program wrote

A Windows program may produce:

- UTF-16LE with BOM (PowerShell 5.1 `Out-File`) — `cat` shows a null byte between
  every character, `file` reports `Little-endian UTF-16 Unicode text`
- GBK (cmd's `echo 中文 > f`) — shows up as a run of `\xD6\xD0...`
- UTF-8 without BOM — fine as is

Procedure: `od -An -tx1 file | head -1` to see the first bytes, then decide between
`iconv -f UTF-16LE -t UTF-8`, `iconv -f GBK -t UTF-8`, or reading it directly.

Never use `cat` as the evidence: terminal mojibake can be wrong content or wrong
terminal decoding, and the two are indistinguishable on screen.

## 6. Splitting work with PowerShell

| Task | Use |
| --- | --- |
| Text processing, batch renames, grep/sed/awk | Bash |
| Registry, services, COM, WMI, scheduled tasks | PowerShell |
| Byte manipulation through `.NET` types | PowerShell |
| Must run on double-click | Neither — see `references/cmd-bat.md` |

Do not force Windows system operations into Bash for the sake of one language — it is
a longer path and a more fragile one. Do not rewrite text processing as a PowerShell
pipeline for the sake of being native — that path has more encoding traps.
