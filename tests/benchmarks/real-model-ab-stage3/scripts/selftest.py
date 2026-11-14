#!/usr/bin/env python3
"""Harmless environment self-test, run before any model code.

Creates its own fixtures under the stage-3 temp root and checks the four things the
execution harness will rely on: PowerShell 5.1, PowerShell 7, cmd at code page 936 and
65001, and Python's GBK to UTF-8 path. Nothing here is model-generated.

Usage::

    python tests/benchmarks/real-model-ab-stage3/scripts/selftest.py --root <temp root>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

PS51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
PS7 = "pwsh"
CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"


def run(argv, cwd, stdin=b"", timeout=120):
    proc = subprocess.run(argv, cwd=str(cwd), input=stdin, capture_output=True,
                          timeout=timeout)
    return {"argv": argv, "exit": proc.returncode,
            "stdout": proc.stdout.decode("utf-8", errors="replace"),
            "stderr": proc.stderr.decode("gbk", errors="replace")}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ps_probe(directory: pathlib.Path) -> dict:
    script = directory / "probe.ps1"
    script.write_bytes(b"\xef\xbb\xbf" + (
        "$ErrorActionPreference = 'Stop'\n"
        "$target = Join-Path $PSScriptRoot 'ps-out.txt'\n"
        "$text = \"中文内容`r`n第二行\"\n"
        "$utf8 = New-Object System.Text.UTF8Encoding($false)\n"
        "[System.IO.File]::WriteAllText($target, $text, $utf8)\n"
        "Write-Output '开始部署'\n"
        "exit 0\n").encode("utf-8"))
    result51 = run([PS51, "-NoProfile", "-File", str(script)], directory)
    data = (directory / "ps-out.txt").read_bytes() if (directory / "ps-out.txt").is_file() else b""
    return {
        "5.1_exit": result51["exit"],
        "5.1_stdout": result51["stdout"].strip(),
        "5.1_file_bytes": len(data),
        "5.1_file_bom": data.startswith(b"\xef\xbb\xbf"),
        "5.1_utf8_decodes": _decodes(data),
    }


def _decodes(data: bytes) -> bool:
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def bat_probe(directory: pathlib.Path) -> dict:
    target = directory / "工作" / "发布"
    target.mkdir(parents=True, exist_ok=True)
    source = directory / "build.cs"
    source.write_text(
        "using System; class P { static int Main(){ Console.WriteLine(\"BUILD_OK\"); "
        "return 7; } }\n", encoding="utf-8")
    subprocess.run([CSC, "/nologo", "/out:" + str(target / "build.exe"), str(source)],
                   capture_output=True)
    body = ("@echo off\r\nchcp 936 >nul\r\ncd /d \"%s\"\r\nif errorlevel 1 exit /b 1\r\n"
            "build.exe\r\nexit /b %%ERRORLEVEL%%\r\n" % target)
    bat = directory / "selftest.bat"
    bat.write_bytes(body.encode("gbk"))
    results = {}
    for label, codepage in (("cp936", "936"), ("cp65001", "65001")):
        wrapper = directory / (label + ".cmd")
        wrapper.write_bytes(('@echo off\r\nchcp %s >nul\r\ncall "%s"\r\nexit /b %%ERRORLEVEL%%\r\n'
                             % (codepage, bat)).encode("gbk"))
        results[label] = run(["cmd.exe", "/c", str(wrapper)], directory)
    return results


def python_probe(directory: pathlib.Path) -> dict:
    source = directory / "gbk.py"
    source.write_bytes("# coding: gbk\nprint(\"你好\")\n".encode("gbk"))
    target = directory / "utf8.py"
    target.write_bytes(source.read_bytes().decode("gbk").replace(
        "coding: gbk", "coding: utf-8").encode("utf-8"))
    compile_result = run([sys.executable, "-m", "py_compile", str(target)], directory)
    run_result = run([sys.executable, str(target)], directory)
    return {
        "compile_exit": compile_result["exit"],
        "run_exit": run_result["exit"],
        "stdout": run_result["stdout"].strip(),
        "bom": target.read_bytes().startswith(b"\xef\xbb\xbf"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    directory = root / "fixtures" / "selftest"
    directory.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(exist_ok=True)

    report = {
        "run_id": root.name,
        "root": str(root),
        "windows_powershell": run([PS51, "-NoProfile", "-Command",
                                   "$PSVersionTable.PSVersion.ToString()"], directory)["stdout"].strip(),
        "powershell": run([PS7, "-NoProfile", "-Command",
                           "$PSVersionTable.PSVersion.ToString()"], directory)["stdout"].strip(),
        "python": sys.version.split()[0],
        "ps": ps_probe(directory),
        "bat": bat_probe(directory),
        "python_probe": python_probe(directory),
    }
    report["ok"] = (
        report["ps"]["5.1_exit"] == 0
        and not report["ps"]["5.1_file_bom"]
        and report["ps"]["5.1_utf8_decodes"]
        and report["bat"]["cp936"]["exit"] == 7
        and "BUILD_OK" in report["bat"]["cp936"]["stdout"]
        and report["bat"]["cp65001"]["exit"] == 7
        and "BUILD_OK" in report["bat"]["cp65001"]["stdout"]
        and report["python_probe"]["compile_exit"] == 0
        and report["python_probe"]["run_exit"] == 0
        and not report["python_probe"]["bom"])

    target = root / "logs" / "selftest.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
