#!/usr/bin/env python3
"""Verify the candidate programmatic UTF-8 BOM write on 5.1 and 7.7.

The code under test is the one proposed for the PS51 documentation example:

    $Utf8Bom = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList @($true)
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8Bom)

It writes into a fresh directory under the stage-3.1 temp root, reads the file back,
and records the first three bytes. Nothing outside the temp root is touched.

Usage::

    python tests/benchmarks/real-model-ab-stage3-1/scripts/ps51_write_test.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile

PS51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
PS7 = "pwsh"
CONTENT = "开始部署\r\n部署完成：成功\r\n"

PROBE = r'''
param([string]$Path, [string]$Out, [string]$Content)
$ErrorActionPreference = 'Stop'
$Utf8Bom = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList @($true)
[System.IO.File]::WriteAllText($Path, $Content, $Utf8Bom)
$bytes = [System.IO.File]::ReadAllBytes($Path)
$back = [System.IO.File]::ReadAllText($Path, $Utf8Bom)
$payload = [ordered]@{
    path = $Path
    exists = (Test-Path -LiteralPath $Path)
    bytes = $bytes.Length
    head_hex = (($bytes[0..2] | ForEach-Object { $_.ToString('x2') }) -join ' ')
    bom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    content_ok = ($back -ceq $Content)
    content = $back
}
[System.IO.File]::WriteAllText($Out, ($payload | ConvertTo-Json -Depth 4),
    (New-Object System.Text.UTF8Encoding($false)))
'''


def run(host: str, root: pathlib.Path) -> dict:
    directory = root / "中文目录"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "部署.ps1"
    result_path = root / ("write-%s.json" % host.replace(".", "_"))
    probe = root / "probe.ps1"
    probe.write_bytes(b"\xef\xbb\xbf" + PROBE.encode("utf-8"))
    exe = PS51 if host == "5.1" else PS7
    proc = subprocess.run([exe, "-NoProfile", "-File", str(probe), "-Path", str(target),
                           "-Out", str(result_path), "-Content", CONTENT],
                          capture_output=True, timeout=120)
    report = json.loads(result_path.read_text(encoding="utf-8-sig")) if result_path.is_file() else {}
    within_root = str(target).lower().startswith(str(root).lower())
    return {
        "host": host,
        "exit": proc.returncode,
        "stderr": proc.stderr.decode("gbk", errors="replace")[:300],
        "path_inside_temp_root": within_root,
        **report,
    }


def main() -> None:
    root = pathlib.Path(tempfile.mkdtemp(prefix="wsw-stage31-write-"))
    report = {
        "generated": "2026-11-15",
        "candidate_code": ("New-Object -TypeName System.Text.UTF8Encoding "
                           "-ArgumentList @($true); [System.IO.File]::WriteAllText($Path, "
                           "$Content, $Utf8Bom)"),
        "content": CONTENT,
        "temp_root": str(root),
        "hosts": [run("5.1", root), run("7", root)],
    }
    report["ok"] = all(
        item.get("exit") == 0
        and item.get("exists")
        and item.get("bom")
        and item.get("content_ok")
        and item.get("path_inside_temp_root")
        and "开始部署" in (item.get("content") or "")
        for item in report["hosts"])
    target = pathlib.Path(__file__).resolve().parents[1] / "ps51-write-test.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
