# -*- coding: utf-8 -*-
"""Contract tests for the quality A/B toolchain.

The A/B itself needs a pinned model and cannot run here. What can be tested is the part
that is mechanical and where a mistake would silently invalidate a future run:

  * the task set really covers 11 tasks and 8 areas, and ``bash-01`` is copied verbatim
    from the benchmark rather than re-worded;
  * the blind assignment is reproducible from a seed, unrecoverable without it, and never
    printed by ``--dry-run``;
  * the two groups get byte-identical prompts, because a prompt that names the sample is a
    prompt that can leak the group;
  * the run log is pre-filled and never invents a token count;
  * the builder refuses a non-empty target, never deletes existing files, and leaves
    nothing behind when a snapshot or a hash check fails;
  * the scoring packet cannot be produced before every answer exists, and cannot be turned
    back into A/B without the key.

Run with:
    python -m unittest discover -s tests/evals -v
"""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import pathlib
import shutil
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
QA_DIR = REPO_ROOT / "tests" / "benchmarks" / "quality-ab"
BENCH_TASKS = REPO_ROOT / "tests" / "benchmarks" / "tasks.json"
SEED = 20261114


def load_tool(name):
    spec = importlib.util.spec_from_file_location("quality_ab_" + name,
                                                  QA_DIR / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load_tool("prepare")
packets = load_tool("make_scoring_packet")
unseal_tool = load_tool("unseal")


class BundleCase(unittest.TestCase):
    """One shared build; tests that write get their own directory under the same temp."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp(prefix="wsw-qa-test-"))
        cls.plan = prepare.load_plan()
        cls.run_dir = cls.tmp / "run"
        prepare.build(cls.plan, cls.run_dir, SEED)
        cls.manifest = json.loads(
            (cls.run_dir / "manifest.json").read_text(encoding="utf-8"))
        cls.sealed = json.loads(
            (cls.run_dir / "SEALED-mapping.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def build_elsewhere(self, name, seed):
        out = self.tmp / name
        prepare.build(self.plan, out, seed)
        return out

    def sample_of(self, task_id, group):
        for sample_id, entry in self.sealed.items():
            if entry["task_id"] == task_id and entry["group"] == group:
                return sample_id
        self.fail("no sample for %s / %s" % (task_id, group))


class TaskSetTests(BundleCase):
    def test_task_count_is_eleven(self):
        self.assertEqual(len(self.plan["tasks"]), 11)
        self.assertEqual(len(self.sealed), 22)

    def test_eight_areas_and_they_match_the_task_list(self):
        self.assertEqual(len(self.plan["coverage"]), 8)
        covered = sorted(task_id for ids in self.plan["coverage"].values()
                         for task_id in ids)
        self.assertEqual(covered,
                         sorted(task["task_id"] for task in self.plan["tasks"]))

    def test_task_ids_are_unique(self):
        ids = [task["task_id"] for task in self.plan["tasks"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_task_is_built_in_both_groups(self):
        groups = {}
        for entry in self.sealed.values():
            groups.setdefault(entry["task_id"], []).append(entry["group"])
        self.assertEqual(len(groups), 11)
        for task_id, seen in groups.items():
            self.assertEqual(sorted(seen), ["A", "B"], task_id)

    def test_prompts_are_byte_identical_across_groups(self):
        for task in self.plan["tasks"]:
            digests = {prepare.sha256(self.run_dir / self.sample_of(task["task_id"], group)
                                      / "PROMPT.md")
                       for group in ("A", "B")}
            self.assertEqual(len(digests), 1, task["task_id"])

    def test_every_load_exists_in_its_snapshot(self):
        for group, key in (("A", "loads_baseline"), ("B", "loads")):
            root = prepare.snapshot_path(group, self.plan)
            for task in self.plan["tasks"]:
                for rel in task.get(key) or []:
                    self.assertTrue((root / rel).is_file(),
                                    "%s %s: %s" % (group, task["task_id"], rel))

    def test_bash01_is_copied_verbatim_from_the_benchmark(self):
        source = {task["task_id"]: task for task in
                  json.loads(BENCH_TASKS.read_text(encoding="utf-8"))["tasks"]}
        target = {task["task_id"]: task for task in self.plan["tasks"]}
        self.assertIn("bash-01", target)
        for field in ("prompt", "expected_behavior", "required_checks",
                      "forbidden_actions", "loads"):
            self.assertEqual(target["bash-01"][field], source["bash-01"][field], field)

    def test_git_bash_is_covered(self):
        self.assertEqual(self.plan["coverage"]["git-bash"], ["bash-01"])


class BlindAssignmentTests(BundleCase):
    def test_same_seed_reproduces_the_same_order(self):
        other = self.build_elsewhere("same-seed", SEED)
        sealed = json.loads((other / "SEALED-mapping.json").read_text(encoding="utf-8"))
        self.assertEqual(sealed, self.sealed)

    def test_different_seeds_produce_different_orders(self):
        first = json.loads((self.build_elsewhere("seed-1", 1) / "SEALED-mapping.json")
                           .read_text(encoding="utf-8"))
        second = json.loads((self.build_elsewhere("seed-2", 2) / "SEALED-mapping.json")
                            .read_text(encoding="utf-8"))
        self.assertNotEqual(first, second)
        self.assertEqual(sorted(map(str, first.values())),
                         sorted(map(str, second.values())))

    def test_dry_run_never_prints_the_group(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            prepare.dry_run(self.plan, SEED)
        text = buffer.getvalue()
        self.assertNotIn("group", text.lower())
        self.assertNotRegex(text, r"\b[AB]\b")
        self.assertIn("S01", text)
        self.assertIn("S22", text)

    def test_dry_run_writes_nothing(self):
        before = sorted(path.name for path in self.tmp.iterdir())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            prepare.dry_run(self.plan, None)
        self.assertEqual(sorted(path.name for path in self.tmp.iterdir()), before)

    def test_seed_is_only_in_the_executor_manifest(self):
        manifest = json.loads(
            (self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIsInstance(manifest["seed"], int)
        prompt = (self.run_dir / "S01" / "PROMPT.md").read_text(encoding="utf-8")
        self.assertNotIn(str(manifest["seed"]), prompt)


class PromptAndLogTests(BundleCase):
    def test_prompt_carries_no_sample_identifier(self):
        for sample_id in self.sealed:
            text = (self.run_dir / sample_id / "PROMPT.md").read_text(encoding="utf-8")
            self.assertNotIn(sample_id, text)
            self.assertNotIn("Sample ", text)
            self.assertNotIn("SEALED", text)
            self.assertNotIn("run-log", text)
            self.assertNotIn("Group", text)

    def test_run_log_is_prefilled_and_has_nineteen_columns(self):
        self.assertEqual(len(prepare.RUN_LOG_COLUMNS), 19)
        for sample_id in self.sealed:
            with (self.run_dir / sample_id / "run-log.csv").open(
                    encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], prepare.RUN_LOG_COLUMNS)
            self.assertEqual(len(rows[1]), 19)
            self.assertEqual(rows[1][0], sample_id)

    def test_run_log_leaves_token_usage_empty(self):
        index = {name: position for position, name in enumerate(prepare.RUN_LOG_COLUMNS)}
        for sample_id in self.sealed:
            with (self.run_dir / sample_id / "run-log.csv").open(
                    encoding="utf-8", newline="") as handle:
                row = list(csv.reader(handle))[1]
            for column in ("prompt_tokens", "completion_tokens", "total_tokens",
                           "cached_tokens"):
                self.assertEqual(row[index[column]], "",
                                 "%s invented %s" % (sample_id, column))

    def test_planned_references_follow_the_group(self):
        index = prepare.RUN_LOG_COLUMNS.index("planned_references")
        task = next(task for task in self.plan["tasks"] if task["task_id"] == "py-02")
        for group, expected in (("A", task["loads_baseline"]), ("B", task["loads"])):
            sample_id = self.sample_of("py-02", group)
            with (self.run_dir / sample_id / "run-log.csv").open(
                    encoding="utf-8", newline="") as handle:
                row = list(csv.reader(handle))[1]
            self.assertEqual(row[index], ";".join(expected))

    def test_prepare_does_not_estimate_tokens(self):
        source = (QA_DIR / "prepare.py").read_text(encoding="utf-8")
        self.assertNotIn("import tokenizers", source)
        self.assertNotIn("tiktoken", source)
        self.assertNotIn("len(text)", source)


class FilesystemSafetyTests(BundleCase):
    def test_refuses_a_non_empty_target_and_keeps_its_files(self):
        target = self.tmp / "occupied"
        target.mkdir()
        (target / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(prepare.BuildError):
            prepare.build(self.plan, target, SEED)
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep")
        self.assertEqual(sorted(path.name for path in target.iterdir()), ["keep.txt"])

    def test_refuses_a_file_as_target(self):
        target = self.tmp / "file-target"
        target.write_text("x", encoding="utf-8")
        with self.assertRaises(prepare.BuildError):
            prepare.build(self.plan, target, SEED)

    def test_refuses_to_write_inside_the_repository(self):
        target = QA_DIR / "_generated-samples"
        try:
            with self.assertRaises(prepare.BuildError):
                prepare.build(self.plan, target, SEED)
        finally:
            if target.exists():
                shutil.rmtree(target)
        self.assertFalse(target.exists())

    def test_missing_snapshot_file_fails_and_writes_nothing(self):
        frozen = self.tmp / "frozen-a"
        shutil.copytree(prepare.snapshot_path("A", self.plan), frozen)
        (frozen / "references" / "git-bash.md").unlink()
        plan = json.loads(json.dumps(self.plan))
        plan["groups"]["A"]["snapshot"] = str(frozen)
        target = self.tmp / "missing-snapshot-run"
        with self.assertRaises(prepare.BuildError):
            prepare.build(plan, target, SEED)
        self.assertFalse(target.exists())

    def test_unexpected_snapshot_file_fails(self):
        frozen = self.tmp / "extra-b"
        shutil.copytree(prepare.snapshot_path("B", self.plan), frozen)
        (frozen / "references" / "notes-from-someone.md").write_text("x", encoding="utf-8")
        plan = json.loads(json.dumps(self.plan))
        plan["groups"]["B"]["snapshot"] = str(frozen)
        with self.assertRaises(prepare.BuildError):
            prepare.build(plan, self.tmp / "extra-run", SEED)

    def test_changelog_is_never_copied(self):
        for sample_id, entry in self.sealed.items():
            skill = self.run_dir / sample_id / "skill"
            self.assertFalse((skill / "CHANGELOG.md").exists(), sample_id)
            expected = 12 if entry["group"] == "A" else 14
            self.assertEqual(len(list(skill.rglob("*.md"))), expected, sample_id)

    def test_a_tampered_copy_aborts_the_build(self):
        original = prepare.shutil.copyfile

        def corrupt(source, destination):
            original(source, destination)
            pathlib.Path(destination).write_text("tampered", encoding="utf-8")

        prepare.shutil.copyfile = corrupt
        target = self.tmp / "tampered-run"
        try:
            with self.assertRaises(prepare.BuildError):
                prepare.build(self.plan, target, SEED)
        finally:
            prepare.shutil.copyfile = original
        self.assertFalse(target.exists())

    def test_a_file_changed_after_the_build_is_detected(self):
        root = self.tmp / "post-build"
        manifest = prepare.build(self.plan, root, SEED)
        sample_id = manifest["samples_meta"][0]["sample_id"]
        (root / sample_id / "skill" / "SKILL.md").write_text("tampered", encoding="utf-8")
        with self.assertRaises(prepare.BuildError):
            prepare._verify_built(root, manifest)


class AnsweredCase(BundleCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.answered = cls.tmp / "answered"
        shutil.copytree(cls.run_dir, cls.answered)
        answer = ("用于工具链自检的回答。\n\n"
                  "```powershell\nWrite-Output 'ok'\n```\n")
        for sample_id in cls.sealed:
            (cls.answered / sample_id / "answer.md").write_text(
                answer, encoding="utf-8", newline="\n")

    def build_packet(self, name, seed=7):
        out = self.tmp / name
        key = self.tmp / (name + ".key.json")
        packets.build_packet(self.answered, out, seed=seed, key_path=key)
        return out, key

    def write_scores(self, name, key_map, base_a=80, base_b=84, drop=None):
        path = self.tmp / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=unseal_tool.SCORE_COLUMNS,
                                    lineterminator="\n")
            writer.writeheader()
            for answer_id, entry in sorted(key_map.items()):
                if answer_id == drop:
                    continue
                base = base_a if entry["group"] == "A" else base_b
                row = {"answer_id": answer_id, "notes": "test row"}
                for dimension, _label, maximum in unseal_tool.DIMENSIONS:
                    row[dimension] = base * maximum // 100
                writer.writerow(row)
        return path


class ScoringPacketTests(AnsweredCase):
    def test_packet_needs_every_answer(self):
        broken = self.tmp / "unfinished"
        shutil.copytree(self.answered, broken)
        first = sorted(self.sealed)[0]
        (broken / first / "answer.md").write_text(prepare.ANSWER_PLACEHOLDER,
                                                  encoding="utf-8")
        target = self.tmp / "packet-unfinished"
        key = self.tmp / "unfinished.key.json"
        with self.assertRaises(packets.PacketError):
            packets.build_packet(broken, target, seed=1, key_path=key)
        self.assertFalse(target.exists())
        self.assertFalse(key.exists())

    def test_packet_rejects_an_empty_answer(self):
        broken = self.tmp / "empty-answer"
        shutil.copytree(self.answered, broken)
        first = sorted(self.sealed)[0]
        (broken / first / "answer.md").write_text("   \n", encoding="utf-8")
        with self.assertRaises(packets.PacketError):
            packets.build_packet(broken, self.tmp / "packet-empty", seed=1,
                                 key_path=self.tmp / "empty.key.json")

    def test_packet_has_every_answer_and_equal_groups(self):
        out, key_path = self.build_packet("packet-count")
        self.assertEqual(len(list((out / "answers").iterdir())), 22)
        key = json.loads(key_path.read_text(encoding="utf-8"))["mapping"]
        groups = {"A": 0, "B": 0}
        for entry in key.values():
            groups[entry["group"]] += 1
        self.assertEqual(groups, {"A": 11, "B": 11})

    def test_packet_hides_group_and_original_ids(self):
        out, _key = self.build_packet("packet-leak")
        needles = ["group", "sample_id", "sealed-mapping", "manifest.json",
                   "v1.0.4", "v1.1.0", "seed"]
        needles += [task["task_id"].lower() for task in self.plan["tasks"]]
        for path in out.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            for needle in needles:
                self.assertNotIn(needle, text, "%s leaks %r" % (path.name, needle))
            self.assertNotRegex(path.name, r"^S\d{2}")

    def test_key_is_outside_the_packet_and_restores_the_groups(self):
        out, key_path = self.build_packet("packet-key")
        with self.assertRaises(ValueError):
            key_path.resolve().relative_to(out.resolve())
        key = json.loads(key_path.read_text(encoding="utf-8"))["mapping"]
        self.assertEqual(sorted(key), ["R%03d" % index for index in range(1, 23)])
        for entry in key.values():
            original = self.sealed[entry["sample_id"]]
            self.assertEqual(entry["group"], original["group"])
            self.assertEqual(entry["task_id"], original["task_id"])

    def test_seed_controls_the_anonymisation(self):
        _out1, key1 = self.build_packet("packet-seed-a", seed=11)
        _out2, key2 = self.build_packet("packet-seed-b", seed=11)
        _out3, key3 = self.build_packet("packet-seed-c", seed=12)
        first = json.loads(key1.read_text(encoding="utf-8"))["mapping"]
        second = json.loads(key2.read_text(encoding="utf-8"))["mapping"]
        third = json.loads(key3.read_text(encoding="utf-8"))["mapping"]
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)

    def test_packet_refuses_a_non_empty_target(self):
        target = self.tmp / "packet-occupied"
        target.mkdir()
        (target / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(packets.PacketError):
            packets.build_packet(self.answered, target, seed=1,
                                 key_path=self.tmp / "occupied.key.json")
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_packet_never_contains_a_skill_document(self):
        out, _key = self.build_packet("packet-no-docs")
        for path in out.rglob("SKILL.md"):
            self.fail("packet contains a skill document: %s" % path)
        self.assertFalse((out / "skill").exists())


class UnsealTests(AnsweredCase):
    def _key_and_packet(self, name="packet-unseal"):
        out, key_path = self.build_packet(name, seed=3)
        key = json.loads(key_path.read_text(encoding="utf-8"))["mapping"]
        return out, key_path, key

    @staticmethod
    def _rows(path):
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_unseal_restores_the_groups_and_reports_the_delta(self):
        _out, key_path, key = self._key_and_packet()
        scores = self.write_scores("scores-one.csv", key)
        report = unseal_tool.unseal(key_path, [scores], self.tmp / "report-one.md")
        self.assertIn("| A (v1.0.4 Chinese) | 11 |", report)
        self.assertIn("| B (v1.1.0 English) | 11 |", report)
        self.assertIn("B - A = +2.00", report)

    def test_unseal_refuses_an_unscored_answer(self):
        _out, key_path, key = self._key_and_packet("packet-unscored")
        scores = self.write_scores("scores-drop.csv", key, drop="R001")
        with self.assertRaises(unseal_tool.UnsealError):
            unseal_tool.unseal(key_path, [scores], self.tmp / "report-drop.md")

    def test_unseal_refuses_a_blank_score(self):
        _out, key_path, key = self._key_and_packet("packet-blank")
        path = self.tmp / "scores-blank.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=unseal_tool.SCORE_COLUMNS,
                                    lineterminator="\n")
            writer.writeheader()
            for answer_id in sorted(key):
                writer.writerow({"answer_id": answer_id})
        with self.assertRaises(unseal_tool.UnsealError):
            unseal_tool.unseal(key_path, [path], self.tmp / "report-blank.md")

    def test_unseal_refuses_an_out_of_range_score(self):
        _out, key_path, key = self._key_and_packet("packet-range")
        scores = self.write_scores("scores-range.csv", key)
        rows = self._rows(scores)
        rows[0]["correctness"] = "31"
        with scores.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=unseal_tool.SCORE_COLUMNS,
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaises(unseal_tool.UnsealError):
            unseal_tool.unseal(key_path, [scores], self.tmp / "report-range.md")

    def test_unseal_refuses_a_duplicate_answer(self):
        _out, key_path, key = self._key_and_packet("packet-dupe")
        scores = self.write_scores("scores-dupe.csv", key)
        rows = self._rows(scores)
        rows.append(dict(rows[0]))
        with scores.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=unseal_tool.SCORE_COLUMNS,
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        with self.assertRaises(unseal_tool.UnsealError):
            unseal_tool.unseal(key_path, [scores], self.tmp / "report-dupe.md")

    def test_two_reviewers_are_averaged_and_disagreements_are_flagged(self):
        _out, key_path, key = self._key_and_packet("packet-two")
        first = self.write_scores("scores-reviewer-a.csv", key, base_a=80, base_b=84)
        second = self.write_scores("scores-reviewer-b.csv", key, base_a=60, base_b=84)
        report = unseal_tool.unseal(key_path, [first, second],
                                    self.tmp / "report-two.md")
        self.assertIn("Reviewer disagreement over 10 points", report)
        self.assertIn("| R", report)
        self.assertIn("B - A = +12.00", report)

    def test_unseal_refuses_to_overwrite_a_report(self):
        _out, key_path, key = self._key_and_packet("packet-overwrite")
        scores = self.write_scores("scores-overwrite.csv", key)
        target = self.tmp / "report-overwrite.md"
        unseal_tool.unseal(key_path, [scores], target)
        with self.assertRaises(unseal_tool.UnsealError):
            unseal_tool.unseal(key_path, [scores], target)


if __name__ == "__main__":
    unittest.main()
