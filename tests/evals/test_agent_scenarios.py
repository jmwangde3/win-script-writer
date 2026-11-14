# -*- coding: utf-8 -*-
"""Routing contract for the 16 evaluation scenarios in agent-scenarios.md.

What this can and cannot check
------------------------------
It cannot check what an agent loaded: nothing in this repository can observe
another process's file reads. What it can check is the part that would silently
rot -- that every positive scenario names a reference that SKILL.md actually
routes, that a negative scenario names none, and that the first hop (entry file
plus one reference) stays small enough for progressive disclosure to mean
anything.

Token counts are deliberately absent. Byte counts are exact and are what is
asserted; bytes are not tokens, and reporting an estimated token number here
would be the same unverified claim this release exists to remove.

Run with:
    python -m unittest discover -s tests/evals -v
"""

from __future__ import annotations

import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "SKILL.md"
REFERENCES = REPO_ROOT / "references"

#: (id, one-line task, expected reference) for the tasks that must trigger.
POSITIVE = [
    ("P1", "PS 5.1 script with Chinese output", "powershell-51.md"),
    ("P2", "PowerShell 7 concurrent download script", "powershell-7.md"),
    ("P3", "one script for both 5.1 and 7", "dual-version-compatibility.md"),
    ("P4", ".bat that deletes old files under a Chinese path", "cmd-bat.md"),
    ("P5", "Chinese path plus nested quotes on the command line", "execution.md"),
    ("P6", "what encoding is this file, 5.1 reads it as mojibake", "encoding-matrix.md"),
    ("P7", "write Chinese content into build.ps1 without breaking it", "security.md"),
    ("P8", "every Chinese character in my .ps1 is mojibake, one fix", "troubleshooting.md"),
    ("P9", "Python script scanning a directory and writing json on Windows", "python.md"),
    ("P10", "git status shows Chinese file names as octal escapes in Git Bash", "git-bash.md"),
    ("P11", "a .py starts with # coding: gbk and I want to convert it", "python-source-encoding.md"),
    ("P12", "why did the detector say WARN instead of FAIL on this declaration",
     "appendix-codec-evidence.md"),
]

#: Tasks that must not trigger. They share vocabulary with the skill on purpose.
NEGATIVE = [
    ("N1", "bash script that deletes /var/log files older than seven days"),
    ("N2", "quicksort in JavaScript"),
    ("N3", "explain the TCP three way handshake"),
    ("N4", "an LRU cache class in Python"),
]

#: Entry file plus one reference. Beyond this, "load one page on demand" stops
#: being cheaper than reading everything, and the routing table loses its point.
MAX_FIRST_HOP_BYTES = 20000


def read_skill():
    return SKILL.read_text(encoding="utf-8")


class TestScenarioRouting(unittest.TestCase):
    def test_every_positive_scenario_names_a_real_reference(self):
        for scenario, task, reference in POSITIVE:
            with self.subTest(scenario=scenario, task=task):
                self.assertTrue((REFERENCES / reference).exists(), reference)

    def test_every_positive_scenario_is_reachable_from_the_entry_file(self):
        # The routing table is the only mechanism that makes a reference
        # reachable. A scenario whose page is not routed is a scenario an agent
        # can only fail.
        skill = read_skill()
        for scenario, task, reference in POSITIVE:
            with self.subTest(scenario=scenario, task=task):
                self.assertIn(
                    "references/" + reference,
                    skill,
                    "%s routes nowhere; SKILL.md never mentions %s" % (scenario, reference),
                )

    def test_the_scenarios_cover_every_reference(self):
        # If a reference is never exercised by a scenario, nothing checks that it
        # is still the right page for its subject.
        covered = {reference for _, _, reference in POSITIVE}
        on_disk = {path.name for path in REFERENCES.glob("*.md")}
        self.assertEqual(on_disk - covered, set(), "no scenario exercises these pages")

    def test_negative_scenarios_do_not_name_a_reference(self):
        for scenario, task in NEGATIVE:
            with self.subTest(scenario=scenario):
                for path in REFERENCES.glob("*.md"):
                    self.assertNotIn(path.name, task)
                    self.assertNotIn(path.stem, task)

    def test_scenario_count_is_within_the_planned_range(self):
        # One positive scenario per reference is the floor: a page no scenario
        # exercises is a page nothing keeps honest. The ceiling leaves room for
        # negatives only, so the set cannot grow into a checklist of positives.
        total = len(POSITIVE) + len(NEGATIVE)
        floor = len(list(REFERENCES.glob("*.md"))) + len(NEGATIVE)
        self.assertGreaterEqual(total, 10, "the plan called for at least 10 scenarios")
        self.assertLessEqual(total, floor + 2)

    def test_negative_scenarios_are_a_real_minority(self):
        # A checklist that is mostly negatives measures nothing about triggering.
        self.assertGreater(len(POSITIVE), len(NEGATIVE))


class TestFirstHopCost(unittest.TestCase):
    def test_entry_file_plus_one_reference_stays_small(self):
        entry = SKILL.stat().st_size
        for scenario, task, reference in POSITIVE:
            with self.subTest(scenario=scenario):
                hop = entry + (REFERENCES / reference).stat().st_size
                self.assertLessEqual(
                    hop,
                    MAX_FIRST_HOP_BYTES,
                    "%s needs %d bytes on the first hop" % (scenario, hop),
                )

    def test_reading_everything_is_measurably_worse(self):
        # The number that motivates routing at all: every page plus the entry
        # file. If this ever approaches the single-page cost, the split stopped
        # paying for itself.
        entry = SKILL.stat().st_size
        everything = entry + sum(p.stat().st_size for p in REFERENCES.glob("*.md"))
        single = max((REFERENCES / ref).stat().st_size for _, _, ref in POSITIVE)
        self.assertGreater(everything, (entry + single) * 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
