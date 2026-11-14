#!/usr/bin/env python3
"""Recompute skill context from the references a session actually opened.

The original benchmark measures a declared routing plan (`loads`). This one uses the
`opened_references` column in `../real-model-ab/raw/run-log.csv`, which came from the
Codex JSONL command log. It still uses the same offline tokenizer, so the result is an
estimate — but an estimate of the files the session touched, not of the files a plan said
it would touch.

API `input_tokens` is deliberately **not** used: it covers the harness system prompt and
every tool turn, and is not a measure of the skill text.

Usage::

    python tests/benchmarks/real-model-ab-followup/scripts/token_actual.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
ORIGINAL = BENCH / "real-model-ab"
RUN_LOG = ORIGINAL / "raw" / "run-log.csv"
SNAPSHOTS = {
    "A": BENCH / "baseline" / "v1.0.4",
    "B": BENCH / "candidate" / "v1.1.0",
}
SCOPE_TASKS = ["ps51", "bat", "safety"]


def load_compute():
    spec = importlib.util.spec_from_file_location("wsw_compute", BENCH / "compute.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    compute = load_compute()
    tokenizer_path = compute.find_tokenizer(None)
    tokenizer = compute.load_tokenizer(tokenizer_path)

    with RUN_LOG.open(encoding="utf-8", newline="") as handle:
        logs = list(csv.DictReader(handle))

    samples = []
    for row in logs:
        snapshot = SNAPSHOTS[row["group"]]
        skill = (snapshot / "SKILL.md").read_text(encoding="utf-8")
        frontmatter, body = compute.split_frontmatter(skill)
        metadata = compute.description_of(frontmatter)
        opened = [item for item in (row["opened_references"] or "").split(";")
                  if item and item not in ("SKILL.md", "README.md")]
        references = []
        for item in opened:
            path = snapshot / item
            references.append({
                "path": item,
                "exists": path.is_file(),
                "tokens": compute.count(tokenizer, path.read_text(encoding="utf-8"))
                if path.is_file() else 0,
            })
        metadata_tokens = compute.count(tokenizer, metadata)
        body_tokens = compute.count(tokenizer, body)
        reference_tokens = sum(item["tokens"] for item in references)
        samples.append({
            "task": row["task"],
            "group": row["group"],
            "sample_id": row["sample_id"],
            "planned_references": row["planned_references"],
            "opened_references": opened,
            "metadata_tokens": metadata_tokens,
            "body_tokens": body_tokens,
            "reference_tokens": reference_tokens,
            "skill_context_actual": metadata_tokens + body_tokens + reference_tokens,
            "references": references,
        })

    pairs = []
    for task in sorted({sample["task"] for sample in samples}):
        a = next(sample for sample in samples if sample["task"] == task and sample["group"] == "A")
        b = next(sample for sample in samples if sample["task"] == task and sample["group"] == "B")
        saving = (a["skill_context_actual"] - b["skill_context_actual"]) / a["skill_context_actual"]
        pairs.append({
            "task": task,
            "in_followup_scope": task in SCOPE_TASKS,
            "a_tokens": a["skill_context_actual"],
            "b_tokens": b["skill_context_actual"],
            "saving_pct": round(saving * 100, 2),
            "a_opened": a["opened_references"],
            "b_opened": b["opened_references"],
        })

    scoped = [pair for pair in pairs if pair["in_followup_scope"]]
    mean_saving = sum(pair["saving_pct"] for pair in scoped) / len(scoped)
    report = {
        "tokenizer": str(tokenizer_path),
        "method": ("opened_references from the session command log; metadata + SKILL.md "
                   "body + those references; tokenizer estimate, not API usage"),
        "caveat": ("API input_tokens is not used here. It includes the harness system "
                   "prompt and every tool turn and must not be reported as skill tokens."),
        "samples": samples,
        "pairs": pairs,
        "scope": {
            "tasks": SCOPE_TASKS,
            "mean_saving_pct": round(mean_saving, 2),
        },
    }
    target = HERE / "followup-token.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")

    print("%-8s %8s %8s %8s" % ("task", "A tok", "B tok", "saving"))
    for pair in pairs:
        print("%-8s %8d %8d %7.2f%%%s" % (
            pair["task"], pair["a_tokens"], pair["b_tokens"], pair["saving_pct"],
            "  *" if pair["in_followup_scope"] else ""))
    print("scope mean saving %.2f%%" % mean_saving)
    print("wrote", target)


if __name__ == "__main__":
    main()
