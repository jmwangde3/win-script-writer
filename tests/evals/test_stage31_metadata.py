# -*- coding: utf-8 -*-
"""Metadata contract for the quality A/B task set.

The SAFETY task was declared against `security.md` + `troubleshooting.md`, but the task
is an encoding audit and `SKILL.md` routes it to `encoding-matrix.md` +
`powershell-51.md`. Every session read the latter two. These tests keep the declared
route and the snapshots in agreement, so a future edit cannot reintroduce the mismatch.

Run with:
    python -m unittest discover -s tests/evals -v
"""

from __future__ import annotations

import json
import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TASKS = REPO_ROOT / "tests" / "benchmarks" / "quality-ab" / "tasks.json"
SNAPSHOTS = {
    "A": REPO_ROOT / "tests" / "benchmarks" / "baseline" / "v1.0.4",
    "B": REPO_ROOT / "tests" / "benchmarks" / "candidate" / "v1.1.0",
}


def load_plan() -> dict:
    return json.loads(TASKS.read_text(encoding="utf-8"))


class SafetyRouteTests(unittest.TestCase):
    def test_tool_02_loads_the_encoding_pages(self):
        plan = load_plan()
        task = next(item for item in plan["tasks"] if item["task_id"] == "tool-02")
        expected = ["references/encoding-matrix.md", "references/powershell-51.md"]
        self.assertEqual(task["loads"], expected)
        self.assertEqual(task["loads_baseline"], expected)

    def test_tool_02_no_longer_points_at_security_pages(self):
        plan = load_plan()
        task = next(item for item in plan["tasks"] if item["task_id"] == "tool-02")
        self.assertNotIn("references/security.md", task["loads"])
        self.assertNotIn("references/troubleshooting.md", task["loads"])


class SnapshotAgreementTests(unittest.TestCase):
    def test_every_load_resolves_in_its_snapshot(self):
        plan = load_plan()
        for task in plan["tasks"]:
            for key, group in (("loads", "B"), ("loads_baseline", "A")):
                references = task.get(key) or []
                self.assertTrue(references, "%s has an empty %s" % (task["task_id"], key))
                for reference in references:
                    self.assertTrue(
                        (SNAPSHOTS[group] / reference).is_file(),
                        "%s: %s missing from the %s snapshot"
                        % (task["task_id"], reference, group))

    def test_no_duplicate_or_absolute_loads(self):
        plan = load_plan()
        for task in plan["tasks"]:
            for key in ("loads", "loads_baseline"):
                references = task.get(key) or []
                self.assertEqual(len(references), len(set(references)),
                                 "%s has duplicate entries in %s" % (task["task_id"], key))
                for reference in references:
                    self.assertFalse(reference.startswith(("/", "\\")),
                                     "%s has an absolute load: %s"
                                     % (task["task_id"], reference))
                    self.assertNotIn("..", reference)

    def test_task_ids_are_unique_and_coverage_matches(self):
        plan = load_plan()
        ids = [task["task_id"] for task in plan["tasks"]]
        self.assertEqual(len(ids), len(set(ids)))
        covered = sorted(task_id for group in plan["coverage"].values()
                         for task_id in group)
        self.assertEqual(covered, sorted(ids))


if __name__ == "__main__":
    unittest.main()
