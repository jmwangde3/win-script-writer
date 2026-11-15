#!/usr/bin/env python3
"""Turn the actual-routing token numbers into one comparable table.

Two averages are reported on purpose:

  * arithmetic mean of the per-task saving rates -- every task counts once
  * weighted saving -- (sum A - sum B) / sum A, so a large task counts more

They differ, and quoting only the friendlier one is how a benchmark misleads. Both are
tokenizer estimates over the references a session actually opened; neither is API usage.

Usage::

    python tests/benchmarks/real-model-ab-followup/scripts/token_comparison.py
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
ORIGINAL = BENCH / "real-model-ab"
TOKEN_ACTUAL = HERE / "followup-token.json"
RUN_LOG = ORIGINAL / "raw" / "run-log.csv"
SCOPE = ["ps51", "bat", "safety"]


def load_compute():
    spec = importlib.util.spec_from_file_location("wsw_compute", BENCH / "compute.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arithmetic_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def weighted_saving(a_values: list[int], b_values: list[int]) -> float:
    total_a = sum(a_values)
    return ((total_a - sum(b_values)) / total_a * 100) if total_a else 0.0


def main() -> None:
    compute = load_compute()
    tokenizer_path = pathlib.Path(compute.find_tokenizer(None))
    tokenizer_sha = hashlib.sha256(tokenizer_path.read_bytes()).hexdigest()

    actual = json.loads(TOKEN_ACTUAL.read_text(encoding="utf-8"))
    with RUN_LOG.open(encoding="utf-8", newline="") as handle:
        logs = {(row["task"], row["group"]): row for row in csv.DictReader(handle)}

    tasks = []
    for pair in actual["pairs"]:
        task = pair["task"]
        log_a = logs[(task, "A")]
        log_b = logs[(task, "B")]
        tasks.append({
            "task": task,
            "in_followup_scope": task in SCOPE,
            "a_tokens": pair["a_tokens"],
            "b_tokens": pair["b_tokens"],
            "saving_pct": pair["saving_pct"],
            "planned_a": [item for item in log_a["planned_references"].split(";") if item],
            "planned_b": [item for item in log_b["planned_references"].split(";") if item],
            "opened_a": pair["a_opened"],
            "opened_b": pair["b_opened"],
        })

    scoped = [item for item in tasks if item["in_followup_scope"]]
    payload = {
        "generated": "2026-11-14",
        "estimate": True,
        "api_usage_used": False,
        "method": ("tokenizer estimate of metadata + SKILL.md body + the references the "
                   "session actually opened (opened_references); API input_tokens is not "
                   "used because it covers the harness prompt and every tool turn"),
        "tokenizer": {
            "name": "DeepSeek V4 offline tokenizer",
            "package": "tokenizers",
            "file_sha256": tokenizer_sha,
        },
        "scope": SCOPE,
        "tasks": tasks,
        "arithmetic_mean_pct": {
            "scope": round(arithmetic_mean([item["saving_pct"] for item in scoped]), 2),
            "all": round(arithmetic_mean([item["saving_pct"] for item in tasks]), 2),
        },
        "weighted_saving_pct": {
            "scope": round(weighted_saving([item["a_tokens"] for item in scoped],
                                           [item["b_tokens"] for item in scoped]), 2),
            "all": round(weighted_saving([item["a_tokens"] for item in tasks],
                                         [item["b_tokens"] for item in tasks]), 2),
        },
        "totals": {
            "scope": {
                "a": sum(item["a_tokens"] for item in scoped),
                "b": sum(item["b_tokens"] for item in scoped),
            },
            "all": {
                "a": sum(item["a_tokens"] for item in tasks),
                "b": sum(item["b_tokens"] for item in tasks),
            },
        },
    }
    target = HERE / "token-comparison.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")

    print("%-8s %8s %8s %8s %s" % ("task", "A", "B", "saving", "scope"))
    for item in tasks:
        print("%-8s %8d %8d %7.2f%%  %s" % (
            item["task"], item["a_tokens"], item["b_tokens"], item["saving_pct"],
            "yes" if item["in_followup_scope"] else ""))
    print("arithmetic mean scope %.2f%% all %.2f%%" % (
        payload["arithmetic_mean_pct"]["scope"], payload["arithmetic_mean_pct"]["all"]))
    print("weighted saving scope %.2f%% all %.2f%%" % (
        payload["weighted_saving_pct"]["scope"], payload["weighted_saving_pct"]["all"]))
    print("wrote", target)


if __name__ == "__main__":
    main()
