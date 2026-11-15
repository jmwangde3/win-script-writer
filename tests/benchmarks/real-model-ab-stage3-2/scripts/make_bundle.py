#!/usr/bin/env python3
"""Build the twelve stage-3.2 samples: BAT A3/B3 and PS51 A3/B3.

The prompts come from `../tasks.json`; the snapshots are the frozen v1.0.4 and v1.1.0
trees. A/B and task order are shuffled.

Usage::

    python tests/benchmarks/real-model-ab-stage3-2/scripts/make_bundle.py --root <root>
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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

SNAPSHOTS = {"A": BENCH / "baseline" / "v1.0.4", "B": BENCH / "candidate" / "v1.1.0"}
TASK_KEY = {"bat-codepage-01": "bat", "ps51-autowrite-01": "ps51"}
SLOTS = ([("bat", "A"), ("bat", "B"), ("ps51", "A"), ("ps51", "B")] * 3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    bundle = root / "bundle"
    if bundle.exists():
        raise SystemExit("refusing to reuse an existing bundle: %s" % bundle)

    plan = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))
    tasks = {task["task_id"]: task for task in plan["tasks"]}
    for group, path in SNAPSHOTS.items():
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
            shutil.copyfile(SNAPSHOTS[group] / rel, destination)

        task = tasks["bat-codepage-01" if task_key == "bat" else "ps51-autowrite-01"]
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
