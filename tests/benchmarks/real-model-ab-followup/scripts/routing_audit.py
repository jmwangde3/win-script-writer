#!/usr/bin/env python3
"""Audit what each session was told to read against what it actually opened.

Inputs:

  * ../quality-ab/tasks.json -- the declared `loads` / `loads_baseline`
  * ../real-model-ab/raw/run-log.csv -- planned and opened references per sample
  * the executor bundle's JSONL event log, when it still exists, for repeat reads

The audit answers four questions per sample: was a required page missing, was an extra
page loaded, was the same page read twice, and in what order were pages opened. It is an
analysis only; nothing here changes SKILL.md or the routing table.

Usage::

    python tests/benchmarks/real-model-ab-followup/scripts/routing_audit.py
"""

from __future__ import annotations

import csv
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
ORIGINAL = BENCH / "real-model-ab"
RUN_LOG = ORIGINAL / "raw" / "run-log.csv"
TASKS = BENCH / "quality-ab" / "tasks.json"
EVIDENCE = pathlib.Path(r"H:\temp\wsw-qa\run\_evidence")
ENTRY_FILES = {"SKILL.md", "README.md"}
REFERENCE = re.compile(
    r"(?i)(?:\.?[\\/])?(?:skill[\\/])?((?:references[\\/][\w\-.]+\.md)|(?:SKILL\.md)|(?:README\.md))")


def split(value: str) -> list[str]:
    return [item for item in (value or "").split(";") if item]


def reads_in_events(sample_id: str) -> dict:
    path = EVIDENCE / (sample_id + ".events.jsonl")
    if not path.is_file():
        return {"available": False, "order": [], "counts": {}}
    order = []
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item") or {}
        if item.get("type") != "command_execution":
            continue
        for match in REFERENCE.findall(item.get("command") or ""):
            normalized = match.replace("\\", "/")
            if normalized.startswith("skill/"):
                normalized = normalized[len("skill/"):]
            counts[normalized] = counts.get(normalized, 0) + 1
            if normalized not in order:
                order.append(normalized)
    return {"available": True, "order": order, "counts": counts}


def audit_sample(planned: list[str], opened: list[str], required: list[str],
                 event_reads: dict) -> dict:
    missing_required = [item for item in required if item not in opened]
    planned_not_opened = [item for item in planned if item not in opened]
    # SKILL.md is the entry point every session reads; the declared plan lists reference
    # pages, so the entry file is reported separately rather than as an unnecessary load.
    entry_opened = [item for item in opened if item in ENTRY_FILES]
    extra = [item for item in opened
             if item not in planned and item not in ENTRY_FILES]
    if event_reads.get("available"):
        counts = event_reads["counts"]
        duplicates = sorted(item for item, count in counts.items()
                            if count > 1 and item not in ENTRY_FILES)
        order = event_reads["order"]
    else:
        duplicates = None
        order = opened
    passed = not missing_required and (duplicates is None or not duplicates)
    return {
        "required": required,
        "planned": planned,
        "opened": opened,
        "entry_opened": entry_opened,
        "read_order": order,
        "missing_required": missing_required,
        "planned_not_opened": planned_not_opened,
        "extra": extra,
        "duplicates": duplicates,
        "duplicate_evidence": "codex jsonl command log" if event_reads.get("available")
                              else "not observable (event log unavailable)",
        "status": "PASS" if passed else "FAIL",
    }


def main() -> None:
    plan = json.loads(TASKS.read_text(encoding="utf-8"))
    tasks = {task["task_id"]: task for task in plan["tasks"]}
    with RUN_LOG.open(encoding="utf-8", newline="") as handle:
        logs = list(csv.DictReader(handle))

    samples = []
    for row in logs:
        source = tasks[row["task_id"]]
        key = "loads_baseline" if row["group"] == "A" else "loads"
        required = source.get(key) or source["loads"]
        samples.append({
            "task": row["task"],
            "task_id": row["task_id"],
            "group": row["group"],
            "sample_id": row["sample_id"],
            **audit_sample(split(row["planned_references"]),
                           split(row["opened_references"]),
                           required,
                           reads_in_events(row["sample_id"])),
        })

    summary = {
        "samples": len(samples),
        "missing_required": sum(1 for item in samples if item["missing_required"]),
        "extra_loads": sum(1 for item in samples if item["extra"]),
        "duplicates": sum(1 for item in samples if item["duplicates"]),
        "event_log_available": sum(1 for item in samples
                                   if item["duplicate_evidence"].startswith("codex")),
        "status": "PASS" if all(item["status"] == "PASS" for item in samples) else "FAIL",
    }
    payload = {
        "generated": "2026-11-14",
        "method": ("planned_references and opened_references from the session log; the "
                   "declared requirement is loads for B and loads_baseline for A; read "
                   "order and repeats come from the Codex command log when it is present"),
        "summary": summary,
        "samples": samples,
    }
    target = HERE / "routing-audit.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")

    for item in samples:
        print("%s/%s status=%s missing=%s extra=%s dup=%s"
              % (item["group"], item["task"], item["status"],
                 ",".join(item["missing_required"]) or "-",
                 ",".join(item["extra"]) or "-",
                 "n/a" if item["duplicates"] is None else (",".join(item["duplicates"]) or "-")))
    print("summary", summary)
    print("wrote", target)


if __name__ == "__main__":
    main()
