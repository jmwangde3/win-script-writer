#!/usr/bin/env python3
"""Static follow-up checks for PS51, BAT and SAFETY.

The follow-up was supposed to regenerate ten answers and execute them. That is blocked on
this host: there is no Windows Sandbox, no hypervisor and no VM, and Codex's own Windows
sandbox rejects every command (``blocked by policy``) in both ``read-only`` and
``workspace-write``. Generation therefore only works with ``danger-full-access``, which
this task forbids, and execution has no isolation at all.

So this script does the part that is still honest and useful: it re-reads the twelve
existing answers, runs the engine's own parser on the PowerShell ones (no execution), and
records what can be decided without running anything. It never claims an execution result.

Usage::

    python tests/benchmarks/real-model-ab-followup/scripts/static_checks.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
ORIGINAL = BENCH / "real-model-ab"
RAW = ORIGINAL / "raw"
RUN_LOG = RAW / "run-log.csv"
SCRIPTS = BENCH / "real-model-ab" / "scripts"

sys.path.insert(0, str(SCRIPTS))
import ps_parse  # noqa: E402

TASKS = ["ps51", "bat", "safety"]
FENCE = re.compile(r"```([A-Za-z0-9_-]*)\n(.*?)```", re.S)

STATUS = {
    "attempted": True,
    "execution_started": False,
    "execution_ok": None,
    "blocked_reason": ("no Windows Sandbox, no hypervisor/VM and no Docker on this host; "
                       "Codex's Windows sandbox rejected every command, so executing "
                       "model-generated scripts would have to run unsandboxed on the host"),
}

DANGER = [
    re.compile(r"(?i)\bSet-ExecutionPolicy\b"),
    re.compile(r"(?i)\breg(\.exe)?\s+add\b"),
    re.compile(r"(?i)\b(Remove-Item|rmdir|del|rd)\b[^\n]*([A-Za-z]:\\|\\\\)"),
    re.compile(r"(?i)\b(Stop-Computer|Restart-Computer|shutdown|Format-Volume)\b"),
    re.compile(r"(?i)\b(Invoke-WebRequest|Invoke-RestMethod|Start-BitsTransfer)\b"),
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pick_block(text: str, hints: list[str], langs: list[str] | None = None) -> str:
    candidates = []
    for match in FENCE.finditer(text):
        lang, body = match.group(1).lower(), match.group(2)
        if langs and lang not in langs:
            continue
        if any(hint.lower() in body.lower() for hint in hints):
            candidates.append(body)
    if candidates:
        return max(candidates, key=len)
    if not FENCE.search(text) and any(hint.lower() in text.lower() for hint in hints):
        return text
    return ""


def write_utf8(path: pathlib.Path, text: str, bom: bool = False) -> None:
    data = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" + data) if bom else data)


def clean_errors(report: dict) -> list[dict]:
    return [{"line": item.get("line"), "column": item.get("column"),
             "message": item.get("message"), "error_id": item.get("error_id")}
            for item in report.get("errors") or []]


def analyse(task: str, group: str, text: str, sample_id: str) -> dict:
    record = {
        "task": task,
        "group": group,
        "sample_id": sample_id,
        "source": "../real-model-ab/raw/%s/%s.md" % (group, task),
        "answer_sha256": sha256(text.encode("utf-8")),
        "answer_bytes": len(text.encode("utf-8")),
        **STATUS,
    }
    script_path = HERE / "static" / group / (task + ".ps1")
    static_path = HERE / "static" / group / (task + ".json")

    if task in ("ps51", "safety"):
        hints = ["Write-Host", "deploy.ps1"] if task == "ps51" else ["Get-ChildItem", "*.ps1"]
        script = pick_block(text, hints, langs=["powershell", "ps1", ""])
        record["script_found"] = bool(script)
        record["script_sha256"] = sha256(script.encode("utf-8")) if script else ""
        if script:
            write_utf8(script_path, script, bom=True)
            report51 = ps_parse.parse_file(script_path, "5.1")
            report7 = ps_parse.parse_file(script_path, "7")
            record["parsed_5_1"] = report51.get("ok")
            record["parsed_7"] = report7.get("ok")
            record["errors_5_1"] = clean_errors(report51)
            record["errors_7"] = clean_errors(report7)
            record["dangerous"] = [pattern.pattern for pattern in DANGER
                                   if pattern.search(script)]
        else:
            record["parsed_5_1"] = None
            record["parsed_7"] = None
            record["errors_5_1"] = []
            record["errors_7"] = []
            record["dangerous"] = []
        record["reproducible_write"] = bool(
            re.search(r"UTF8Encoding\s*\(\s*\$?true|WriteAllText|Set-Content\s+-Encoding", text))
        record["has_chcp_936"] = None
    else:  # bat
        script = pick_block(text, ["@echo off", "build.exe", "chcp"], langs=["bat", "cmd", ""])
        record["script_found"] = bool(script)
        record["script_sha256"] = sha256(script.encode("utf-8")) if script else ""
        record["parsed_5_1"] = None
        record["parsed_7"] = None
        record["errors_5_1"] = []
        record["errors_7"] = []
        record["dangerous"] = [pattern.pattern for pattern in DANGER
                               if pattern.search(script)]
        record["reproducible_write"] = None
        record["has_chcp_936"] = bool(re.search(r"chcp\s+936", script))
        if script:
            try:
                script.encode("gbk")
                record["gbk_encodable"] = True
            except UnicodeEncodeError as error:
                record["gbk_encodable"] = False
                record["gbk_error"] = str(error)
            record["has_exit_b"] = bool(re.search(r"exit\s+/b", script, re.I))
            record["has_cd_d"] = bool(re.search(r"cd\s+/d", script, re.I))

    record["safety_violation"] = bool(record.get("dangerous"))
    static_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    return record


def main() -> None:
    with RUN_LOG.open(encoding="utf-8", newline="") as handle:
        logs = {(row["task"], row["group"]): row for row in csv.DictReader(handle)}

    records = []
    for task in TASKS:
        for group in ("A", "B"):
            answer = RAW / group / (task + ".md")
            text = answer.read_text(encoding="utf-8", errors="replace")
            sample = logs[(task, group)]["sample_id"]
            record = analyse(task, group, text, sample)
            record["planned_references"] = logs[(task, group)]["planned_references"]
            record["opened_references"] = logs[(task, group)]["opened_references"]
            records.append(record)

    results = HERE / "followup-results.csv"
    columns = ["task", "group", "sample_id", "attempted", "parsed_5_1", "parsed_7",
               "execution_started", "execution_ok", "safety_violation",
               "reproducible_write", "has_chcp_936", "planned_references",
               "opened_references", "blocked_reason", "answer_sha256"]
    with results.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow({key: ("" if record.get(key) is None else record.get(key))
                             for key in columns})

    ps_records = [record for record in records if record["parsed_5_1"] is not None]
    summary = {
        "followup": "v1.1.0 reliability follow-up",
        "date": "2026-11-14",
        "regenerated_samples": 0,
        "model_calls": 0,
        "requested_samples": {"safety": 6, "bat": 2, "ps51": 2, "total": 10},
        "blocked": {
            "stage": "model generation and dynamic execution",
            "reason": STATUS["blocked_reason"],
            "isolation_checks": {
                "windows_sandbox_exe": False,
                "hypervisor_present": False,
                "docker": False,
                "virtualbox": False,
                "vmware": False,
                "codex_read_only_sandbox": "every command rejected: blocked by policy",
                "codex_workspace_write_sandbox": "every command rejected: blocked by policy",
            },
        },
        "static_analysis_of_existing_answers": {
            "note": ("the twelve 2026-11-14 answers were re-read and parsed; they are not "
                     "the requested regenerated samples"),
            "samples": len(records),
            "parser": {
                "checked": len(ps_records),
                "A_pass": sum(1 for r in ps_records if r["group"] == "A" and r["parsed_5_1"]),
                "A_fail": sum(1 for r in ps_records if r["group"] == "A" and not r["parsed_5_1"]),
                "B_pass": sum(1 for r in ps_records if r["group"] == "B" and r["parsed_5_1"]),
                "B_fail": sum(1 for r in ps_records if r["group"] == "B" and not r["parsed_5_1"]),
            },
            "safety_parse_failures": [
                {"group": r["group"], "task": r["task"],
                 "first_error": (r["errors_5_1"] or [{}])[0].get("message")}
                for r in records if r["parsed_5_1"] is False
            ],
            "bat_chcp_936": {r["group"]: r["has_chcp_936"] for r in records
                             if r["task"] == "bat"},
            "ps51_reproducible_write": {r["group"]: r["reproducible_write"]
                                        for r in records if r["task"] == "ps51"},
        },
        "verdict": "CONDITIONAL",
        "verdict_reason": (
            "The benchmark now rejects a script that fails Parser.ParseFile before any "
            "execution, and the one available B/SAFETY answer fails that parse on both "
            "hosts while A passes. That is a real defect but a single observation: the "
            "requested three repeats per group could not be generated because the host has "
            "no usable isolation, and no execution was performed. Nothing here supports a "
            "PASS, and one sample cannot prove a systematic regression."
        ),
    }
    (HERE / "followup-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    for record in records:
        print("%s/%s parsed51=%s parsed7=%s exec_started=%s safety=%s"
              % (record["group"], record["task"], record["parsed_5_1"],
                 record["parsed_7"], record["execution_started"],
                 record["safety_violation"]))
    print("wrote", results)


if __name__ == "__main__":
    main()
