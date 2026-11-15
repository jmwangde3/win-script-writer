#!/usr/bin/env python3
"""Unified token report: six tasks, five excluding SAFETY, three follow-up tasks.

Every number is a DeepSeek-tokenizer estimate of text length, not the context a
GPT-6-Luna session consumed. API `input_tokens` is deliberately excluded.

Usage::

    python tests/benchmarks/real-model-ab-stage3/scripts/token_report.py
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
FOLLOWUP = BENCH / "real-model-ab-followup"
TOKEN_ACTUAL = FOLLOWUP / "followup-token.json"
RUN_LOG = BENCH / "real-model-ab" / "raw" / "run-log.csv"


def load_compute():
    spec = importlib.util.spec_from_file_location("wsw_compute", BENCH / "compute.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arithmetic(values):
    return sum(values) / len(values) if values else 0.0


def weighted(rows):
    total_a = sum(row["A_tokens"] for row in rows)
    total_b = sum(row["B_tokens"] for row in rows)
    return ((total_a - total_b) / total_a * 100) if total_a else 0.0


def main() -> None:
    compute = load_compute()
    tokenizer_path = pathlib.Path(compute.find_tokenizer(None))
    tokenizer_sha = hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()
    try:
        import tokenizers
        tokenizer_version = tokenizers.__version__
    except ImportError:
        tokenizer_version = "unavailable"

    actual = json.loads(TOKEN_ACTUAL.read_text(encoding="utf-8"))
    with RUN_LOG.open(encoding="utf-8", newline="") as handle:
        logs = {(row["task"], row["group"]): row for row in csv.DictReader(handle)}

    rows = []
    for pair in actual["pairs"]:
        task = pair["task"]
        rows.append({
            "task_id": task,
            "A_tokens": pair["a_tokens"],
            "B_tokens": pair["b_tokens"],
            "saving_percent": pair["saving_pct"],
            "planned_references": {
                "A": [item for item in logs[(task, "A")]["planned_references"].split(";") if item],
                "B": [item for item in logs[(task, "B")]["planned_references"].split(";") if item],
            },
            "opened_references": {"A": pair["a_opened"], "B": pair["b_opened"]},
        })

    scopes = {
        "all_six_tasks": rows,
        "five_tasks_excluding_safety": [row for row in rows if row["task_id"] != "safety"],
        "three_followup_tasks": [row for row in rows
                                 if row["task_id"] in ("ps51", "bat", "safety")],
    }
    summary = {
        name: {
            "tasks": len(items),
            "arithmetic_mean": round(arithmetic([row["saving_percent"] for row in items]), 2),
            "weighted_saving": round(weighted(items), 2),
            "A_total": sum(row["A_tokens"] for row in items),
            "B_total": sum(row["B_tokens"] for row in items),
        }
        for name, items in scopes.items()
    }

    payload = {
        "generated": "2026-11-15",
        "estimate": True,
        "api_usage_used": False,
        "statement": ("DeepSeek tokenizer text-length estimate of the skill context; not "
                      "the context GPT-6-Luna actually consumed"),
        "tokenizer_name": "DeepSeek V4 offline tokenizer",
        "tokenizer_version": "tokenizers %s" % tokenizer_version,
        "tokenizer_sha256": tokenizer_sha,
        "method": ("metadata + SKILL.md body + the references a session actually opened; "
                   "API input_tokens is not used"),
        "tasks": rows,
        "scopes": summary,
    }
    target = HERE / "token-comparison.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")

    print("%-8s %8s %8s %8s" % ("task", "A", "B", "saving"))
    for row in rows:
        print("%-8s %8d %8d %7.2f%%" % (row["task_id"], row["A_tokens"],
                                        row["B_tokens"], row["saving_percent"]))
    for name, item in summary.items():
        print("%-28s tasks=%d arithmetic=%.2f%% weighted=%.2f%%"
              % (name, item["tasks"], item["arithmetic_mean"], item["weighted_saving"]))
    print("wrote", target)


if __name__ == "__main__":
    main()
