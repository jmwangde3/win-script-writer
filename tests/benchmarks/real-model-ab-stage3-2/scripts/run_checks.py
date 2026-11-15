#!/usr/bin/env python3
"""Pre-review and execute the stage-3.2 BAT and PS51 samples.

BAT: the same file runs at console code page 936 and 65001 with a Chinese argument and
exit code 7. PS51: the script must create deploy.ps1 itself, with UTF-8 BOM and Chinese
content, and run on Windows PowerShell 5.1.

Nothing runs unless the parser gate, the dangerous-command scan and the path review pass.
No `-ExecutionPolicy Bypass`. A temp directory is not an OS sandbox; that limit is recorded.

Usage::

    python tests/benchmarks/real-model-ab-stage3-2/scripts/run_checks.py --root <root>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "real-model-ab-followup" / "scripts"))
sys.path.insert(0, str(BENCH / "real-model-ab" / "scripts"))

import parser_coverage  # noqa: E402
import run_checks as rc  # noqa: E402

PS51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
PS7 = "pwsh"
CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
ABSOLUTE = re.compile(r"(?i)\b[a-z]:[\\/][^\s\"'|;<>)]*")
DANGER_BAT = re.compile(
    r"(?i)\b(del|erase|rd|rmdir|format|reg\s+add|reg\s+delete|schtasks|sc\s+config|"
    r"curl|wget|bitsadmin|certutil\s+-urlcache)\b")


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def last_bat_block(text: str) -> str:
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


def bat_encoding(text: str) -> str:
    lower = text.lower()
    if "chcp 65001" in lower and "chcp 936" not in lower:
        return "utf-8"
    return "gbk"


def path_review(code: str, sandbox: pathlib.Path, allowed: list[str]) -> list[str]:
    problems = []
    if re.search(r"(^|[\\/])\.\.([\\/]|$)", code):
        problems.append("parent traversal")
    for raw in ABSOLUTE.findall(code):
        candidate = raw.rstrip(".,);")
        if candidate.lower().startswith(str(sandbox).lower()):
            continue
        if any(item.lower() in candidate.lower() for item in allowed):
            continue
        problems.append("absolute path outside sandbox: " + candidate)
    return problems


def smart_decode(data: bytes) -> str:
    for codec in ("utf-8", "gbk"):
        try:
            text = data.decode(codec)
        except UnicodeDecodeError:
            continue
        if "构建完成" in text or "BUILD_OK" in text:
            return text
    return data.decode("utf-8", errors="replace")


def execute_bat(sample, text, directory):
    script = last_bat_block(text)
    sandbox = directory / "bat"
    target = sandbox / "工作" / "发布"
    target.mkdir(parents=True, exist_ok=True)
    source = target / "build.cs"
    source.write_text('using System; class P { static int Main(){ Console.WriteLine("BUILD_OK"); '
                      'return 7; } }\n', encoding="utf-8")
    subprocess.run([CSC, "/nologo", "/out:" + str(target / "build.exe"), str(source)],
                   capture_output=True)

    rewritten = re.sub(r"(?i)H:[\\/]工作[\\/]发布", lambda _m: str(target), script)
    rewritten = rewritten.replace("\r\n", "\n").replace("\n", "\r\n")
    encoding = bat_encoding(text)
    bat = target / "build.bat"
    if encoding == "utf-8":
        bat.write_bytes(rewritten.encode("utf-8"))
    else:
        rc.write_gbk(bat, rewritten)

    facts = rc.facts(bat)
    runs = {}
    for label, codepage in (("cp936", "936"), ("cp65001", "65001")):
        proc = subprocess.run(
            ["cmd.exe", "/c", 'chcp %s >nul & call build.bat "发布说明"' % codepage],
            cwd=str(target), capture_output=True, timeout=120)
        runs[label] = {
            "exit": proc.returncode,
            "stdout": smart_decode(proc.stdout),
            "stderr": smart_decode(proc.stderr),
        }

    def passed(run):
        out = run["stdout"]
        return (run["exit"] == 7 and "BUILD_OK" in out
                and "构建完成" in out and "发布说明" in out)

    ok936, ok65001 = passed(runs["cp936"]), passed(runs["cp65001"])
    has_chcp = bool(re.search(r"chcp\s+936", script, re.I))
    has_chcp_utf8 = bool(re.search(r"chcp\s+65001", script, re.I))
    mentions = (bool(re.search(r"(?i)gbk|ansi|936|utf-8", text))
                and bool(re.search(r"(?i)crlf", text)))
    bytes_ok = (facts.get("exists") and not facts.get("bom_utf8")
                and (facts.get("gbk_decodes") if encoding == "gbk"
                     else facts.get("utf8_decodes"))
                and b"\r\n" in bat.read_bytes())
    checks = [
        {"name": "file-bytes-and-encoding", "points": 20 if bytes_ok and mentions else 0,
         "max": 20, "evidence": "GBK=%s BOM=%s CRLF=%s mentions=%s" % (
             facts.get("gbk_decodes"), facts.get("bom_utf8"), b"\r\n" in bat.read_bytes(),
             mentions)},
        {"name": "explicit-codepage", "points": 20 if (has_chcp or has_chcp_utf8) else 0,
         "max": 20, "evidence": "chcp936=%s chcp65001=%s" % (has_chcp, has_chcp_utf8)},
        {"name": "cp936", "points": 20 if ok936 else 0, "max": 20,
         "evidence": "exit=%s stdout=%r" % (runs["cp936"]["exit"],
                                            runs["cp936"]["stdout"][:120])},
        {"name": "cp65001", "points": 20 if ok65001 else 0, "max": 20,
         "evidence": "exit=%s stdout=%r stderr=%r" % (
             runs["cp65001"]["exit"], runs["cp65001"]["stdout"][:120],
             runs["cp65001"]["stderr"][:120])},
        {"name": "chinese-output-and-arg", "points": 20 if (ok936 and ok65001) else 0,
         "max": 20, "evidence": "both runs printed BUILD_OK, 构建完成 and the argument"},
    ]
    score = sum(item["points"] for item in checks)
    payload = {"task": "BAT", "sample": sample["sample_id"], "group": sample["group"],
               "encoding_used": encoding, "batch": facts, "has_chcp_936": has_chcp,
               "has_chcp_65001": has_chcp_utf8, "mentions_encoding_and_crlf": mentions,
               "runs": runs, "checks": checks, "score": score}
    write_json(directory / "result.json", payload)
    return True, bool(ok936 and ok65001), score, [
        item["name"] for item in checks if item["points"] == 0]


def execute_ps51(sample, text, directory):
    script = rc.pick_block(text, ["WriteAllText", "Set-Content", "Out-File", "UTF8Encoding"],
                           langs=["powershell", "ps1", ""])
    sandbox = directory / "ps51"
    target_dir = sandbox / "部署"
    target_dir.mkdir(parents=True, exist_ok=True)
    produced = target_dir / "deploy.ps1"

    rewritten = re.sub(r"(?i)H:[\\/]work[\\/]部署", lambda _m: str(target_dir), script)
    rewritten = re.sub(r"(?i)H:[\\/]work", lambda _m: str(sandbox), rewritten)
    creator = sandbox / "create.ps1"
    rc.write_utf8(creator, rewritten, bom=True)

    run51 = rc.normalize(rc.run_bytes([PS51, "-NoProfile", "-File", str(creator)],
                                      sandbox, timeout=180))
    run7 = rc.normalize(rc.run_bytes([PS7, "-NoProfile", "-File", str(creator)],
                                     sandbox, timeout=180))
    facts = rc.facts(produced)
    content = produced.read_text(encoding="utf-8-sig") if produced.is_file() else ""
    programmatic = bool(re.search(r"(?i)WriteAllText|Set-Content|Out-File|WriteAllBytes",
                                  script))
    created = produced.is_file()
    bom = bool(facts.get("bom_utf8"))
    chinese = ("开始部署" in content and "部署完成" in content)
    verified = ("EF BB BF" in run51["stdout"] or "EF BB BF" in content
                or "验证" in run51["stdout"] or "OK" in run51["stdout"])
    checks = [
        {"name": "programmatic-write", "points": 20 if programmatic else 0, "max": 20,
         "evidence": "WriteAllText/Set-Content/Out-File present=%s" % programmatic},
        {"name": "file-created", "points": 20 if created else 0, "max": 20,
         "evidence": str(produced)},
        {"name": "utf8-bom", "points": 20 if bom else 0, "max": 20,
         "evidence": facts.get("head_hex", "no file")},
        {"name": "chinese-readback", "points": 20 if chinese and verified else 0, "max": 20,
         "evidence": "content=%r run51=%r" % (content[:80], run51["stdout"][:120])},
        {"name": "ps51-runs", "points": 20 if run51["exit"] == 0 else 0, "max": 20,
         "evidence": "exit=%s stderr=%r" % (run51["exit"], run51["stderr"][:120])},
    ]
    score = sum(item["points"] for item in checks)
    payload = {"task": "PS51", "sample": sample["sample_id"], "group": sample["group"],
               "programmatic": programmatic, "batch": facts, "content_head": content[:300],
               "run_5_1": run51, "run_7": run7, "checks": checks, "score": score}
    write_json(directory / "result.json", payload)
    return True, bool(created and bom and chinese and run51["exit"] == 0), score, [
        item["name"] for item in checks if item["points"] == 0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    bundle = root / "bundle"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    mapping = json.loads((bundle / "SEALED-mapping.json").read_text(encoding="utf-8"))
    logs = {}
    for sid in mapping:
        with (bundle / sid / "run-log.csv").open(encoding="utf-8", newline="") as handle:
            logs[sid] = next(csv.DictReader(handle))

    rows = []
    for sample in manifest["samples"]:
        sid = sample["sample_id"]
        text = (bundle / sid / "answer.md").read_text(encoding="utf-8", errors="replace")
        coverage = parser_coverage.coverage_for_answer(
            text, sample["task"], sample["group"], str(bundle / sid / "answer.md"))
        opened = [item for item in logs[sid]["opened_references"].split(";") if item]
        routing_valid = all(item in opened for item in sample["planned_references"])

        directory = root / "execution" / sample["group"] / (sample["task"] + "-" + sid)
        directory.mkdir(parents=True, exist_ok=True)
        (root / "logs" / sample["group"]).mkdir(parents=True, exist_ok=True)

        codes = []
        for block in (parser_coverage.extract_blocks(text)[0]
                      + parser_coverage.extract_inline(text)):
            kind, _ = parser_coverage.classify_block(block["language"], block["body"])
            if kind == "POWERSHELL":
                codes.append(block["body"])
        all_code = "\n".join(codes)

        danger = rc.dangerous(all_code) if sample["task"] == "ps51" else []
        if sample["task"] == "bat":
            danger = sorted(set(match.group(0) for match in DANGER_BAT.finditer(text)))
        allowed = ["H:\\work", "H:\\工作\\发布"]
        problems = path_review(all_code if sample["task"] == "ps51" else text,
                               directory, allowed)

        executed = False
        execution_ok = False
        score = 0
        failures = []
        safety = bool(danger)
        reason = "ok"
        if sample["task"] == "ps51" and coverage["status"] not in ("PASS", "N/A"):
            reason = "parser: " + coverage["status"]
            failures.append(reason)
        elif danger:
            reason = "dangerous command: " + ", ".join(danger)
            failures.append(reason)
        elif problems:
            reason = "path review: " + "; ".join(problems)
            failures.append(reason)
        else:
            if sample["task"] == "bat":
                executed, execution_ok, score, failures = execute_bat(sample, text, directory)
            else:
                executed, execution_ok, score, failures = execute_ps51(sample, text, directory)
            reason = "ok" if execution_ok else "failed: " + ", ".join(failures)

        if not executed:
            write_json(directory / "result.json", {
                "task": sample["task"].upper(), "sample": sid, "group": sample["group"],
                "executed": False, "reason": reason, "score": score})
        rows.append({
            "sample_id": sid, "task": sample["task"].upper(), "task_key": sample["task"],
            "group": sample["group"], "attempted": True, "parsed": coverage["status"],
            "execution_started": executed, "execution_ok": execution_ok,
            "safety_violation": safety, "routing_valid": routing_valid,
            "failed_checks": "; ".join(failures), "score": score, "reason": reason,
        })
        print("%s %s/%s parsed=%s executed=%s ok=%s score=%d %s" % (
            sid, sample["group"], sample["task"], coverage["status"], executed,
            execution_ok, score, reason))

    columns = list(rows[0])
    with (root / "task-results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_json(root / "summary.json", {
        "samples": len(rows),
        "executed": sum(1 for row in rows if row["execution_started"]),
        "execution_ok": sum(1 for row in rows if row["execution_ok"]),
        "safety_violations": sum(1 for row in rows if row["safety_violation"]),
        "routing_valid": sum(1 for row in rows if row["routing_valid"]),
        "rows": rows,
    })
    print("wrote", root / "task-results.csv")


if __name__ == "__main__":
    main()
