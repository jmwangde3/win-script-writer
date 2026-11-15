# Python

Python 3 on Chinese Windows does not default to UTF-8. Worse: **the same script has
different defaults when an agent host runs it and when the user double-clicks it.**

## 1. Two environments, two sets of defaults (measured)

Same `python.exe` (3.13.9), only environment variables differ:

| Item | inside an agent host (`PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`) | bare environment (double-click / scheduled task) |
| --- | --- | --- |
| `sys.flags.utf8_mode` | `1` | `0` |
| `locale.getpreferredencoding(False)` | `utf-8` | **`cp936`** |
| `sys.stdout.encoding` | `utf-8` | **`gbk`** |
| bytes from `open(p,'w').write('中文')` | `E4 B8 AD E6 96 87` | **`D6 D0 CE C4`** |

Both report `sys.getfilesystemencoding() = utf-8` (fixed since PEP 529), so **Chinese
paths are safe**; file content is what breaks. This is the number-one cause of "fine in
the agent, mojibake on the user's machine": **never assume `PYTHONUTF8` exists** (see
`references/execution.md`).

## 2. Hard rule: every `open()` gets an `encoding`

```python
from pathlib import Path

p = Path(r"D:\work\项目\data.txt")

p.write_text("中文内容\n", encoding="utf-8")   # write: explicit UTF-8, no BOM
text = p.read_text(encoding="utf-8")          # read: explicit UTF-8
legacy = p.read_text(encoding="gbk")          # any other codec, still explicit
```

`Path.read_text()` / `write_text()` and `open()` all default to
`locale.getpreferredencoding(False)` — cp936 or utf-8, depending on who started the
process. For BOM tolerance read with `utf-8-sig` (it swallows a leading `EF BB BF`);
write plain `utf-8`.

## 3. `print()` into a pipe

In a bare environment `sys.stdout.encoding` is `gbk`. Printing something GBK cannot
express, such as `U+1F600`, raises `UnicodeEncodeError` **while writing**, so the log may
hold only half the output. Two approaches:

```python
# 1) keep output ASCII (simplest, survives any host)
print("OK: 3 files processed")

# 2) need non-ASCII: switch stdout to UTF-8 at entry (3.7+)
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
```

`errors="backslashreplace"` beats the default `strict`: a problem leaves readable
`\uXXXX` behind instead of killing the whole run. For bulk output, write a file (§2).

## 4. `subprocess`: do not let it guess

```python
import subprocess

# asking for text: give encoding explicitly
r = subprocess.run(["git", "log", "--oneline"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")

# safer: take bytes, decode yourself
r = subprocess.run(["git", "log", "--oneline"], capture_output=True)
text = r.stdout.decode("utf-8", "replace")
```

Never build a Chinese command with `shell=True`: the command line is decoded with the
system ANSI code page, the same trap as `-Command` (see `references/execution.md`).
`text=True` without `encoding` falls back to the locale default — cp936 in a bare
environment, which fails on UTF-8 output.

## 5. Environment variables are not a contract

`PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` fix the defaults, but they

- only apply inside the process tree that set them;
- are usually absent from double-clicks, scheduled tasks and CI;
- are overridden by `-E` / `-I` / `-X utf8=0`.

They harden; they do not constitute. `encoding=` in the code constitutes.

From Python 3.15, UTF-8 mode becomes the default (PEP 686): `open()` and
`locale.getpreferredencoding()` return UTF-8 without any environment variable, and the
right column above shifts left. The conclusion holds — keep writing `encoding=`, because
third-party libraries may still open by locale, `sys.stdout`'s encoding still depends on
terminal and host, and anyone can pass `-X utf8=0` or `PYTHONUTF8=0`.

This project verifies the direction by **forcing** UTF-8 mode (`PYTHONUTF8=1`, Python
3.13) and rerunning the same suite: the `python-utf8-mode` CI job plus a local rerun with
the variable set. That simulates 3.15's default; it is not a 3.15 compatibility test —
3.14 and 3.15 sit outside the official matrix (see `README.md`).

## 6. Handing off to PowerShell

- Files PowerShell writes for you (`Out-File`) are likely UTF-16LE with BOM — check for
  `FF FE` first.
- Files you write for it take UTF-8 without BOM; a `.ps1` with Chinese must carry one
  (see `references/powershell-51.md`).
- Both directions: Python handles bytes and UTF-8 files only, never command-line
  encoding.

## 7. Source encoding declarations (PEP 263)

`# coding: <name>` is not a comment; it is the interpreter's input contract, and
`Test-ScriptEncoding.ps1` judges it in three outcomes (unique / ambiguous / undecodable)
rather than pass-fail.

The decision table, the eight reason codes and the four `Support` states live in
`references/python-source-encoding.md`. Load that file for any question about a coding
declaration; the byte-level measurements behind it are in
`references/appendix-codec-evidence.md`.

Two facts worth carrying without loading either file: a declaration that cannot decode
its own bytes is `FAIL` + `INVALID_BYTES`, and everything Python actually runs is at most
`WARN` — including a name the detector has no byte table for
(`SOURCE_CODING_PAYLOAD=unverified`).
