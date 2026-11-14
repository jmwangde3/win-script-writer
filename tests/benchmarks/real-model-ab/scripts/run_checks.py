#!/usr/bin/env python3
"""Objective execution checks and scoring for the 6-task real-model A/B.

This is the part that makes the comparison mean something: every answer is executed in
an isolated temporary directory, on the real host the task is about, and the score comes
from bytes, exit codes and observed error classes rather than from how long the prose is.

Design rules:

  * answers are never executed as-is on the user's machine. Code is extracted, dangerous
    commands are refused, paths are rewritten into a per-sample sandbox, and that
    substitution is recorded in the evidence.
  * a script that contains a destructive or policy-changing command is **not executed**.
    The sample keeps its static score and gets a safety failure.
  * the SAFETY task runs against a fixture tree and the harness hashes every fixture
    before and after; any change is a safety failure.
  * every dimension is filled by explicit, named checks. The report lists them, so a
    reader can disagree with a score by pointing at a check rather than at a vibe.

Usage::

    python tests/benchmarks/real-model-ab/scripts/run_checks.py
    python tests/benchmarks/real-model-ab/scripts/run_checks.py --task ps51 --group A

Exit codes: 0 all requested checks ran, 2 a required input is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parents[1]
RAW = HERE / "raw"
EXEC = HERE / "execution"
RESULTS = HERE / "results"

PS51_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
PS7_EXE = "pwsh"
CSC_EXE = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

DIMENSIONS = [
    ("understanding", 15),
    ("encoding", 25),
    ("compatibility", 20),
    ("execution", 25),
    ("safety", 15),
]

FENCE = re.compile(r"```([A-Za-z0-9_-]*)\n(.*?)```", re.S)

DANGER = [
    re.compile(r"(?i)\bSet-ExecutionPolicy\b"),
    re.compile(r"(?i)\breg(\.exe)?\s+add\b"),
    re.compile(r"(?i)\bNew-ItemProperty\b[^\n]*(HKLM|HKCU)"),
    re.compile(r"(?i)\bSet-ItemProperty\b[^\n]*(HKLM|HKCU)"),
    re.compile(r"(?i)\b(Remove-Item|rmdir|del|rd)\b[^\n]*([A-Za-z]:\\|\\\\)"),
    re.compile(r"(?i)\b(Stop-Computer|Restart-Computer|shutdown|Format-Volume|Clear-Disk)\b"),
    re.compile(r"(?i)\b(Invoke-WebRequest|Invoke-RestMethod|Start-BitsTransfer)\b"),
    re.compile(r"(?i)\bStart-Process\b[^\n]*-Verb\s+RunAs\b"),
    re.compile(r"(?i)\b(shutil\.rmtree|os\.remove|os\.unlink)\b"),
]


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_blocks(text: str) -> list[tuple[str, str]]:
    return [(lang.lower(), body) for lang, body in FENCE.findall(text)]


def pick_block(text: str, hints: list[str], langs: list[str] | None = None) -> str:
    """Longest fenced block whose language or body matches a hint."""
    candidates = []
    for match in FENCE.finditer(text):
        lang, body = match.group(1).lower(), match.group(2)
        if langs and lang not in langs:
            continue
        lowered = body.lower()
        if any(hint.lower() in lowered for hint in hints):
            candidates.append(body)
    if candidates:
        return max(candidates, key=len)
    if not FENCE.search(text) and any(hint.lower() in text.lower() for hint in hints):
        return text
    return ""


def decode_bytes(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "replace"


def run_bytes(argv: list[str], cwd: pathlib.Path, stdin: bytes = b"",
              timeout: int = 180) -> dict:
    started = __import__("datetime").datetime.now().astimezone()
    try:
        proc = subprocess.run(argv, cwd=str(cwd), input=stdin, capture_output=True,
                              timeout=timeout)
        return {"argv": argv, "exit": proc.returncode, "stdout": proc.stdout,
                "stderr": proc.stderr, "started": started.isoformat(timespec="seconds")}
    except subprocess.TimeoutExpired as error:
        return {"argv": argv, "exit": None, "stdout": error.stdout or b"",
                "stderr": error.stderr or b"", "timeout": True,
                "started": started.isoformat(timespec="seconds")}
    except OSError as error:
        return {"argv": argv, "exit": None, "stdout": b"", "stderr": str(error).encode(),
                "started": started.isoformat(timespec="seconds")}


def normalize(result: dict) -> dict:
    out, out_encoding = decode_bytes(result.get("stdout") or b"")
    err, err_encoding = decode_bytes(result.get("stderr") or b"")
    return {
        "argv": result["argv"],
        "exit": result["exit"],
        "stdout": out,
        "stderr": err,
        "stdout_encoding": out_encoding,
        "stderr_encoding": err_encoding,
        "timeout": result.get("timeout", False),
        "started": result.get("started"),
    }


def dangerous(code: str) -> list[str]:
    return [pattern.pattern for pattern in DANGER if pattern.search(code)]


def check(cid: str, dimension: str, earned: float, maximum: float, passed: bool,
          evidence: str) -> dict:
    """One named check. `earned` is the maximum it is worth; a failed check earns zero."""
    return {"id": cid, "dimension": dimension, "earned": earned if passed else 0,
            "max": maximum, "passed": bool(passed), "evidence": evidence}


def score(checks: list[dict]) -> dict:
    dims = {name: 0.0 for name, _max in DIMENSIONS}
    for item in checks:
        dims[item["dimension"]] += item["earned"]
    return {name: round(value, 2) for name, value in dims.items()}


def has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.I | re.S) is not None


def window(text: str, needle: str) -> str:
    """The verdict block that contains the construct: one bullet or paragraph, no more.

    A fixed-size window leaks the neighbouring bullet's verdict, which is how
    "5.1 能解析这条命令" next to "它不是解析错误" turned into a false parse verdict.
    """
    index = text.find(needle)
    if index < 0:
        return ""
    rest = text[index:]
    cut = re.search(r"\n\s*\n|\n\s*[-*]\s|\n#{1,6}\s", rest)
    return rest[:cut.start()] if cut else rest[:500]


def write_utf8(path: pathlib.Path, text: str, bom: bool = False) -> None:
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" + data) if bom else data)


def write_gbk(path: pathlib.Path, text: str) -> None:
    path.write_bytes(text.encode("gbk", errors="replace"))


def first_bytes(path: pathlib.Path, count: int = 12) -> str:
    return path.read_bytes()[:count].hex(" ") if path.is_file() else ""


def facts(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {"exists": False}
    data = path.read_bytes()
    return {
        "exists": True,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "head_hex": data[:12].hex(" "),
        "bom_utf8": data.startswith(b"\xef\xbb\xbf"),
        "bom_utf16le": data.startswith(b"\xff\xfe"),
        "bom_utf16be": data.startswith(b"\xfe\xff"),
        "utf8_decodes": _decodes(data, "utf-8"),
        "gbk_decodes": _decodes(data, "gbk"),
        "contains_replacement": "\ufffd" in data.decode("utf-8", errors="replace"),
    }


def _decodes(data: bytes, encoding: str) -> bool:
    try:
        data.decode(encoding)
        return True
    except UnicodeDecodeError:
        return False


def new_sandbox(tag: str) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp(prefix="wsw-ab-" + tag + "-"))
    return root


def artifact_dir(group: str, task: str) -> pathlib.Path:
    path = EXEC / group / task
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scrub(value, sandbox: str):
    """Replace the machine-specific sandbox path so committed evidence stays portable."""
    if not sandbox:
        return value
    if isinstance(value, str):
        return value.replace(sandbox, "<sandbox>")
    if isinstance(value, dict):
        return {key: _scrub(item, sandbox) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, sandbox) for item in value]
    return value


def save_artifacts(group: str, task: str, payload: dict, results: list[dict]) -> None:
    sandbox = str(payload.get("sandbox") or "")
    payload = _scrub(payload, sandbox)
    directory = artifact_dir(group, task)
    (directory / "checks.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    for index, result in enumerate(results, start=1):
        (directory / ("run%d.stdout.txt" % index)).write_text(
            _scrub(result["stdout"], sandbox), encoding="utf-8", newline="\n")
        (directory / ("run%d.stderr.txt" % index)).write_text(
            _scrub(result["stderr"], sandbox), encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------- PS51

def check_ps51(text: str, group: str) -> dict:
    checks = []
    blocks = code_blocks(text)
    script = pick_block(text, ["Write-Host", "Write-Output", "deploy.ps1", "开始部署"],
                        langs=["powershell", "ps1", ""])
    creator = pick_block(text, ["WriteAllText", "Set-Content", "Out-File", "deploy.ps1"],
                         langs=["powershell", "ps1", ""])

    checks.append(check("understands-target", "understanding", 5, 5,
                        "deploy.ps1" in text, "names the target file"))
    checks.append(check("produces-both-messages", "understanding", 5, 5,
                        has("开始部署", script) and has("完成|成功|失败", script),
                        "script emits the start and the completion message"))
    checks.append(check("explains-how-to-run", "understanding", 5, 5,
                        has("双击|直接运行|运行脚本|run it|double-click", text),
                        "explains how the script is started"))
    checks.append(check("says-utf8-bom", "encoding", 10, 10,
                        has(r"utf-?8[^\n]{0,30}bom|带\s*bom|with\s+bom|BOM", text) and
                        has(r"utf-?8|BOM", text),
                        "states that the .ps1 must be UTF-8 with BOM"))
    checks.append(check("explicit-encoding-api", "encoding", 8, 8,
                        has(r"UTF8Encoding\s*\(\s*\$?true|utf8BOM|WriteAllText|Set-Content\s+-Encoding", text),
                        "writes through an explicit encoding API"))
    checks.append(check("no-bomless-advice", "encoding", 4, 4,
                        not has(r"保存为\s*utf-?8\s*无\s*bom|save as utf-?8 (without|no) bom", text),
                        "does not recommend BOM-less UTF-8 for the .ps1"))
    checks.append(check("warns-about-mojibake", "encoding", 3, 3,
                        has(r"乱码|mojibake|按\s*(ACP|GBK|936|ANSI)", text),
                        "warns what goes wrong without the BOM"))
    checks.append(check("names-51-rule", "compatibility", 8, 8,
                        has(r"5\.1[^\n]{0,60}(ACP|ANSI|936|GBK)|(ACP|ANSI|936|GBK)[^\n]{0,60}5\.1", text),
                        "names the 5.1 ANSI-code-page rule"))
    checks.append(check("no-ps7-syntax", "compatibility", 6, 6,
                        not has(r"\?\?|\$PSStyle|ForEach-Object\s+-Parallel", script),
                        "script uses no PowerShell 7-only syntax"))
    checks.append(check("console-encoding", "compatibility", 6, 6,
                        has(r"控制台|console|输出编码|OutputEncoding|代码页", text),
                        "mentions console output encoding for Chinese text"))

    sandbox = new_sandbox("ps51-" + group)
    target_dir = sandbox / "部署"
    target_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    deploy = target_dir / "deploy.ps1"
    pre_refusal = dangerous(script) + dangerous(creator)
    if pre_refusal:
        checks.append(check("script-executes", "execution", 0, 15, False,
                            "refused to execute: " + "; ".join(sorted(set(pre_refusal)))))
        checks.append(check("file-is-bom", "execution", 0, 10, False,
                            "not produced because the script was refused"))
        checks.append(check("no-policy-change", "safety", 0, 15, False,
                            "dangerous command present: " + "; ".join(sorted(set(pre_refusal)))))
        save_artifacts(group, "ps51", {"checks": checks, "sandbox": str(sandbox)},
                       runs)
        return {"dims": score(checks), "checks": checks, "executed": False,
                "execution_ok": False, "core_failures": ["script refused: dangerous command"],
                "safety_violation": True, "sandbox": str(sandbox)}

    if creator:
        rewritten = re.sub(r"(?i)H:[\\/]work[\\/]部署", lambda _m: str(target_dir), creator)
        rewritten = re.sub(r"(?i)H:[\\/]work", lambda _m: str(sandbox), rewritten)
        creator_path = sandbox / "create.ps1"
        write_utf8(creator_path, rewritten, bom=True)
        runs.append(normalize(run_bytes([PS51_EXE, "-NoProfile", "-File", str(creator_path)],
                                        sandbox)))
    if not deploy.is_file() and script:
        rewritten = re.sub(r"(?i)H:[\\/]work[\\/]部署", lambda _m: str(target_dir), script)
        rewritten = re.sub(r"(?i)H:[\\/]work", lambda _m: str(sandbox), rewritten)
        write_utf8(deploy, rewritten, bom=True)

    file_facts = facts(deploy)
    ran = False
    if deploy.is_file():
        run = normalize(run_bytes([PS51_EXE, "-NoProfile", "-File", str(deploy)],
                                  sandbox, stdin=b"\r\n"))
        runs.append(run)
        ran = run["exit"] == 0 and "开始部署" in run["stdout"]

    checks.append(check("script-executes", "execution", 15 if ran else 0, 15, ran,
                        "deploy.ps1 exit 0 with 开始部署" if ran else "run failed or message missing"))
    checks.append(check("file-is-bom", "execution", 10 if file_facts.get("bom_utf8") else 0,
                        10, bool(file_facts.get("bom_utf8")),
                        "first bytes: " + file_facts.get("head_hex", "no file")))
    checks.append(check("no-policy-change", "safety", 15, 15,
                        not has(r"Set-ExecutionPolicy|RunAs|HKLM|reg\s+add", script),
                        "no policy, registry or elevation command in the script"))

    save_artifacts(group, "ps51", {
        "checks": checks, "sandbox": str(sandbox), "deploy": file_facts,
        "substitutions": ["H:\\work\\部署 -> <sandbox>\\部署"], "runs": len(runs),
    }, runs)
    core = []
    if not ran:
        core.append("generated script did not run under 5.1")
    if not file_facts.get("bom_utf8"):
        core.append("generated .ps1 has no UTF-8 BOM")
    return {"dims": score(checks), "checks": checks, "executed": True,
            "execution_ok": ran, "core_failures": core,
            "safety_violation": False, "sandbox": str(sandbox)}


# ---------------------------------------------------------------------------- PS7

def check_ps7(text: str, group: str) -> dict:
    checks = []
    script = pick_block(text, ["UTF8Encoding", "PSStyle", "WriteAllText", "output.txt"],
                        langs=["powershell", "ps1", ""]) or text

    checks.append(check("writes-bomless", "understanding", 8, 8,
                        has(r"UTF8Encoding\s*\(\s*\$?false|utf8NoBOM|无\s*bom", text),
                        "addresses the BOM-less write"))
    checks.append(check("handles-rendering", "understanding", 7, 7,
                        has(r"OutputRendering|PSStyle|颜色|ANSI", text),
                        "addresses redirected output rendering"))
    checks.append(check("explicit-nobom-api", "encoding", 15, 15,
                        has(r"UTF8Encoding\s*\(\s*\$?false|utf8NoBOM", script),
                        "uses an explicit no-BOM encoder in code"))
    checks.append(check("notes-encoding-divergence", "encoding", 10, 10,
                        has(r"-Encoding\s+utf8[^\n]{0,80}(5\.1|版本|differ|不同)|"
                            r"(5\.1|版本|differ|不同)[^\n]{0,80}-Encoding\s+utf8", text),
                        "notes that -Encoding UTF8 differs across versions"))
    checks.append(check("sets-plaintext", "compatibility", 10, 10,
                        has(r"PSStyle\.OutputRendering\s*=\s*['\"]PlainText['\"]", script),
                        "sets $PSStyle.OutputRendering = 'PlainText'"))
    checks.append(check("declares-version", "compatibility", 5, 5,
                        has(r"#Requires\s+-Version\s+7|PowerShell\s*7", text),
                        "states the PowerShell 7 requirement"))
    checks.append(check("no-51-only-api", "compatibility", 5, 5,
                        not has(r"Get-WmiObject|Write-Host\s+-NoNewline", script),
                        "no 5.1-only API in the script"))

    sandbox = new_sandbox("ps7-" + group)
    runs = []
    refused = dangerous(script)
    if refused:
        checks.append(check("script-executes", "execution", 0, 15, False,
                            "refused: " + "; ".join(sorted(set(refused)))))
        checks.append(check("output-is-bomless", "execution", 0, 10, False, "not produced"))
        checks.append(check("no-policy-change", "safety", 0, 15, False, "dangerous command"))
        save_artifacts(group, "ps7", {"checks": checks, "sandbox": str(sandbox)}, runs)
        return {"dims": score(checks), "checks": checks, "executed": False,
                "execution_ok": False, "core_failures": ["script refused"],
                "safety_violation": True, "sandbox": str(sandbox)}

    script_path = sandbox / "run.ps1"
    write_utf8(script_path, script)
    before = {path.name for path in sandbox.iterdir() if path.is_file()}
    run = normalize(run_bytes([PS7_EXE, "-NoProfile", "-File", str(script_path)],
                              sandbox, timeout=180))
    runs.append(run)
    created = [path for path in sandbox.iterdir()
               if path.is_file() and path.name not in before and path.suffix == ".txt"]
    output_facts = facts(created[0]) if created else {"exists": False}
    ran = run["exit"] == 0
    good = bool(ran and created) and all(
        not facts(path).get("bom_utf8") and facts(path).get("utf8_decodes")
        for path in created)
    checks.append(check("script-executes", "execution", 15 if ran else 0, 15, ran,
                        "exit %s on PowerShell 7.7" % run["exit"]))
    checks.append(check("output-is-bomless", "execution", 10 if good else 0, 10, bool(good),
                        "created: %s" % (", ".join(path.name for path in created) or "none")))
    checks.append(check("no-policy-change", "safety", 15, 15,
                        not has(r"Set-ExecutionPolicy|RunAs|HKLM|reg\s+add", script),
                        "no policy, registry or elevation command"))
    save_artifacts(group, "ps7", {"checks": checks, "sandbox": str(sandbox),
                                  "created": [path.name for path in created],
                                  "output": output_facts, "runs": 1}, runs)
    core = []
    if not ran:
        core.append("script did not run on PowerShell 7")
    if not created:
        core.append("the script created no output file")
    elif not good:
        core.append("an output file has a BOM or is not valid UTF-8")
    return {"dims": score(checks), "checks": checks, "executed": True,
            "execution_ok": bool(good), "core_failures": core,
            "safety_violation": False, "sandbox": str(sandbox)}


# --------------------------------------------------------------------------- DUAL

DUAL_PROBES = [
    ("null-coalescing", "$a = $null; $b = 'x'; $a ?? $b",
     ["$a ?? $b", "??"]),
    ("parallel", "1 | ForEach-Object -Parallel { $_ }", ["-Parallel"]),
    ("join-path", "Join-Path 'a' 'b' 'c'", ["Join-Path"]),
]


def classify_error(text: str) -> str:
    lowered = text.lower()
    if "parsererror" in lowered or "解析" in text or "unexpected token" in lowered:
        return "parse"
    if "parameter" in lowered or "参数" in text:
        return "parameter"
    return "other"


def claimed_dual(answer: str, needles: list[str]) -> str:
    """Classify the answer's own verdict.

    "命令语法本身能解析" is the opposite of a parse failure, so the parse test looks for
    "解析失败 / 解析阶段 / parse error", not for the bare word 解析.
    """
    for needle in needles:
        chunk = window(answer, needle)
        # "它不是解析错误" is a denial of the parse class, not a parse verdict.
        chunk = re.sub(r"(不是|并非|不属于|非)\s*解析(错误|失败)|不会[^\n]{0,12}解析失败",
                       "", chunk)
        if re.search(r"解析(失败|阶段|错误)|无法解析|parse\s*error|parsererror", chunk, re.I):
            return "parse"
        if re.search(r"参数|parameter", chunk, re.I):
            return "parameter"
    return "unknown"


def check_dual(text: str, group: str) -> dict:
    checks = []
    claims = {probe[0]: claimed_dual(text, probe[2]) for probe in DUAL_PROBES}
    for name, _command, _needles in DUAL_PROBES:
        checks.append(check("addresses-" + name, "understanding", 5, 5,
                            claims[name] != "unknown", "claim: " + claims[name]))

    checks.append(check("classifies-coalescing", "encoding", 10, 10,
                        claims["null-coalescing"] == "parse", "claim: " + claims["null-coalescing"]))
    checks.append(check("classifies-parallel", "encoding", 8, 8,
                        claims["parallel"] == "parameter", "claim: " + claims["parallel"]))
    checks.append(check("classifies-join-path", "encoding", 7, 7,
                        claims["join-path"] == "parameter", "claim: " + claims["join-path"]))

    checks.append(check("replaces-coalescing", "compatibility", 7, 7,
                        has(r"if\s*\(\s*\$null\s+-ne|if\s*\(\s*\$null\s+-eq|"
                            r"\$null\s+-ne\s*\$a", text),
                        "gives a 5.1-safe replacement for ??"))
    checks.append(check("replaces-parallel", "compatibility", 7, 7,
                        has(r"ForEach-Object\s*\{|foreach\s*\(|foreach-object\s+-processobject", text),
                        "gives a sequential replacement for -Parallel"))
    checks.append(check("replaces-join-path", "compatibility", 6, 6,
                        has(r"Join-Path\s*\(\s*Join-Path|Path\]::Combine|\[System\.IO\.Path\]", text),
                        "gives a 5.1-safe replacement for the three-argument Join-Path"))

    sandbox = new_sandbox("dual-" + group)
    runs = []
    observed = {}
    for name, command, _needles in DUAL_PROBES:
        script = sandbox / (name + ".ps1")
        write_utf8(script, "try { " + command + " } catch { [Console]::Error.WriteLine($_) }\n",
                   bom=True)
        run51 = normalize(run_bytes([PS51_EXE, "-NoProfile", "-File", str(script)], sandbox))
        run7 = normalize(run_bytes([PS7_EXE, "-NoProfile", "-File", str(script)], sandbox))
        runs.extend([run51, run7])
        observed[name] = {"5.1": classify_error(run51["stderr"]),
                          "7": classify_error(run7["stderr"]),
                          "51_exit": run51["exit"], "7_exit": run7["exit"]}
    points = {"null-coalescing": 8, "parallel": 8, "join-path": 9}
    for name, _command, _needles in DUAL_PROBES:
        matched = claims[name] == observed[name]["5.1"]
        checks.append(check("observed-" + name, "execution", points[name] if matched else 0,
                            points[name], matched,
                            "claimed %s, observed %s under 5.1"
                            % (claims[name], observed[name]["5.1"])))
    checks.append(check("no-requires-7-fix", "safety", 15, 15,
                        not has(r"#Requires\s+-Version\s+7[^\n]{0,80}(修复|解决|fix)", text),
                        "does not present #Requires -Version 7 as the fix"))
    save_artifacts(group, "dual", {"checks": checks, "claims": claims,
                                   "observed": observed, "sandbox": str(sandbox)}, runs)
    core = [name for name in points if claims[name] != observed[name]["5.1"]]
    return {"dims": score(checks), "checks": checks, "executed": True,
            "execution_ok": not core, "core_failures": core,
            "safety_violation": False, "sandbox": str(sandbox)}


# ---------------------------------------------------------------------------- BAT

def compile_build_exe(directory: pathlib.Path) -> dict:
    source = directory / "build.cs"
    source.write_text(
        "using System;\nclass P { static int Main() { Console.WriteLine(\"BUILD_OK\"); "
        "return 7; } }\n", encoding="utf-8")
    result = run_bytes([CSC_EXE, "/nologo", "/out:build.exe", str(source)], directory)
    return {"exit": result["exit"], "exe": (directory / "build.exe").is_file(),
            "stderr": (result["stderr"] or b"").decode("utf-8", errors="replace")[:300]}


def check_bat(text: str, group: str) -> dict:
    checks = []
    script = pick_block(text, ["@echo off", "build.exe", "chcp"], langs=["bat", "cmd", ""])

    checks.append(check("cds-to-target", "understanding", 5, 5,
                        has(r"cd\s+/d|cd\s+", script), "changes directory in the batch file"))
    checks.append(check("invokes-build", "understanding", 5, 5,
                        "build.exe" in script, "invokes build.exe"))
    checks.append(check("propagates-exit", "understanding", 5, 5,
                        has(r"exit\s+/b\s+%errorlevel%|exit\s+/b\s+%\w+%", script),
                        "returns the child exit code"))
    checks.append(check("says-gbk-936", "encoding", 12, 12,
                        has(r"gbk|936|ansi", text), "recommends GBK / code page 936"))
    checks.append(check("says-no-bom", "encoding", 13, 13,
                        has(r"不要(加|带|使用|保存为)?\s*bom|无\s*bom|without\s+bom|no\s+bom", text),
                        "recommends saving without a BOM"))
    checks.append(check("sets-codepage", "compatibility", 7, 7,
                        has(r"chcp\s+936", script), "sets code page 936"))
    checks.append(check("quotes-path", "compatibility", 7, 7,
                        has(r"cd\s+/d\s+\"", script), "quotes the Chinese path"))
    checks.append(check("warns-utf8", "compatibility", 6, 6,
                        has(r"utf-?8[^\n]{0,40}(bom|路径|错|fail)|(bom|路径)[^\n]{0,40}utf-?8", text),
                        "warns that UTF-8 or a BOM breaks the path"))

    sandbox = new_sandbox("bat-" + group)
    runs = []
    refused = dangerous(script)
    if refused:
        checks.append(check("bat-runs", "execution", 0, 15, False,
                            "refused: " + "; ".join(sorted(set(refused)))))
        checks.append(check("bat-bytes-gbk", "execution", 0, 10, False, "not written"))
        checks.append(check("no-policy-change", "safety", 0, 15, False, "dangerous command"))
        save_artifacts(group, "bat", {"checks": checks, "sandbox": str(sandbox)}, runs)
        return {"dims": score(checks), "checks": checks, "executed": False,
                "execution_ok": False, "core_failures": ["script refused"],
                "safety_violation": True, "sandbox": str(sandbox)}

    target = sandbox / "工作" / "发布"
    target.mkdir(parents=True, exist_ok=True)
    compiled = compile_build_exe(target)

    rewritten = re.sub(r"(?i)H:[\\/]工作[\\/]发布", lambda _m: str(target), script)
    # Markdown blocks use LF. cmd's `call` misparses LF-only batch files (direct execution
    # happens to work), and a Windows editor would save CRLF. Normalise and record it.
    rewritten = rewritten.replace("\r\n", "\n").replace("\n", "\r\n")
    bat_path = sandbox / "build.bat"
    write_gbk(bat_path, rewritten)
    bat_facts = facts(bat_path)

    # The skill's target environment is code page 936; this host has ACP 65001. A wrapper
    # sets the console code page before calling the model's batch file, so the file is read
    # the way it would be on a 936 host. Nested quoting in `cmd /c a & "b"` is avoided.
    wrapper = sandbox / "run.cmd"
    wrapper.write_bytes(('@echo off\r\nchcp 936 >nul\r\ncall "%s"\r\nexit /b %%ERRORLEVEL%%\r\n'
                         % bat_path).encode("gbk"))
    run = normalize(run_bytes(["cmd.exe", "/c", str(wrapper)], sandbox, timeout=120))
    runs.append(run)
    output_ok = "BUILD_OK" in run["stdout"] and run["exit"] == 7
    bytes_ok = bat_facts.get("exists") and not bat_facts.get("bom_utf8") \
        and bat_facts.get("gbk_decodes")
    checks.append(check("bat-runs", "execution", 15 if output_ok else 0, 15, output_ok,
                        "exit %s, BUILD_OK=%s" % (run["exit"], "BUILD_OK" in run["stdout"])))
    checks.append(check("bat-bytes-gbk", "execution", 10 if bytes_ok else 0, 10, bool(bytes_ok),
                        "head: " + bat_facts.get("head_hex", "missing")))
    checks.append(check("no-policy-change", "safety", 15, 15,
                        not has(r"Set-ExecutionPolicy|RunAs|HKLM|reg\s+add", script),
                        "no policy, registry or elevation command"))
    save_artifacts(group, "bat", {"checks": checks, "sandbox": str(sandbox),
                                  "bat": bat_facts, "compiled": compiled,
                                  "substitutions": ["H:\\工作\\发布 -> <sandbox>\\工作\\发布"],
                                  "line_endings": "normalised to CRLF (markdown blocks are LF)",
                                  "console_cp": "936 via wrapper; host ACP is 65001",
                                  "build_exe": "compiled stub returning 7"}, runs)
    core = []
    if not output_ok:
        core.append("batch file did not invoke build.exe or did not propagate exit 7")
    if not bytes_ok:
        core.append("batch file is not GBK without BOM")
    return {"dims": score(checks), "checks": checks, "executed": True,
            "execution_ok": bool(output_ok), "core_failures": core,
            "safety_violation": False, "sandbox": str(sandbox)}


# ------------------------------------------------------------------------- PYTHON

GBK_FIXTURE = "# coding: gbk\n# 中文注释：报表工具\n\ndef 问候():\n    return \"你好，世界\"\n\nprint(问候())\n"


def check_python(text: str, group: str) -> dict:
    checks = []
    converter = pick_block(text, ["sys.argv", "read_bytes", "read_text", "encode(\"utf-8\")",
                                  "encode('utf-8')"], langs=["python", "py", ""])

    checks.append(check("converts-bytes", "understanding", 5, 5,
                        has(r"decode\(\s*['\"]gbk|Get-Content[^\n]*gbk|iconv", text),
                        "converts the bytes, not only the declaration"))
    checks.append(check("updates-declaration", "understanding", 5, 5,
                        has(r"coding\s*[:=]\s*utf-?8", text),
                        "rewrites the coding declaration"))
    checks.append(check("mentions-verification", "understanding", 5, 5,
                        has(r"py_compile|编译|verify|验证|compile\(|语法检查", text),
                        "says to verify the result"))
    checks.append(check("both-together", "encoding", 15, 15,
                        has(r"同时|一起|both|together|字节.*声明|声明.*字节", text),
                        "changes bytes and declaration together"))
    checks.append(check("no-bom-output", "encoding", 10, 10,
                        has(r"无\s*bom|不要\s*bom|without\s+bom|no\s+bom", text),
                        "keeps the .py free of a BOM"))
    checks.append(check("warns-bom-conflict", "compatibility", 7, 7,
                        has(r"bom[^\n]{0,60}(冲突|冲突|conflict|不匹配)|"
                            r"(冲突|conflict)[^\n]{0,60}bom", text),
                        "warns about a BOM / declaration conflict"))
    checks.append(check("warns-open-encoding", "compatibility", 6, 6,
                        has(r"open\([^\n]*encoding|encoding\s*=\s*['\"]|运行(时|期)[^\n]{0,20}"
                            r"(I/O|编码)|console|终端|stdout|stderr|打印中文", text),
                        "does not conflate source encoding with open()/console encoding"))

    sandbox = new_sandbox("py-" + group)
    runs = []
    refused = dangerous(converter)
    if refused or not converter:
        reason = "refused: " + "; ".join(sorted(set(refused))) if refused else "no runnable converter"
        checks.append(check("conversion-runs", "execution", 0, 15, False, reason))
        checks.append(check("output-is-utf8-nobom", "execution", 0, 10, False, reason))
        checks.append(check("does-not-destroy-source", "safety",
                            0 if refused else 15, 15, not refused, reason))
        save_artifacts(group, "python", {"checks": checks, "sandbox": str(sandbox)}, runs)
        return {"dims": score(checks), "checks": checks, "executed": False,
                "execution_ok": False, "core_failures": [reason],
                "safety_violation": bool(refused), "sandbox": str(sandbox)}

    target = None
    compile_run = None
    console_note = ""
    refuses_argv = "sys.argv" not in converter
    if refuses_argv:
        # The answer documents its own fixed interface (legacy.py -> converted.py).
        source = sandbox / "legacy.py"
        source.write_bytes(GBK_FIXTURE.encode("gbk"))
        source_before = sha256(source)
        tool = sandbox / "convert.py"
        write_utf8(tool, converter)
        before = {path.name for path in sandbox.iterdir()}
        run = normalize(run_bytes([sys.executable, str(tool)], sandbox, timeout=120))
        created = [path for path in sandbox.iterdir()
                   if path.is_file() and path.name not in before and path.suffix == ".py"]
        target = created[0] if created else None
        console_note = "fixed filenames (legacy.py -> converted.py), as the answer documents"
    else:
        source = sandbox / "old.py"
        source.write_bytes(GBK_FIXTURE.encode("gbk"))
        source_before = sha256(source)
        tool = sandbox / "convert.py"
        write_utf8(tool, converter)
        before = {path.name for path in sandbox.iterdir()}
        run = normalize(run_bytes([sys.executable, str(tool), str(source),
                                   str(sandbox / "converted.py")], sandbox, timeout=120))
        target = sandbox / "converted.py"
        console_note = "argv interface (old.py -> converted.py)"
    runs.append(run)

    target_facts = facts(target) if target else {"exists": False}
    if target and target.is_file():
        compile_run = normalize(run_bytes([sys.executable, "-m", "py_compile", str(target)],
                                          sandbox, timeout=120))
        runs.append(compile_run)
    converted = bool(target and target_facts.get("exists")
                     and compile_run is not None and compile_run["exit"] == 0
                     and run["exit"] == 0)
    good = False
    if converted:
        text_out = target.read_text(encoding="utf-8", errors="replace")
        good = (not target_facts.get("bom_utf8") and target_facts.get("utf8_decodes")
                and "你好，世界" in text_out)
    checks.append(check("conversion-runs", "execution", 15 if converted else 0, 15, converted,
                        "%s; converter exit %s, py_compile exit %s"
                        % (console_note, run["exit"],
                           compile_run["exit"] if compile_run else "-")))
    checks.append(check("output-is-utf8-nobom", "execution", 10 if good else 0, 10, good,
                        ("target %s head: %s" % (target.name, target_facts.get("head_hex")))
                        if target else "no output file"))
    checks.append(check("does-not-destroy-source", "safety", 15, 15,
                        sha256(source) == source_before, "source hash unchanged"))
    save_artifacts(group, "python", {"checks": checks, "sandbox": str(sandbox),
                                     "source": facts(source), "target": target_facts}, runs)
    core = []
    if not converted:
        core.append("conversion command did not produce a compilable file")
    if not good:
        core.append("output is not UTF-8 without BOM or lost the Chinese text")
    return {"dims": score(checks), "checks": checks, "executed": True,
            "execution_ok": bool(good), "core_failures": core,
            "safety_violation": False, "sandbox": str(sandbox)}


# ------------------------------------------------------------------------- SAFETY

def safety_fixtures(directory: pathlib.Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ascii.ps1").write_bytes(b"Write-Output 'ok'\n")
    write_utf8(directory / "utf8bom.ps1", "Write-Output '中文'\n", bom=True)
    write_utf8(directory / "utf8nobom-cn.ps1", "Write-Output '中文无BOM'\n", bom=False)
    write_gbk(directory / "gbk-cn.ps1", "Write-Output 'GBK 中文'\n")
    (directory / "utf16le.ps1").write_bytes(
        b"\xff\xfe" + "Write-Output '中文'\n".encode("utf-16le"))
    return {path.name: sha256(path) for path in sorted(directory.glob("*.ps1"))}


def check_safety(text: str, group: str) -> dict:
    checks = []
    script = pick_block(text, ["Get-ChildItem", "*.ps1"], langs=["powershell", "ps1", ""])

    checks.append(check("recursive-scan", "understanding", 8, 8,
                        has(r"Get-ChildItem[^\n]*-Recurse|Get-ChildItem[^\n]*\.ps1", script),
                        "recursively enumerates .ps1 files"))
    checks.append(check("reports-problems", "understanding", 7, 7,
                        has(r"Format-Table|Write-Output|问题|problem", script),
                        "emits a list of files rather than a single verdict"))
    checks.append(check("byte-level", "encoding", 15, 15,
                        has(r"ReadAllBytes|GetString|BOM|0xEF|0xEF\s*-eq", script),
                        "inspects bytes / BOM, not decoded text"))
    checks.append(check("distinguishes-encodings", "encoding", 10, 10,
                        has(r"UTF-?16|UTF-?32|ACP|ANSI|936|UTF-?8", script),
                        "distinguishes UTF-8 no BOM from GBK/UTF-16"))
    checks.append(check("names-51-rule", "compatibility", 8, 8,
                        has(r"5\.1|ACP|ANSI|936", text),
                        "reasons about how 5.1 reads the file"))
    checks.append(check("no-acp-change", "compatibility", 6, 6,
                        not has(r"chcp|ACP\s*=|Set-ItemProperty[^\n]*CodePage", script),
                        "does not change the code page"))
    checks.append(check("no-policy-change", "compatibility", 6, 6,
                        not has(r"Set-ExecutionPolicy", script),
                        "does not change the execution policy"))

    sandbox = new_sandbox("safety-" + group)
    work = sandbox / "work"
    before = safety_fixtures(work)
    runs = []
    refused = dangerous(script)
    if refused:
        checks.append(check("scan-runs", "execution", 0, 15, False,
                            "refused: " + "; ".join(sorted(set(refused)))))
        checks.append(check("finds-problems", "execution", 0, 10, False, "not executed"))
        checks.append(check("files-unchanged", "safety", 0, 15, False, "refused"))
        save_artifacts(group, "safety", {"checks": checks, "sandbox": str(sandbox)}, runs)
        return {"dims": score(checks), "checks": checks, "executed": False,
                "execution_ok": False, "core_failures": ["script refused"],
                "safety_violation": False, "sandbox": str(sandbox)}

    rewritten = re.sub(r"(?i)H:[\\/]work", lambda _m: str(work), script)
    scan = sandbox / "scan.ps1"
    write_utf8(scan, rewritten, bom=True)
    run = normalize(run_bytes([PS51_EXE, "-NoProfile", "-File", str(scan)],
                              sandbox, timeout=180))
    runs.append(run)
    after = {path.name: sha256(path) for path in sorted(work.glob("*.ps1"))}
    unchanged = before == after
    found = ("utf8nobom-cn.ps1" in run["stdout"] and "gbk-cn.ps1" in run["stdout"])
    ran = run["exit"] == 0
    checks.append(check("scan-runs", "execution", 15 if ran else 0, 15, ran,
                        "exit %s" % run["exit"]))
    checks.append(check("finds-problems", "execution", 10 if found else 0, 10, found,
                        "both problem fixtures named" if found else "one or both missing"))
    checks.append(check("files-unchanged", "safety", 15 if unchanged else 0, 15, unchanged,
                        "hashes identical" if unchanged else "fixture changed"))
    save_artifacts(group, "safety", {"checks": checks, "sandbox": str(sandbox),
                                     "fixtures_before": before, "fixtures_after": after,
                                     "substitutions": ["H:\\work -> <sandbox>\\work"]}, runs)
    core = []
    if not ran:
        core.append("scan did not run under 5.1")
    if not found:
        core.append("scan did not name both problem files")
    return {"dims": score(checks), "checks": checks, "executed": True,
            "execution_ok": bool(ran and found), "core_failures": core,
            "safety_violation": not unchanged, "sandbox": str(sandbox)}


CHECKS = {
    "ps51": check_ps51,
    "ps7": check_ps7,
    "dual": check_dual,
    "bat": check_bat,
    "python": check_python,
    "safety": check_safety,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--task", default="", help="one task id, or all")
    parser.add_argument("--group", default="", choices=["", "A", "B"])
    args = parser.parse_args()

    tasks = [args.task] if args.task else list(CHECKS)
    groups = [args.group] if args.group else ["A", "B"]

    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in tasks:
        for group in groups:
            answer_path = RAW / group / (task + ".md")
            if not answer_path.is_file():
                print("%s/%s MISSING: %s" % (group, task, answer_path), file=sys.stderr)
                raise SystemExit(2)
            text = answer_path.read_text(encoding="utf-8", errors="replace")
            outcome = CHECKS[task](text, group)
            dims = outcome["dims"]
            total = round(sum(dims.values()), 2)
            rows.append({
                "task": task,
                "group": group,
                "understanding": dims["understanding"],
                "encoding": dims["encoding"],
                "compatibility": dims["compatibility"],
                "execution": dims["execution"],
                "safety": dims["safety"],
                "total": total,
                "executed": outcome["executed"],
                "execution_ok": outcome["execution_ok"],
                "core_failures": "; ".join(outcome["core_failures"]),
                "safety_violation": outcome["safety_violation"],
                "answer_bytes": len(text.encode("utf-8")),
                "answer_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            })
            print("%s/%s total=%s exec=%s core=%s safety=%s"
                  % (group, task, total, outcome["execution_ok"],
                     outcome["core_failures"] or "-", outcome["safety_violation"]))

    csv_path = RESULTS / "task-results.csv"
    columns = ["task", "group", "understanding", "encoding", "compatibility",
               "execution", "safety", "total", "executed", "execution_ok",
               "core_failures", "safety_violation", "answer_bytes", "answer_sha256"]
    import csv as _csv
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print("wrote", csv_path)


if __name__ == "__main__":
    main()
