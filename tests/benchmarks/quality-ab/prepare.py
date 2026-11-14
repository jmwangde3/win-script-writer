#!/usr/bin/env python3
"""Build the executor bundle for the v1.0.4 vs v1.1.0 model quality A/B.

What this does:

  * reads ``tasks.json`` next to this file (11 tasks, 8 areas)
  * for every task and both documentation snapshots, copies the *documentation only*
    into an isolated directory
  * shuffles the 22 (task, group) pairs into blind sample ids S01..S22. The seed is
    random by default and is written only to the executor's ``manifest.json``; it is
    never printed and never handed to a scorer
  * writes one prompt per sample, a pre-filled run log, an empty answer slot, the sealed
    mapping and the manifest with a SHA-256 for every input and output file

What this deliberately does **not** do:

  * it never calls a model, a CLI or an agent -- no answer is produced here
  * it never scores anything and never writes a scoring sheet -- that is
    ``make_scoring_packet.py``, which may only run after all answers exist
  * it never guesses token usage -- the log columns are filled from the API response or
    left empty

Safety rules, because this tool writes directories:

  * a non-empty target is refused, never cleaned
  * the whole bundle is built in a staging directory next to the target and renamed into
    place only after every check passes
  * a failure removes the staging directory and leaves the target untouched
  * writing inside the Git repository is refused, so generated samples cannot be committed
    by accident; the default target is the system temp directory

Usage::

    python tests/benchmarks/quality-ab/prepare.py                     # build into %TEMP%
    python tests/benchmarks/quality-ab/prepare.py --out D:/qa-run     # explicit target
    python tests/benchmarks/quality-ab/prepare.py --dry-run           # print ids, write nothing
    python tests/benchmarks/quality-ab/prepare.py --seed 1234         # reproducible order

Exit codes: 0 ok, 2 refused or invalid input (missing task, missing/mismatched snapshot,
non-empty target, target inside the repository).
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import pathlib
import random
import secrets
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]

EXPECTED_TASKS = 11
EXPECTED_AREAS = 8

BASELINE_FILES = [
    "SKILL.md",
    "README.md",
    "references/cmd-bat.md",
    "references/dual-version-compatibility.md",
    "references/encoding-matrix.md",
    "references/execution.md",
    "references/git-bash.md",
    "references/powershell-51.md",
    "references/powershell-7.md",
    "references/python.md",
    "references/security.md",
    "references/troubleshooting.md",
]

CANDIDATE_FILES = [
    "SKILL.md",
    "README.md",
    "references/appendix-codec-evidence.md",
    "references/cmd-bat.md",
    "references/dual-version-compatibility.md",
    "references/encoding-matrix.md",
    "references/execution.md",
    "references/git-bash.md",
    "references/powershell-51.md",
    "references/powershell-7.md",
    "references/python-source-encoding.md",
    "references/python.md",
    "references/security.md",
    "references/troubleshooting.md",
]

# ``copy`` is what a sample receives. ``disk_extra`` is allowed to exist in the snapshot
# but is never copied: CHANGELOG.md names the version and is release history, not
# documentation a model needs to answer, so it stays out of both bundles.
SNAPSHOTS = {
    "A": {"declared": "../baseline/v1.0.4", "copy": BASELINE_FILES, "disk_extra": []},
    "B": {"declared": "../candidate/v1.1.0", "copy": CANDIDATE_FILES,
          "disk_extra": ["CHANGELOG.md"]},
}

RUN_LOG_COLUMNS = [
    "sample_id",
    "model",
    "model_version",
    "client",
    "client_version",
    "session_id",
    "started_at",
    "finished_at",
    "temperature",
    "top_p",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
    "planned_references",
    "provided_references",
    "opened_references",
    "load_evidence",
    "notes",
]

ANSWER_PLACEHOLDER = "<!-- not answered yet: the model under test writes this file -->\n"

# No sample id, no group, no logging instruction. Two samples of the same task therefore
# produce byte-identical prompts, which is checked at build time and again by the tests.
PROMPT_HEAD = """\
You are answering one question about scripting on Chinese Windows. Work only inside this
directory: `skill/` is the only copy of the documentation you may use. Do not read
anything outside this directory, do not browse the network, and do not look for another
copy of this skill on the machine -- the answer only counts if it comes from this folder.

Read `skill/SKILL.md` first; it routes to the other pages. Load only the pages you decide
you need.

Write `answer.md` in this directory. Answer in Chinese, as you would to a colleague.
Give code that can be run as written -- no placeholders, no "rest is the same".

## Question

"""


class BuildError(Exception):
    """Invalid input or an incomplete snapshot. Nothing outside the staging dir is touched."""


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_plan() -> dict:
    plan = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))
    validate_plan(plan)
    return plan


def validate_plan(plan: dict) -> None:
    tasks = plan.get("tasks") or []
    if len(tasks) != EXPECTED_TASKS:
        raise BuildError("quality-ab/tasks.json must hold exactly %d tasks, found %d"
                         % (EXPECTED_TASKS, len(tasks)))

    task_ids = [task["task_id"] for task in tasks]
    if len(set(task_ids)) != len(task_ids):
        raise BuildError("duplicate task_id in quality-ab/tasks.json")

    coverage = plan.get("coverage") or {}
    if len(coverage) != EXPECTED_AREAS:
        raise BuildError("coverage must declare exactly %d areas, found %d"
                         % (EXPECTED_AREAS, len(coverage)))
    covered = [task_id for ids in coverage.values() for task_id in ids]
    if sorted(covered) != sorted(task_ids):
        raise BuildError("coverage does not match the task list exactly")

    if set(plan.get("groups") or {}) != {"A", "B"}:
        raise BuildError("groups must be exactly A and B")

    for task in tasks:
        for key in ("prompt", "required_checks", "forbidden_actions", "loads"):
            if not task.get(key):
                raise BuildError("%s has an empty %s" % (task["task_id"], key))


def snapshot_path(group: str, plan: dict) -> pathlib.Path:
    return (HERE / plan["groups"][group]["snapshot"]).resolve()


def verify_snapshot(group: str, root: pathlib.Path) -> None:
    """Fail unless the snapshot holds exactly the expected files and nothing else."""
    if not root.is_dir():
        raise BuildError("missing snapshot for group %s: %s" % (group, root))

    expected = set(SNAPSHOTS[group]["copy"]) | set(SNAPSHOTS[group]["disk_extra"])
    actual = {path.relative_to(root).as_posix()
              for path in root.rglob("*") if path.is_file()}

    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        raise BuildError("snapshot %s is missing: %s" % (group, ", ".join(missing)))
    if unexpected:
        raise BuildError("snapshot %s has unexpected files: %s"
                         % (group, ", ".join(unexpected)))
    if "CHANGELOG.md" in SNAPSHOTS[group]["copy"]:
        raise BuildError("CHANGELOG.md must not be part of a sample bundle")


def build_prompt(task: dict) -> str:
    return PROMPT_HEAD + task["prompt"] + "\n"


def shuffled_pairs(plan: dict, seed: int) -> list[tuple[str, str]]:
    pairs = [(task["task_id"], group) for task in plan["tasks"] for group in ("A", "B")]
    random.Random(seed).shuffle(pairs)
    return pairs


def run_log_text(sample_id: str, planned: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(RUN_LOG_COLUMNS)
    # Columns 2..14 stay empty for the executor; sample_id and the plan are pre-filled so
    # the row cannot be mis-joined and so nobody has to invent either value.
    writer.writerow([sample_id] + [""] * 13 + [";".join(planned)] + [""] * 4)
    return buffer.getvalue()


def _guard_target(out: pathlib.Path) -> None:
    if out == REPO_ROOT or REPO_ROOT in out.parents:
        raise BuildError("refusing to write inside the repository: %s\n"
                         "generated samples must never be committed" % out)
    if out.exists():
        if not out.is_dir():
            raise BuildError("target exists and is not a directory: %s" % out)
        if any(out.iterdir()):
            raise BuildError("target exists and is not empty: %s\n"
                             "choose a new directory; this tool never deletes samples" % out)


def build(plan: dict, out: pathlib.Path, seed: int) -> dict:
    """Build the bundle at ``out``. Returns the manifest. Raises BuildError on bad input."""
    out = pathlib.Path(out).expanduser().resolve()
    snaps = {group: snapshot_path(group, plan) for group in ("A", "B")}
    for group, root in snaps.items():
        verify_snapshot(group, root)

    tasks = {task["task_id"]: task for task in plan["tasks"]}
    for task in plan["tasks"]:
        for key, group in (("loads", "B"), ("loads_baseline", "A")):
            refs = task.get(key)
            if not refs:
                continue
            for ref in refs:
                if ref not in SNAPSHOTS[group]["copy"]:
                    raise BuildError("%s: %s is not in the group %s snapshot"
                                     % (task["task_id"], ref, group))

    _guard_target(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(tempfile.mkdtemp(prefix=".wsw-quality-ab-build-",
                                            dir=str(out.parent)))
    try:
        manifest = _build_into(plan, staging, snaps, seed)
        _verify_built(staging, manifest)
        if out.exists():
            out.rmdir()  # _guard_target proved it is empty; nothing is lost
        os.rename(staging, out)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _build_into(plan: dict, root: pathlib.Path, snaps: dict, seed: int) -> dict:
    pairs = shuffled_pairs(plan, seed)
    tasks = {task["task_id"]: task for task in plan["tasks"]}

    input_hashes = {
        group: {rel: sha256(snaps[group] / rel) for rel in SNAPSHOTS[group]["copy"]}
        for group in ("A", "B")
    }

    manifest = {
        "schema": 2,
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "seed": seed,
        "tasks": len(plan["tasks"]),
        "samples": len(pairs),
        "prompt_sha256": {},
        "snapshots": {
            group: {"path": plan["groups"][group]["snapshot"],
                    "copied": len(SNAPSHOTS[group]["copy"]),
                    "excluded": list(SNAPSHOTS[group]["disk_extra"]),
                    "files": input_hashes[group]}
            for group in ("A", "B")
        },
        "samples_meta": [],
    }
    mapping = {}

    for index, (task_id, group) in enumerate(pairs, start=1):
        sample_id = "S%02d" % index
        sample = root / sample_id
        sample.mkdir()
        skill = sample / "skill"
        skill.mkdir()

        copied = {}
        for rel in SNAPSHOTS[group]["copy"]:
            destination = skill / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(snaps[group] / rel, destination)
            digest = sha256(destination)
            if digest != input_hashes[group][rel]:
                raise BuildError("%s: copied %s does not match the snapshot"
                                 % (sample_id, rel))
            copied[rel] = digest

        task = tasks[task_id]
        prompt_file = sample / "PROMPT.md"
        prompt_file.write_text(build_prompt(task), encoding="utf-8", newline="\n")
        prompt_digest = sha256(prompt_file)
        known = manifest["prompt_sha256"].get(task_id)
        if known is not None and known != prompt_digest:
            raise BuildError("%s: the two groups did not get an identical prompt" % task_id)
        manifest["prompt_sha256"][task_id] = prompt_digest

        if group == "A":
            planned = task.get("loads_baseline") or task["loads"]
        else:
            planned = task["loads"]
        (sample / "run-log.csv").write_text(run_log_text(sample_id, planned),
                                           encoding="utf-8", newline="\n")
        (sample / "answer.md").write_text(ANSWER_PLACEHOLDER, encoding="utf-8", newline="\n")

        mapping[sample_id] = {"task_id": task_id, "group": group,
                              "snapshot": plan["groups"][group]["snapshot"]}
        manifest["samples_meta"].append({
            "sample_id": sample_id,
            "task_id": task_id,
            "files_copied": len(copied),
            "files": copied,
            "prompt_sha256": prompt_digest,
            "run_log_sha256": sha256(sample / "run-log.csv"),
        })

    write_json(root / "SEALED-mapping.json", mapping)
    write_json(root / "manifest.json", manifest)
    return manifest


def write_json(path: pathlib.Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def _verify_built(root: pathlib.Path, manifest: dict) -> None:
    """Re-read every written file and compare it with the manifest."""
    for sample in manifest["samples_meta"]:
        sample_dir = root / sample["sample_id"]
        for rel, digest in sample["files"].items():
            if sha256(sample_dir / "skill" / rel) != digest:
                raise BuildError("%s: %s changed after it was written"
                                 % (sample["sample_id"], rel))
        if sha256(sample_dir / "PROMPT.md") != sample["prompt_sha256"]:
            raise BuildError("%s: PROMPT.md changed after it was written" % sample["sample_id"])
        if sha256(sample_dir / "run-log.csv") != sample["run_log_sha256"]:
            raise BuildError("%s: run-log.csv changed after it was written"
                             % sample["sample_id"])

        expected = ({"skill/" + rel for rel in sample["files"]}
                    | {"PROMPT.md", "run-log.csv", "answer.md"})
        actual = {path.relative_to(sample_dir).as_posix()
                  for path in sample_dir.rglob("*") if path.is_file()}
        if actual != expected:
            raise BuildError("%s: unexpected file set: %s"
                             % (sample["sample_id"], ", ".join(sorted(actual - expected))))

    expected_root = {sample["sample_id"] for sample in manifest["samples_meta"]}
    expected_root |= {"SEALED-mapping.json", "manifest.json"}
    actual_root = {path.name for path in root.iterdir()}
    if actual_root != expected_root:
        raise BuildError("unexpected bundle layout: %s"
                         % ", ".join(sorted(actual_root ^ expected_root)))


def dry_run(plan: dict, seed: int | None) -> None:
    """Validate the inputs and print the sample order without the group."""
    for group in ("A", "B"):
        verify_snapshot(group, snapshot_path(group, plan))

    pairs = shuffled_pairs(plan, seed if seed is not None else secrets.randbits(63))
    for index, (task_id, _group) in enumerate(pairs, start=1):
        print("S%02d  task=%s" % (index, task_id))
    print("\n%d samples, %d tasks x 2 snapshots -- nothing written"
          % (len(pairs), len(plan["tasks"])))
    if seed is not None:
        print("seed=%d (explicit, reproducible)" % seed)
    else:
        print("seed is omitted on purpose: the formal seed is random and stays in the "
              "executor's manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=None,
                        help="target directory (default: a new folder under the system temp dir)")
    parser.add_argument("--seed", type=int, default=None,
                        help="explicit shuffle seed for reproducible runs; omit for a "
                             "secure random seed")
    parser.add_argument("--dry-run", action="store_true",
                        help="print task ids and sample numbers, write nothing")
    args = parser.parse_args()

    try:
        plan = load_plan()
        if args.dry_run:
            dry_run(plan, args.seed)
            return

        seed = args.seed if args.seed is not None else secrets.randbits(63)
        if args.out:
            out = pathlib.Path(args.out).expanduser().resolve()
        else:
            stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            out = pathlib.Path(tempfile.gettempdir()) / ("wsw-quality-ab-" + stamp)
        manifest = build(plan, out, seed)
    except BuildError as error:
        print("ERROR: %s" % error, file=sys.stderr)
        raise SystemExit(2)

    print("\n%d samples in %s" % (manifest["samples"], out))
    print("executor keeps: manifest.json (seed) and SEALED-mapping.json")
    print("scorer gets nothing from here -- run make_scoring_packet.py after the answers exist")


if __name__ == "__main__":
    main()
