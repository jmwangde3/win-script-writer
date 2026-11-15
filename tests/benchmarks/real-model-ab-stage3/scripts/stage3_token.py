#!/usr/bin/env python3
"""Token context for the ten fresh stage-3 samples, from their own opened references.

Same tokenizer and same formula as the follow-up report: metadata + SKILL.md body + the
references the session actually opened. Not API usage.

Usage::

    python tests/benchmarks/real-model-ab-stage3/scripts/stage3_token.py --root <root>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
SNAPSHOTS = {"A": BENCH / "baseline" / "v1.0.4", "B": BENCH / "candidate" / "v1.1.0"}


def load_compute():
    spec = importlib.util.spec_from_file_location("wsw_compute", BENCH / "compute.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    bundle = root / "bundle"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    compute = load_compute()
    tokenizer_path = pathlib.Path(compute.find_tokenizer(None))
    tokenizer = compute.load_tokenizer(str(tokenizer_path))

    samples = []
    for sample in manifest["samples"]:
        sid = sample["sample_id"]
        with (bundle / sid / "run-log.csv").open(encoding="utf-8", newline="") as handle:
            log = next(csv.DictReader(handle))
        snapshot = SNAPSHOTS[sample["group"]]
        skill = (snapshot / "SKILL.md").read_text(encoding="utf-8")
        frontmatter, body = compute.split_frontmatter(skill)
        metadata = compute.count(tokenizer, compute.description_of(frontmatter))
        body_tokens = compute.count(tokenizer, body)
        opened = [item for item in (log["opened_references"] or "").split(";")
                  if item and item not in ("SKILL.md", "README.md")]
        reference_tokens = 0
        for item in opened:
            path = snapshot / item
            if path.is_file():
                reference_tokens += compute.count(tokenizer, path.read_text(encoding="utf-8"))
        samples.append({
            "sample_id": sid,
            "task": sample["task"],
            "group": sample["group"],
            "opened_references": opened,
            "metadata_tokens": metadata,
            "body_tokens": body_tokens,
            "reference_tokens": reference_tokens,
            "skill_context": metadata + body_tokens + reference_tokens,
        })

    tasks = []
    for task in ("ps51", "bat", "safety"):
        a = [item["skill_context"] for item in samples if item["task"] == task and item["group"] == "A"]
        b = [item["skill_context"] for item in samples if item["task"] == task and item["group"] == "B"]
        mean_a = sum(a) / len(a)
        mean_b = sum(b) / len(b)
        tasks.append({
            "task": task,
            "A_samples": len(a),
            "B_samples": len(b),
            "A_mean_tokens": round(mean_a, 1),
            "B_mean_tokens": round(mean_b, 1),
            "saving_percent": round((mean_a - mean_b) / mean_a * 100, 2),
        })
    total_a = sum(item["skill_context"] for item in samples if item["group"] == "A")
    total_b = sum(item["skill_context"] for item in samples if item["group"] == "B")
    payload = {
        "generated": "2026-11-15",
        "estimate": True,
        "api_usage_used": False,
        "tokenizer": "DeepSeek V4 offline tokenizer",
        "tokenizer_sha256": hashlib.sha256(tokenizer_path.read_bytes()).hexdigest(),
        "method": "metadata + SKILL.md body + opened_references; tokenizer estimate",
        "samples": samples,
        "tasks": tasks,
        "overall": {
            "A_total": total_a,
            "B_total": total_b,
            "weighted_saving": round((total_a - total_b) / total_a * 100, 2),
            "arithmetic_mean": round(sum(item["saving_percent"] for item in tasks) / len(tasks), 2),
        },
    }
    target = HERE / "stage3-token.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    for item in tasks:
        print("%s A=%.1f B=%.1f saving=%.2f%%" % (
            item["task"], item["A_mean_tokens"], item["B_mean_tokens"],
            item["saving_percent"]))
    print("overall weighted %.2f%% arithmetic %.2f%%" % (
        payload["overall"]["weighted_saving"], payload["overall"]["arithmetic_mean"]))
    print("wrote", target)


if __name__ == "__main__":
    main()
