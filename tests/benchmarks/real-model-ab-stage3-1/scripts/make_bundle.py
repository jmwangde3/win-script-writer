#!/usr/bin/env python3
"""Build the eight new stage-3.1 samples (BAT A2/B2, PS51 A2/B2).

Existing stage-3 BAT and PS51 samples are kept and merged later; this bundle only holds
the new pairs.

Usage::

    python tests/benchmarks/real-model-ab-stage3-1/scripts/make_bundle.py --root <root>
"""

from __future__ import annotations

import argparse
import importlib.util
import pathlib
import random
import secrets
import shutil

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
QUALITY_AB = BENCH / "quality-ab"

spec = importlib.util.spec_from_file_location("qa_prepare", QUALITY_AB / "prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

SLOTS = ([("bat", "A"), ("bat", "B"), ("ps51", "A"), ("ps51", "B")] * 2)
TASK_IDS = {"bat": "bat-01", "ps51": "ps51-01"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
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
    manifest = {"schema": 1, "run_id": root.name, "seed": seed, "samples": [], "model": {
        "id": "gpt-6-luna", "version": "not exposed by Codex CLI",
        "client": "codex-cli 0.167.0-alpha.3.2",
        "reasoning_effort": "CLI default (medium)",
    }}
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
        (sample / "PROMPT.md").write_text(prepare.build_prompt(task),
                                          encoding="utf-8", newline="\n")
        (sample / "run-log.csv").write_text(
            prepare.run_log_text(sid, task["loads"]), encoding="utf-8", newline="\n")
        (sample / "answer.md").write_text(prepare.ANSWER_PLACEHOLDER,
                                          encoding="utf-8", newline="\n")

        mapping[sid] = {"task": task_key, "task_id": task["task_id"], "group": group}
        manifest["samples"].append({
            "sample_id": sid, "task": task_key, "task_id": task["task_id"],
            "group": group, "planned_references": task["loads"],
            "declared_loads": task["loads"],
            "prompt_sha256": prepare.sha256(sample / "PROMPT.md"),
        })

    prepare.write_json(bundle / "SEALED-mapping.json", mapping)
    prepare.write_json(bundle / "manifest.json", manifest)
    (root / "run-order.txt").write_text(
        "\n".join("%s %s %s" % (item["sample_id"], item["task"], item["group"])
                  for item in manifest["samples"]) + "\n",
        encoding="utf-8", newline="\n")
    for item in manifest["samples"]:
        print(item["sample_id"], item["task"], item["group"])


if __name__ == "__main__":
    main()
