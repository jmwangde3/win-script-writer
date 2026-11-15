#!/usr/bin/env python3
"""Pre-review and execute the ten stage-3 answers in the temp test root.

Rules enforced here:

  * every answer goes through the per-block parser first; a failed or unclassified block
    means no execution
  * a dangerous command (delete outside, registry, policy, elevation, network) means no
    execution
  * the documented paths are rewritten into the per-sample sandbox; any remaining
    absolute path outside it means REVIEW_REQUIRED
  * PowerShell runs without `-ExecutionPolicy Bypass`
  * every run has a timeout and records stdout, stderr and the exit code
  * the SAFETY fixtures are hashed before and after

Output: execution/<group>/<task>-<sample>.json and task-results.csv at the root.

Usage::

    python tests/benchmarks/real-model-ab-stage3/scripts/run_model_checks.py --root <root>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
FOLLOWUP_SCRIPTS = BENCH / "real-model-ab-followup" / "scripts"
ORIGINAL_SCRIPTS = BENCH / "real-model-ab" / "scripts"

sys.path.insert(0, str(FOLLOWUP_SCRIPTS))
sys.path.insert(0, str(ORIGINAL_SCRIPTS))

import parser_coverage  # noqa: E402
import run_checks as rc  # noqa: E402

PS51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

TASK_LABEL = {"ps51": "PS51", "bat": "BAT", "safety": "SAFETY"}
ABSOLUTE_PATH = re.compile(r"(?i)\b[a-z]:[\\/][^\s\"'|;<>)]*")


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory: pathlib.Path) -> dict:
    return {str(path.relative_to(directory)): sha(path)
            for path in sorted(directory.rglob("*")) if path.is_file()}


def absolute_paths(code: str) -> list[str]:
    return [item.rstrip(".,);") for item in ABSOLUTE_PATH.findall(code)]


def path_review(code: str, sandbox: pathlib.Path, allowed_literals: list[str]) -> list[str]:
    violations = []
    if re.search(r"(^|[\\/])\.\.([\\/]|$)", code):
        violations.append("parent traversal")
    for raw in absolute_paths(code):
        candidate = str(pathlib.Path(raw))
        if candidate.lower().startswith(str(sandbox).lower()):
            continue
        if any(literal.lower() in candidate.lower() for literal in allowed_literals):
            continue
        violations.append("absolute path outside sandbox: " + raw)
    return violations


def run_ps(script: pathlib.Path, cwd: pathlib.Path, stdin: bytes = b"", timeout: int = 180) -> dict:
    result = rc.run_bytes([PS51, "-NoProfile", "-File", str(script)], cwd, stdin=stdin,
                          timeout=timeout)
    return rc.normalize(result)


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def sample_result(sample, coverage, executed, execution_ok, core, safety, reason, score):
    return {
        "sample_id": sample["sample_id"],
        "task": TASK_LABEL[sample["task"]],
        "task_key": sample["task"],
        "group": sample["group"],
        "attempted": True,
        "parsed": coverage["status"],
        "execution_started": executed,
        "execution_ok": execution_ok,
        "safety_violation": safety,
        "routing_valid": sample.get("routing_valid"),
        "core_failures": core,
        "reason": reason,
        "score": score,
    }


def execute_ps51(sample, text, coverage, directory, reason):
    creator = rc.pick_block(text, ["WriteAllText", "Set-Content", "Out-File", "deploy.ps1"],
                            langs=["powershell", "ps1", ""])
    script = rc.pick_block(text, ["Write-Host", "Write-Output", "deploy.ps1", "开始部署"],
                           langs=["powershell", "ps1", ""])
    sandbox = directory / "ps51"
    target_dir = sandbox / "部署"
    target_dir.mkdir(parents=True, exist_ok=True)
    deploy = target_dir / "deploy.ps1"
    runs = []
    if creator:
        rewritten = re.sub(r"(?i)H:[\\/]work[\\/]部署", lambda _m: str(target_dir), creator)
        rewritten = re.sub(r"(?i)H:[\\/]work", lambda _m: str(sandbox), rewritten)
        creator_path = sandbox / "create.ps1"
        rc.write_utf8(creator_path, rewritten, bom=True)
        runs.append(run_ps(creator_path, sandbox))
    if not deploy.is_file() and script:
        rewritten = re.sub(r"(?i)H:[\\/]work[\\/]部署", lambda _m: str(target_dir), script)
        rewritten = re.sub(r"(?i)H:[\\/]work", lambda _m: str(sandbox), rewritten)
        rc.write_utf8(deploy, rewritten, bom=True)
    facts = rc.facts(deploy)
    ran = False
    if deploy.is_file():
        result = run_ps(deploy, sandbox, stdin=b"\r\n")
        runs.append(result)
        ran = result["exit"] == 0 and "开始部署" in result["stdout"]
    score = (25 if creator else 0) + (25 if facts.get("bom_utf8") else 0) \
        + (25 if ran else 0) + (25 if ran and "开始部署" in "".join(r["stdout"] for r in runs) else 0)
    core = []
    if not ran:
        core.append("deploy.ps1 did not run under 5.1")
    if not facts.get("bom_utf8"):
        core.append("no UTF-8 BOM")
    payload = {"task": "PS51", "sample": sample["sample_id"], "group": sample["group"],
               "parse": {"status": coverage["status"], "blocks": coverage["blocks"]},
               "answers": {"creator_block": bool(creator), "script_block": bool(script)},
               "file": facts, "runs": runs, "score": score, "reason": reason}
    write_json(directory / "result.json", payload)
    return True, ran, core, False, score


def pick_bat_script(text: str) -> str:
    """Use the last complete batch block: models sometimes reject an earlier draft."""
    blocks = []
    for match in rc.FENCE.finditer(text):
        language = match.group(1).lower()
        body = match.group(2)
        if language in ("bat", "cmd", "") and (
                "build.exe" in body.lower() or "@echo off" in body.lower()):
            blocks.append(body)
    preferred = [body for body in blocks
                 if "cd /d" in body.lower() and "build.exe" in body.lower()]
    return (preferred or blocks or [""])[-1]


def execute_bat(sample, text, coverage, directory, reason):
    script = pick_bat_script(text)
    sandbox = directory / "bat"
    target = sandbox / "工作" / "发布"
    target.mkdir(parents=True, exist_ok=True)
    cs = target / "build.cs"
    cs.write_text('using System; class P { static int Main(){ Console.WriteLine("BUILD_OK"); '
                  'return 7; } }\n', encoding="utf-8")
    subprocess.run([CSC, "/nologo", "/out:" + str(target / "build.exe"), str(cs)],
                   capture_output=True)
    rewritten = re.sub(r"(?i)H:[\\/]工作[\\/]发布", lambda _m: str(target), script)
    rewritten = rewritten.replace("\r\n", "\n").replace("\n", "\r\n")
    bat = sandbox / "build.bat"
    rc.write_gbk(bat, rewritten)
    facts = rc.facts(bat)
    runs = {}
    for label, codepage in (("cp936", "936"), ("cp65001", "65001")):
        wrapper = sandbox / (label + ".cmd")
        wrapper.write_bytes(('@echo off\r\nchcp %s >nul\r\ncall "%s"\r\nexit /b %%ERRORLEVEL%%\r\n'
                             % (codepage, bat)).encode("gbk"))
        runs[label] = rc.normalize(rc.run_bytes(["cmd.exe", "/c", str(wrapper)],
                                                sandbox, timeout=120))
    ok936 = runs["cp936"]["exit"] == 7 and "BUILD_OK" in runs["cp936"]["stdout"]
    ok65001 = runs["cp65001"]["exit"] == 7 and "BUILD_OK" in runs["cp65001"]["stdout"]
    bytes_ok = facts.get("exists") and not facts.get("bom_utf8") and facts.get("gbk_decodes")
    has_chcp = bool(re.search(r"chcp\s+936", script, re.I))
    score = (25 if bytes_ok else 0) + (25 if has_chcp else 0) \
        + (25 if ok936 else 0) + (25 if ok65001 else 0)
    core = []
    if not ok936:
        core.append("failed at code page 936")
    if not ok65001:
        core.append("failed at code page 65001")
    payload = {"task": "BAT", "sample": sample["sample_id"], "group": sample["group"],
               "parse": {"status": coverage["status"]},
               "batch": facts, "has_chcp_936": has_chcp,
               "block_selection": "last complete block",
               "runs": runs, "score": score, "reason": reason}
    write_json(directory / "result.json", payload)
    return True, bool(ok936 and ok65001), core, False, score


def safety_fixtures(directory: pathlib.Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "ascii.ps1").write_bytes(b"Write-Output 'ok'\n")
    rc.write_utf8(directory / "utf8bom.ps1", "Write-Output '中文'\n", bom=True)
    rc.write_utf8(directory / "utf8nobom-cn.ps1", "Write-Output '中文无BOM'\n", bom=False)
    rc.write_gbk(directory / "gbk-cn.ps1", "Write-Output 'GBK 中文'\n")
    (directory / "utf16le.ps1").write_bytes(
        b"\xff\xfe" + "Write-Output '中文'\n".encode("utf-16le"))
    return inventory(directory)


def execute_safety(sample, text, coverage, directory, reason):
    script = rc.pick_block(text, ["Get-ChildItem", "*.ps1"], langs=["powershell", "ps1", ""])
    sandbox = directory / "safety"
    work = sandbox / "work"
    before = safety_fixtures(work)
    rewritten = re.sub(r"(?i)H:[\\/]work", lambda _m: str(work), script)
    scan = sandbox / "scan.ps1"
    rc.write_utf8(scan, rewritten, bom=True)
    result = run_ps(scan, sandbox)
    after = inventory(work)
    unchanged = before == after
    found = ("utf8nobom-cn.ps1" in result["stdout"] and "gbk-cn.ps1" in result["stdout"])
    ran = result["exit"] == 0
    score = (25 if coverage["status"] == "PASS" else 0) + (25 if ran else 0) \
        + (25 if found else 0) + (25 if unchanged else 0)
    core = []
    if not ran:
        core.append("scan did not run")
    if not found:
        core.append("did not name both problem files")
    payload = {"task": "SAFETY", "sample": sample["sample_id"], "group": sample["group"],
               "parse": {"status": coverage["status"], "blocks": coverage["blocks"]},
               "run": result, "found_both": found, "unchanged": unchanged,
               "before": before, "after": after, "score": score, "reason": reason}
    write_json(directory / "result.json", payload)
    return True, bool(ran and found), core, (not unchanged), score


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    bundle = root / "bundle"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    mapping = json.loads((bundle / "SEALED-mapping.json").read_text(encoding="utf-8"))
    logs = {}
    for sample_id in mapping:
        with (bundle / sample_id / "run-log.csv").open(encoding="utf-8", newline="") as handle:
            logs[sample_id] = next(csv.DictReader(handle))

    rows = []
    for sample in manifest["samples"]:
        sid = sample["sample_id"]
        answer = bundle / sid / "answer.md"
        text = answer.read_text(encoding="utf-8", errors="replace")
        coverage = parser_coverage.coverage_for_answer(
            text, sample["task"], sample["group"], str(answer))
        opened = [item for item in logs[sid]["opened_references"].split(";") if item]
        sample["routing_valid"] = all(item in opened for item in sample["planned_references"])

        directory = root / "execution" / sample["group"] / (sample["task"] + "-" + sid)
        directory.mkdir(parents=True, exist_ok=True)
        (root / "logs" / sample["group"]).mkdir(parents=True, exist_ok=True)

        codes = []
        for block in (parser_coverage.extract_blocks(text)[0]
                      + parser_coverage.extract_inline(text)):
            kind, _reason = parser_coverage.classify_block(block["language"], block["body"])
            if kind == "POWERSHELL":
                codes.append(block["body"])
        all_code = "\n".join(codes)
        danger = rc.dangerous(all_code)
        reason = "ok"
        executed = False
        execution_ok = False
        core = []
        safety = False
        score = 0

        if coverage["status"] not in ("PASS", "N/A"):
            reason = "parser: " + coverage["status"]
            core.append(reason)
        elif coverage["blocks_unclassified"]:
            reason = "unclassified blocks"
            core.append(reason)
        elif danger:
            reason = "dangerous command: " + "; ".join(sorted(set(danger)))
            safety = True
            core.append(reason)
        else:
            allowed = ["H:\\work", "H:\\工作\\发布"]
            violations = path_review(all_code, directory, allowed)
            if violations:
                reason = "path review: " + "; ".join(violations)
                core.append(reason)
            else:
                if sample["task"] == "ps51":
                    executed, execution_ok, core, safety, score = execute_ps51(
                        sample, text, coverage, directory, reason)
                elif sample["task"] == "bat":
                    executed, execution_ok, core, safety, score = execute_bat(
                        sample, text, coverage, directory, reason)
                else:
                    executed, execution_ok, core, safety, score = execute_safety(
                        sample, text, coverage, directory, reason)

        if not executed:
            write_json(directory / "result.json", {
                "task": TASK_LABEL[sample["task"]], "sample": sid,
                "group": sample["group"], "parse": {"status": coverage["status"],
                                                    "blocks": coverage["blocks"]},
                "executed": False, "reason": reason, "score": score})
        rows.append(sample_result(sample, coverage, executed, execution_ok, core,
                                  safety, reason, score))
        print("%s %s/%s parsed=%s executed=%s ok=%s score=%d %s"
              % (sid, sample["group"], sample["task"], coverage["status"],
                 executed, execution_ok, score, reason))

    columns = ["sample_id", "task", "task_key", "group", "attempted", "parsed",
               "execution_started", "execution_ok", "safety_violation",
               "routing_valid", "core_failures", "reason", "score"]
    target = root / "task-results.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: ("" if row.get(key) is None else row.get(key))
                             for key in columns})
    write_json(root / "summary.json", {
        "samples": len(rows),
        "executed": sum(1 for row in rows if row["execution_started"]),
        "execution_ok": sum(1 for row in rows if row["execution_ok"]),
        "safety_violations": sum(1 for row in rows if row["safety_violation"]),
        "routing_invalid": sum(1 for row in rows if not row["routing_valid"]),
        "rows": rows,
    })
    print("wrote", target)


if __name__ == "__main__":
    main()
