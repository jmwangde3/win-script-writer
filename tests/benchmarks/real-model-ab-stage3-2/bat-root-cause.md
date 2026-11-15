# BAT root cause: S07 missing `chcp 936`

## Evidence

| Item | Value |
| --- | --- |
| Sample | B / S07 (`bat-01`, stage 3.1) |
| File bytes | 168 bytes, GBK, no BOM, CRLF (`40 65 63 68 6f 20 6f 66 66 0d 0a`) |
| `chcp 936` in the final block | **no** |
| CP936 run | exit **7**, stdout `BUILD_OK` |
| CP65001 run | exit **1**, stderr `The system cannot find the path specified.` |
| Score | 50/100 (bytes + 936; no chcp, no 65001) |

The answer first proposes a `\u` escape, then explicitly says it does not work, and gives
the final GBK block:

```bat
@echo off
cd /d "H:\工作\发布"
if errorlevel 1 exit /b 1
"%CD%\build.exe"
exit /b %ERRORLEVEL%
```

That block is correctly saved as GBK without BOM, but it never sets the console code page.

## Answers

**1. Why no `chcp 936`?**
The model focused on the **file** encoding (GBK) and assumed the console was already at
936. It did not add the console-side switch. This is an omission in the execution strategy,
not missing knowledge: the same answer says the file must be GBK/ANSI.

**2. Why does A pass both environments?**
The A answers put `chcp 936 >nul` at the top. The batch then sets the console to 936 before
`cd` parses the GBK bytes, so the same file works in both wrappers.

**3. Is `chcp 936` the only necessary fix?**
For this file, yes. The bytes are already GBK, no BOM, CRLF; the path is correct. Adding
`chcp 936 >nul` before `cd /d` makes both runs pass. No other change is required.

**4. Is the BAT file encoding correct?**
Yes: GBK, no BOM, CRLF. `gbk_decodes = true`, `utf8_decodes = false`, first bytes are
`@echo off\r\n`.

**5. Is there a UTF-8 file / GBK console conflict?**
There is a **GBK file / 65001 console** conflict, the mirror image. `cmd.exe` reads the
batch using the active console code page. At 65001, the GBK path bytes are not valid UTF-8,
so `cd /d` cannot resolve `工作\发布`. The batch must either set 936 (GBK file) or be a
UTF-8 file with `chcp 65001` on line 1.

**6. Any argument, path or interpreter problem?**
No. The Chinese path resolves at 936; `build.exe` runs and exit 7 propagates. The failure is
entirely the console code page. There is no quoting or interpreter defect in the final block.

**7. Does the formal Skill already cover this?**
Yes. `references/cmd-bat.md`:

- §2 example starts with `chcp 936 >nul` and says `.bat` launches, it does not process data.
- §3 says inline Chinese must be **ANSI/GBK (936) without BOM**; if UTF-8 is mandatory,
  put `chcp 65001 >nul` on line 1 and keep the file BOM-free.

The knowledge is present and loaded (`cmd-bat.md` was opened by every BAT session).

**8. Classification**

**`MODEL_OMISSION`** — the model did not apply a code-page rule that its loaded reference
shows. It is not a knowledge gap (the answer states the GBK requirement), not a loading
problem (`cmd-bat.md` was opened), and not a client behavior problem (the file was written
exactly as the model specified). No documentation change is justified by this sample; the
new stage-3.2 task tests whether the omission persists when the prompt explicitly requires
both code pages without manual changes.
