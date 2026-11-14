# cmd.exe / .bat / .cmd

`cmd.exe` is harsher than PowerShell: it parses the batch file itself byte by byte
using the **currently active code page**, and it **ignores BOMs**. One `.bat` with
Chinese in it therefore has four different failure modes for four ways of saving it.

## 1. Four ways to save, measured

Test setup: a `.bat` containing `if exist "<absolute path with Chinese>"` plus
`echo 中文 > out.txt`, executed with `cmd.exe /c`, active code page left at the system
default 936. Verdicts use **exact whole-line matching** — an earlier version matched
substrings and was fooled by echo, see §6.

| Saved as | Chinese path resolves | `@echo off` takes effect | Bytes written to `out.txt` |
| --- | --- | --- | --- |
| UTF-8 without BOM | **PATH_FAIL** | yes | `E4 B8 AD E6 96 87` |
| UTF-8 with BOM | **PATH_FAIL** | **no**, line 1 becomes `<EF BB BF>@echo off` | `E4 B8 AD E6 96 87` |
| GBK (936) without BOM | **PATH_OK** | yes | `D6 D0 CE C4` |
| UTF-8 without BOM + first line `chcp 65001 >nul` | **PATH_OK** | yes | `E4 B8 AD E6 96 87` |

Three things worth keeping:

1. **`exit=0` in every case, success or failure.** cmd does not return non-zero when
   a path is missing unless you write `exit /b` yourself. "The script finished without
   an error" therefore carries no information.
2. **A BOM is the only case that also breaks `@echo off`**: `<EF BB BF>@echo off` is
   not a valid command, so echo stays on, the screen fills with command echo, and
   every following line is reinterpreted.
3. **`echo` writes the raw bytes in the file, not bytes re-encoded to the console code
   page.** That is why a UTF-8-saved file stays UTF-8 even when the console shows
   mojibake.

## 2. Conclusion: do not write new `.bat` files

Preference order: Bash (if available) → PowerShell → `.bat` last. Choose `.bat` only
for double-click execution, a scheduled task, or a genuinely ancient system.

How to fix an existing `.bat`:

```bat
@echo off
chcp 936 >nul
rem keep the skeleton pure ASCII: commands, variables, labels, comments in English
rem put Chinese content in an external UTF-8 data file read by PowerShell or Python
powershell.exe -NoProfile -File "%~dp0work.ps1"
exit /b %ERRORLEVEL%
```

The point: `.bat` launches, it does not process data.

## 3. If Chinese must be inline

Save as **ANSI/GBK (936) without BOM**. That is the only spelling that satisfies both
"paths resolve" and "`@echo off` works".

If UTF-8 is mandatory (to match the rest of a repository), put `chcp 65001 >nul` on
line 1 and keep the file **free of BOM**. It works on this host; know the cost:

- Older Windows 10 builds had defects in `for /f`, pipes and redirection under 65001;
  re-test on any other machine.
- `chcp` changes the active code page of the whole console, and children inherit it.
- Some third-party programs still interpret arguments as ANSI under 65001.

## 4. Code page boundary list

Each of these decodes again under the active code page:

| Site | What happens |
| --- | --- |
| `for /f %%i in (file)` | decodes every line of the file with the current CP |
| `findstr 中文 file` | pattern and file are both matched under the current CP |
| `type file` / `more file` | output interpreted under the current CP |
| `program-a \| program-b` | each side encodes and decodes its own way; bytes in between are not converted |
| `set /p x=<file` | reads the first line under the current CP |
| Chinese inside `>> log.txt` | written as raw bytes |

Rule: **every time data crosses a process or file boundary, ask which code page
applies at that boundary.**

## 5. Exit codes

```bat
@echo off
some-command.exe
if errorlevel 1 exit /b 1
exit /b 0
```

Without `exit /b`, a `.bat` returns the exit code of its **last command**, which is
easily 0. In CI that is the same as no check at all.

## 6. One real mistake, kept as a lesson

The first version of the four-way test asked "does stdout contain `PATH_OK`". The
UTF-8-with-BOM case appeared to pass, because once the BOM broke `@echo off`, cmd
echoed the whole directive
`if exist "..." (echo PATH_OK) else (echo PATH_FAIL)` — which contains both markers,
so a substring match always hits.

Switching to exact whole-line matching exposed it as `PATH_FAIL` immediately.

Lesson: **never let the output under test be the only evidence about the test**,
especially when that output can itself be polluted. Every assertion in `tests/` now
reads a structured field (`VERDICT=`, `ENCODING=`) or matches an exact line.
