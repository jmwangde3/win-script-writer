#!/usr/bin/env python3
"""Build the ten-sample stage-3 bundle in the temp test root.

SAFETY A x3 / B x3, BAT A x1 / B x1, PS51 A x1 / B x1, shuffled. Prompts are the ones
from `../quality-ab/tasks.json`, unchanged. The SAFETY planned references use the
corrected route from `routing-investigation.md` (encoding-matrix + powershell-51), while
the original declared list is kept in the manifest for traceability.

Usage::

    python tests/benchmarks/real-model-ab-stage3/scripts/make_bundle.py --root <temp root>
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import random
import secrets
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
QUALITY_AB = BENCH / "quality-ab"

spec = importlib.util.spec_from_file_location("qa_prepare", QUALITY_AB / "prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

SLOTS = ([("safety", "A")] * 3 + [("safety", "B")] * 3
         + [("bat", "A"), ("bat", "B"), ("ps51", "A"), ("ps51", "B")])

TASK_IDS = {"safety": "tool-02", "bat": "bat-01", "ps51": "ps51-01"}

CORRECTED_LOADS = {
    "safety": ["references/encoding-matrix.md", "references/powershell-51.md"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="stage-3 temp root")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    bundle = root / "bundle"
    if bundle.exists():
        raise SystemExit("refusing to reuse an existing bundle: %s" % bundle)

    plan = prepare.load_plan()
    tasks = {task["task_id"]: task for task in plan["tasks"]}
    snapshots = {group: prepare.snapshot_path(group, plan) for group in ("A", "B")}
    for group, path in snapshots.items():
        prepare.verify_snapshot(group, path)

    seed = args.seed if args.seed is not None else secrets.randbits(63)
    order = list(SLOTS)
    random.Random(seed).shuffle(order)

    bundle.mkdir(parents=True)
    manifest = {
        "schema": 1,
        "run_id": root.name,
        "seed": seed,
        "model": {
            "id": "gpt-6-luna",
            "version": "not exposed by Codex CLI",
            "client": "codex-cli 0.167.0-alpha.3.2",
            "reasoning_effort": "CLI default (medium)",
            "temperature": "not exposed",
            "top_p": "not exposed",
            "sampling_seed": "not exposed",
        },
        "samples": [],
    }
    mapping = {}
    for index, (task_key, group) in enumerate(order, start=1):
        sid = "S%02d" % index
        sample = bundle / sid
        skill = sample / "skill"
        skill.mkdir(parents=True)
        for rel in prepare.SNAPSHOTS[group]["copy"]:
            destination = skill / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snapshots[group] / rel, destination)

        task = tasks[TASK_IDS[task_key]]
        prompt = prepare.build_prompt(task)
        (sample / "PROMPT.md").write_text(prompt, encoding="utf-8", newline="\n")

        planned = CORRECTED_LOADS.get(task_key) or task["loads"]
        (sample / "run-log.csv").write_text(
            prepare.run_log_text(sid, planned), encoding="utf-8", newline="\n")
        (sample / "answer.md").write_text(prepare.ANSWER_PLACEHOLDER,
                                          encoding="utf-8", newline="\n")

        mapping[sid] = {"task": task_key, "task_id": task["task_id"], "group": group}
        manifest["samples"].append({
            "sample_id": sid,
            "task": task_key,
            "task_id": task["task_id"],
            "group": group,
            "planned_references": planned,
            "declared_loads": task["loads"],
            "declared_loads_baseline": task.get("loads_baseline") or task["loads"],
            "prompt_sha256": prepare.sha256(sample / "PROMPT.md"),
        })

    prepare.write_json(bundle / "SEALED-mapping.json", mapping)
    prepare.write_json(bundle / "manifest.json", manifest)
    (root / "run-order.txt").write_text(
        "\n".join("%s %s %s" % (item["sample_id"], item["task"], item["group"])
                  for item in manifest["samples"]) + "\n",
        encoding="utf-8", newline="\n")
    print("bundle", bundle)
    for item in manifest["samples"]:
        print(item["sample_id"], item["task"], item["group"])


if __name__ == "__main__":
    main()
