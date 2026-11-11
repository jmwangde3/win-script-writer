#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execute script text in Windows PowerShell or PowerShell 7 without code page loss.

Why this exists
---------------
Passing script text through ``-Command`` on a CP936 (zh-CN) host is lossy: the
command line is decoded with the ANSI code page, so Chinese literals and Chinese
paths arrive as mojibake, and nested quotes are re-parsed by the shell. This
wrapper sends the script as Base64 of UTF-16LE through ``-EncodedCommand``
instead, which bypasses both the code page and the quote parser.

What it does not do
-------------------
It is not a sandbox. It does not change ``[Console]::OutputEncoding`` or
``$OutputEncoding`` unless you ask with ``--console-encoding``, and it does not
inject ``-ExecutionPolicy Bypass`` unless you ask with ``--execution-policy``.

Usage
-----
    python run_ps.py 'Write-Output "hello"'
    python run_ps.py --command 'Get-ChildItem -LiteralPath "C:\\some\\dir"'
    python run_ps.py --file .\\script.ps1
    python run_ps.py - < script.ps1
    echo 'Get-Date' | python run_ps.py --stdin
    python run_ps.py --shell pwsh --command '$PSVersionTable.PSEdition'
    python run_ps.py --console-encoding utf8 'Write-Output "zh text"'

Exit codes
----------
    0    the script succeeded
    n    the script's own exit code
    3    usage, I/O or decoding error in this wrapper
    124  timeout
    127  requested shell not found
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
import tempfile

__version__ = "1.0.0"

EXIT_LOCAL_ERROR = 3
EXIT_TIMEOUT = 124
EXIT_NO_SHELL = 127

#: Windows caps a process command line at 32767 characters. Keep a margin for the
#: executable path and the fixed switches.
MAX_COMMAND_LINE_CHARS = 30000

EXECUTION_POLICIES = (
    "Bypass",
    "RemoteSigned",
    "AllSigned",
    "Restricted",
    "Unrestricted",
    "Undefined",
    "Default",
)


def resolve_shell(name):
    """Return the full path of the requested shell, or None when it is missing."""
    if not name:
        name = "powershell"
    name = name.strip().lower()

    if name in ("pwsh", "ps7", "powershell-core", "powershell7"):
        candidates = []
        found = shutil.which("pwsh")
        if found:
            candidates.append(found)
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidates.append(os.path.join(program_files, "PowerShell", "7", "pwsh.exe"))
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidates.append(os.path.join(local_appdata, "Microsoft", "WindowsApps", "pwsh.exe"))
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    for folder in ("System32", "SysWOW64"):
        candidate = os.path.join(system_root, folder, "WindowsPowerShell", "v1.0", "powershell.exe")
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("powershell.exe")


def build_prelude(console_encoding):
    """Return an optional prelude that aligns the child console encoding.

    Empty by default: the caller's console settings are not touched.
    """
    if not console_encoding:
        return ""
    value = console_encoding.strip().lower()
    if value in ("", "none", "off", "keep"):
        return ""
    if value in ("utf8", "utf-8", "65001"):
        return (
            "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false);"
            "$OutputEncoding = New-Object System.Text.UTF8Encoding($false);"
        )
    if value.isdigit():
        return "[Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(%s);" % value
    raise ValueError("unsupported console encoding: %s" % console_encoding)


def build_argv(exe, encoded=None, script_path=None, execution_policy=None):
    """Build the child argv. Always a list: this module never uses a shell."""
    argv = [exe, "-NoProfile", "-NonInteractive"]
    if execution_policy:
        argv += ["-ExecutionPolicy", execution_policy]
    if encoded is not None:
        argv += ["-EncodedCommand", encoded]
    else:
        argv += ["-File", script_path]
    return argv


def needs_file_fallback(length):
    """True when the encoded payload would exceed the command line limit."""
    return length > MAX_COMMAND_LINE_CHARS


def read_source(args):
    """Return (script_text, error_message). Exactly one error field is set."""
    if args.file:
        path = os.path.abspath(args.file)
        if not os.path.isfile(path):
            return None, "input file not found: %s" % path
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            return None, "cannot read %s: %s" % (path, exc)
        return decode(raw, args.input_encoding)

    if args.command is not None:
        return args.command, None

    if args.snippet is not None and args.snippet != "-":
        return args.snippet, None

    if args.snippet == "-" or args.stdin:
        if sys.stdin is None:
            return None, "stdin is not available"
        raw = sys.stdin.buffer.read()
        return decode(raw, args.input_encoding)

    if not sys.stdin.isatty():
        raw = sys.stdin.buffer.read()
        return decode(raw, args.input_encoding)

    return None, "no script supplied"


def decode(raw, encoding):
    try:
        text = raw.decode(encoding)
    except LookupError:
        return None, "unknown input encoding: %s" % encoding
    except UnicodeDecodeError as exc:
        return None, "input is not valid %s (byte offset %d)" % (encoding, exc.start)
    # utf-8-sig strips a BOM; other codecs may leave U+FEFF behind.
    return text.lstrip("\ufeff"), None


def write_stream(stream, payload):
    if not payload:
        return
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.flush()
    else:  # pragma: no cover - only when stdout has been replaced
        stream.write(payload.decode("utf-8", "replace"))


def error(message):
    write_stream(sys.stderr, ("run_ps.py: " + message + "\n").encode("utf-8", "replace"))


def wrap_script(script):
    """Wrap script text in a script block.

    Needed only when a prelude is injected. ``param(...)`` and
    ``[CmdletBinding()]`` are only legal as the first statement of a script or a
    script block, so concatenating a prelude in front of them silently turns them
    into commands that do not exist: PowerShell reports "param : The term 'param'
    is not recognized", the rest of the script still runs, and the process still
    exits 0. Wrapping keeps the user's text at the start of a block while the
    prelude stays outside it.

    The newlines matter: without the one before the closing brace, a script whose
    last line ends in a comment would comment out the brace itself.
    """
    return "& {\n" + script + "\n}"


def run(script, *, shell="powershell", timeout=300.0, execution_policy=None,
        console_encoding=None, keep_temp=False):
    """Execute script text and return (exit_code, stdout_bytes, stderr_bytes)."""
    prelude = build_prelude(console_encoding)
    # Only pay for the wrapper when there is a prelude to keep out of the way.
    if prelude:
        payload = prelude + wrap_script(script)
    else:
        payload = script
    encoded = base64.b64encode(payload.encode("utf-16-le")).decode("ascii")

    exe = resolve_shell(shell)
    if not exe:
        return EXIT_NO_SHELL, b"", ("requested shell not found: %s\n" % shell).encode()

    temp_dir = None
    try:
        if needs_file_fallback(len(exe) + len(encoded) + 64):
            # Long payloads cannot travel on the command line. A UTF-8 file with a
            # BOM is the one form that both PS 5.1 and PS 7 parse identically.
            temp_dir = tempfile.mkdtemp(prefix="ws-run-ps-")
            script_path = os.path.join(temp_dir, "script.ps1")
            with open(script_path, "wb") as handle:
                handle.write(b"\xef\xbb\xbf")
                handle.write(payload.encode("utf-8"))
            argv = build_argv(exe, script_path=script_path, execution_policy=execution_policy)
        else:
            argv = build_argv(exe, encoded=encoded, execution_policy=execution_policy)

        effective_timeout = None if not timeout or timeout <= 0 else timeout
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or b""
            err = (exc.stderr or b"") + (
                "run_ps.py: timed out after %s seconds\n" % timeout
            ).encode()
            return EXIT_TIMEOUT, out, err
        except FileNotFoundError:
            return EXIT_NO_SHELL, b"", ("requested shell not found: %s\n" % exe).encode()
        except OSError as exc:
            return EXIT_LOCAL_ERROR, b"", ("failed to start %s: %s\n" % (exe, exc)).encode()

        return completed.returncode, completed.stdout, completed.stderr
    finally:
        if temp_dir and not keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="run_ps.py",
        description="Run script text in PowerShell without code page or quote loss.",
        epilog="Exit codes: 0 ok, child exit code, 3 local error, 124 timeout, 127 shell not found.",
    )
    parser.add_argument("snippet", nargs="?", help="script text, or - to read stdin")
    parser.add_argument("-c", "--command", help="script text (named form of snippet)")
    parser.add_argument("-f", "--file", help="read the script from a file")
    parser.add_argument("--stdin", action="store_true", help="read the script from stdin")
    parser.add_argument(
        "--input-encoding",
        default="utf-8-sig",
        help="encoding of stdin or --file input (default: utf-8-sig)",
    )
    parser.add_argument(
        "--shell",
        default="powershell",
        choices=("powershell", "pwsh"),
        help="which runtime to use (default: powershell, i.e. Windows PowerShell 5.1)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="seconds before the child is killed; 0 disables the limit (default: 300)",
    )
    parser.add_argument(
        "--execution-policy",
        default=None,
        help="pass -ExecutionPolicy to the child for this process only (off by default)",
    )
    parser.add_argument(
        "--console-encoding",
        default=None,
        metavar="ENC",
        help="align the child console encoding (utf8 or a code page number); off by default",
    )
    parser.add_argument("--version", action="version", version="run_ps.py " + __version__)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.execution_policy:
        normalized = args.execution_policy.strip().capitalize()
        match = [p for p in EXECUTION_POLICIES if p.lower() == normalized.lower()]
        if not match:
            error("unknown execution policy: %s" % args.execution_policy)
            return EXIT_LOCAL_ERROR
        args.execution_policy = match[0]

    sources = [
        args.snippet is not None,
        args.command is not None,
        bool(args.file),
        args.stdin,
    ]
    if sum(1 for flag in sources if flag) > 1:
        error("supply only one of: snippet, --command, --file, --stdin")
        return EXIT_LOCAL_ERROR

    script, problem = read_source(args)
    if problem:
        error(problem)
        return EXIT_LOCAL_ERROR
    if not script or not script.strip():
        error("empty script")
        return EXIT_LOCAL_ERROR

    try:
        code, out, err = run(
            script,
            shell=args.shell,
            timeout=args.timeout,
            execution_policy=args.execution_policy,
            console_encoding=args.console_encoding,
        )
    except ValueError as exc:
        error(str(exc))
        return EXIT_LOCAL_ERROR

    write_stream(sys.stdout, out)
    write_stream(sys.stderr, err)
    return code


if __name__ == "__main__":
    sys.exit(main())
