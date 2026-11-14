# Security principles

This page is not about what a user may do. It is about **what the tools do by
default**. When a diagnostic or write tool runs on someone else's machine, the damage
rarely comes from failing the task — it comes from what the tool changed on the way
past it.

Seven principles, each with an implementation site and a test.

## 1. Never inject `-ExecutionPolicy Bypass` by default

**Why**: `Bypass` disables the machine's last check on whether a script may run.
Baking it into a wrapper's default means every caller silently gave up their own
policy configuration.

**How**: `--execution-policy` in `scripts/run_ps.py` is an explicit optional argument.
Without it, no `-ExecutionPolicy` argument is added at all, and the help text says so.

**Test**: `tests/python/test_run_ps.py` asserts that the default argv contains no
`-ExecutionPolicy`.

## 2. Never overwrite an existing file by default

**Why**: The most common way this class of tool corrupts something is "I thought it was
inspecting, but it was rewriting". One wrong call can overwrite a user's uncommitted
script.

**How**: `scripts/New-EncodedScript.ps1` reports `EXISTS` and exits when the target is
present; only an explicit `-Force` writes. Writes go through a temp file, a read-back
check, then an atomic replace (`File.Replace` / `File.Move`), so a failure mid-way
leaves no half-written file.

**Test**: the "overwrite protection" cases in
`tests/powershell/New-EncodedScript.Tests.ps1` assert the target bytes are unchanged
without `-Force`.

## 3. Never change system-level encoding settings

**Why**: `ACP`, `OEMCP` and the system-wide UTF-8 switch all require a reboot and all
break older GBK software. A scripting helper has no reason to touch any of them.

**How**: `Get-WinScriptEnvironment.ps1` is read-only; it reports `ACP`, `OEMCP` and
`ACPSOURCE` and never writes the registry. No tool calls `Set-ExecutionPolicy`, runs
`chcp`, or changes `ACP`.

**Test**: its Pester cases assert the reported values match the registry and that
repeated read-only runs produce no side effects.

## 4. Never self-elevate

**Why**: Behaviour after elevation is outside what the user expected and cannot be
rolled back. A diagnostic tool that elevates only hides the real conclusion — that
permissions were insufficient.

**How**: every tool works completely as a standard user. `Get-WinScriptEnvironment.ps1`
reads keys under `HKLM`, which are world-readable and need no administrator.

**Correct behaviour on failure**: report "cannot read", not "let me elevate".
`Get-RegistryCodePage` catches the exception, returns `$null`, and the output says
`unknown`.

## 5. State plainly that `run_ps.py` is not a sandbox

**Why**: Mistaking "code-page-independent executor" for "safe executor" is the most
dangerous misreading available here. It restricts no filesystem, no network, no API;
the child process holds exactly the caller's rights.

**How**: the first line of the "What it does not do" section in the module docstring is
`It is not a sandbox.`; `SKILL.md` and `references/execution.md` each repeat it.

`--invoke-file` is no safer, only thinner: it hands the path to the child unchanged —
it does not read, decode, copy or rewrite the file — so all it provides is a real file
context, never isolation.

**Corollary**: do not treat `run_ps.py` as a way to run untrusted code. Untrusted code
needs a container, a restricted account or an AppContainer, not a base64 layer.

## 6. Never substitute characters silently

**Why**: Replacing unencodable characters with `?` and continuing moves the failure
far downstream — one extra question mark in a config file, discovered a week later.
Silent degradation is harder to find than a crash.

**How**:

- `New-EncodedScript.ps1` encodes with `EncoderFallback.ExceptionFallback`; a
  character GBK cannot express raises `UNREPRESENTABLE_CHARACTER` instead of being
  replaced.
- `Test-ScriptEncoding.ps1` only labels a file `gbk` when decode-then-encode returns
  byte-identical data, and then only at `confidence=medium`.
- `Test-ScriptEncoding.ps1` also decodes the bytes after a BOM: a BOM is a
  declaration, not proof the content is valid. `EF BB BF FF` reports `FAIL`, not `OK`.
- Tool output is ASCII throughout (`VERDICT=OK`, `ENCODING=gbk`), so it never depends
  on a code page.

**Test**: `tests/powershell/New-EncodedScript.Tests.ps1` uses an emoji fixture and
asserts a non-zero exit code with an explicit error code.

## 7. Never record sensitive content

**Why**: these tools see script bodies, paths and environment variables. Once that
text lands in a log or an echo, "a script on my machine" becomes "a script inside some
log file".

**How**:

- No tool writes a log file.
- `run_ps.py` echoes only the child's real stdout/stderr bytes; it never prints "the
  command I ran was…".
- Error messages contain paths and error codes, never script bodies.
- `--keep-temp` keeps the temp directory only when asked, and the directory name never
  carries script content.

## 8. The boundary of what may change

When building tools of this kind, even tests take the explicit path. Nothing
self-heals:

| Operation | Default | Requires |
| --- | --- | --- |
| Overwrite a file | refused | `-Force` |
| Relax execution policy | not added | `--execution-policy` |
| Change console encoding | unchanged | `--console-encoding` |
| Keep temp files | deleted | `--keep-temp` |
| Rewrite a script file | never | `--invoke-file` does not rewrite either; only `New-EncodedScript.ps1` writes files |
| Change the system code page | never | not offered at all |

The last row is deliberate: some things should not exist behind a default-off switch.
They should not exist.
