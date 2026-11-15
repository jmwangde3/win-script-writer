#!/usr/bin/env python3
"""Static PowerShell parse check: parse a file, never run it.

`Parser.ParseFile` is the engine's own parser. It reports syntax errors with a line and
column and executes nothing, which is exactly what a generated script needs before anyone
runs it. Both hosts are supported because they do not agree on how a BOM-less file with
non-ASCII bytes is read.

Usage::

    from ps_parse import parse_file
    parse_file(path, "5.1")   # Windows PowerShell
    parse_file(path, "7")     # PowerShell 7

The result is a dict::

    {"ok": true|false, "host": "5.1.26100.9711", "errors": [...]}

``ok`` is ``None`` only when the probe itself could not run, which is a harness failure,
not a syntax verdict.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile

PS51_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
PS7_EXE = "pwsh"

PROBE = r'''
param([string]$Path, [string]$Out)
$tokens = $null
$errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
$payload = [ordered]@{
    host = $PSVersionTable.PSVersion.ToString()
    ok = (@($errors).Count -eq 0)
    errors = @($errors | ForEach-Object {
        [ordered]@{
            message = $_.Message
            error_id = $_.ErrorId
            line = $_.Extent.StartLineNumber
            column = $_.Extent.StartColumnNumber
            text = $_.Extent.Text
        }
    })
}
[System.IO.File]::WriteAllText($Out, ($payload | ConvertTo-Json -Depth 4),
    (New-Object System.Text.UTF8Encoding($false)))
'''


def host_exe(host: str) -> str:
    if host == "5.1":
        return PS51_EXE
    if host == "7":
        return PS7_EXE
    raise ValueError("host must be '5.1' or '7'")


def parse_file(path: pathlib.Path, host: str, timeout: int = 60) -> dict:
    path = pathlib.Path(path).resolve()
    if not path.is_file():
        return {"ok": None, "host": host, "errors": [],
                "harness_error": "file does not exist: %s" % path}
    with tempfile.TemporaryDirectory(prefix="wsw-parse-") as directory:
        holder = pathlib.Path(directory)
        probe = holder / "parse.ps1"
        probe.write_bytes(b"\xef\xbb\xbf" + PROBE.encode("utf-8"))
        output = holder / "result.json"
        try:
            subprocess.run([host_exe(host), "-NoProfile", "-NonInteractive", "-File",
                            str(probe), "-Path", str(path), "-Out", str(output)],
                           capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            return {"ok": None, "host": host, "errors": [],
                    "harness_error": str(error)}
        if not output.is_file():
            return {"ok": None, "host": host, "errors": [],
                    "harness_error": "the parser probe produced no result"}
        data = json.loads(output.read_text(encoding="utf-8-sig"))
    data.setdefault("errors", [])
    data["errors"] = list(data["errors"])
    return data


if __name__ == "__main__":
    import sys

    target = pathlib.Path(sys.argv[1])
    for version in ("5.1", "7"):
        report = parse_file(target, version)
        print(version, "ok=%s" % report["ok"])
        for error in report["errors"]:
            print("  line %s col %s: %s" % (error.get("line"), error.get("column"),
                                            error.get("message")))
