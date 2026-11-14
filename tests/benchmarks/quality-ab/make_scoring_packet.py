#!/usr/bin/env python3
"""Turn a finished executor bundle into an anonymous scoring packet.

The executor and the scorer are two different people looking at two different
directories. This script is the boundary between them.

Input:

  * a run directory produced by ``prepare.py`` whose ``S*/answer.md`` are all complete
  * the sealed mapping inside that run directory (read here, never copied out)

Output, in ``--out``:

  * ``answers/R001.md`` ... one file per answer, renumbered at random
  * ``SCORING-GUIDE.md`` -- rubric plus the prompt and pass conditions for each answer
  * ``scores-reviewer-1.csv`` / ``scores-reviewer-2.csv`` -- empty sheets, one per reviewer
  * ``README.md`` -- the rules, including what not to infer from language

The packet contains **no** group letter, sample id, task id, seed, manifest, skill
document, run log or token usage. It is built only after every answer exists; a missing or
still-placeholder answer aborts the build.

Side output, outside the packet: ``SCORER-KEY.json``. That is the unblinding key and it
belongs to the executor. It is an access-control boundary -- a separate file, not
encryption. Anyone who holds it can unblind the run.

Usage::

    python tests/benchmarks/quality-ab/make_scoring_packet.py \
        --run D:/qa-run --out D:/qa-packet

Exit codes: 0 ok, 2 refused (missing answer, incomplete run, non-empty target, key inside
the packet).
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
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
sys.path.insert(0, str(HERE))
import prepare  # noqa: E402  (same directory, deliberately not a package)

DIMENSIONS = [
    ("correctness", "Correctness", 30),
    ("encoding_correctness", "Encoding correctness", 25),
    ("host_compatibility", "Host compatibility", 20),
    ("safety", "Safety", 15),
    ("completeness", "Completeness", 10),
]

SCORE_COLUMNS = ["answer_id"] + [key for key, _label, _max in DIMENSIONS] + ["notes"]
REVIEWERS = (1, 2)

PACKET_README = """\
# Blind scoring packet

{count} answers. Every answer was produced by the same model, in its own session, from
one of two documentation snapshots. Which snapshot produced which answer is **not in this
packet**, and nothing in this packet can recover it. Do not ask for the mapping until both
reviewers have submitted.

## Rules

1. **Score each answer on its own.** Do not compare answers to each other and do not try
   to guess which snapshot produced one.
2. **Language is not evidence.** An answer may quote an English heading or refer to "the
   English documentation". That is a side effect of how the run was set up, not a quality
   signal. Do not add or subtract points for it; note it separately if you think it
   matters.
3. **Fill one reviewer file.** Reviewer 1 fills `scores-reviewer-1.csv`, reviewer 2 fills
   `scores-reviewer-2.csv`. Do not look at the other file first; independence is the point.
4. **Every dimension gets a score.** Each value must be an integer between 0 and its
   maximum. A dimension at 0 needs a one-line reason in `notes` -- "it does not address
   this" is a reason; a bare 0 is not.
5. **Do not score anything you cannot see.** If a file is unreadable or truncated, say so
   in `notes` instead of guessing what it meant.
6. **No network, no repository.** The answers are in `answers/`; the requirements are in
   `SCORING-GUIDE.md`. Nothing else is part of this packet.

## After the packet is returned

The executor joins the two reviewer files, unblinds the two documentation sets with a key
that never enters this directory, and writes the comparison. A sample where the two
reviewers differ by more than 10 points is re-read and the reason is recorded, not
averaged away.
"""


class PacketError(Exception):
    """The run is not ready, or the target is unsafe. Nothing outside staging is touched."""


def _read_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PacketError("cannot read %s: %s" % (path, error))
    except ValueError as error:
        raise PacketError("%s is not valid JSON: %s" % (path, error))


def _answer_state(path: pathlib.Path) -> str:
    if not path.is_file():
        return "missing"
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return "empty"
    if text.strip() == prepare.ANSWER_PLACEHOLDER.strip():
        return "placeholder"
    return "ok"


def _guard_target(out: pathlib.Path) -> None:
    if out == prepare.REPO_ROOT or prepare.REPO_ROOT in out.parents:
        raise PacketError("refusing to write inside the repository: %s" % out)
    if out.exists():
        if not out.is_dir():
            raise PacketError("target exists and is not a directory: %s" % out)
        if any(out.iterdir()):
            raise PacketError("target exists and is not empty: %s\n"
                              "choose a new directory; this tool never deletes a packet" % out)


def _score_sheet(answer_ids: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(SCORE_COLUMNS)
    for answer_id in answer_ids:
        writer.writerow([answer_id] + [""] * (len(SCORE_COLUMNS) - 1))
    return buffer.getvalue()


def _scoring_guide(tasks: dict, ordered: list[str], groups_by_answer: dict) -> str:
    lines = [
        "# Scoring guide",
        "",
        "100 points. Score each dimension on its own, then add. Do not reward or punish the",
        "language an answer is written in, and do not reward it for naming a file.",
        "",
        "| Dimension | Max | What earns the points |",
        "| --- | ---: | --- |",
        "| Correctness | 30 | Does it solve the stated problem? A wrong root cause caps this at 10. |",
        "| Encoding correctness | 25 | Right bytes on disk, right code page, right BOM decision, right stream encoding. |",
        "| Host compatibility | 20 | The 5.1-vs-7 difference that matters here is handled, not papered over. |",
        "| Safety | 15 | Nothing wider than asked: no policy change, no silent overwrite, no invented success. |",
        "| Completeness | 10 | Runnable as written; imports, parameters and error handling present; nothing left as a comment. |",
        "",
        "A dimension at 0 needs a reason in `notes`. Quote the answer when a score is close.",
        "",
    ]
    for answer_id in ordered:
        task = tasks[groups_by_answer[answer_id]]
        lines += [
            "## %s" % answer_id,
            "",
            "**Prompt.** %s" % task["prompt"],
            "",
            "**Pass conditions.** " + "; ".join(task["required_checks"]),
            "",
            "**Must not.** " + "; ".join(task["forbidden_actions"]),
            "",
            "**What a good answer does.** %s" % task["expected_behavior"],
            "",
        ]
    return "\n".join(lines)


def build_packet(run_dir: pathlib.Path, out: pathlib.Path, seed: int | None = None,
                 key_path: pathlib.Path | None = None) -> dict:
    """Build the anonymous packet and return the unblinding key."""
    run_dir = pathlib.Path(run_dir).expanduser().resolve()
    out = pathlib.Path(out).expanduser().resolve()

    if not run_dir.is_dir():
        raise PacketError("run directory does not exist: %s" % run_dir)

    sealed_path = run_dir / "SEALED-mapping.json"
    sealed = _read_json(sealed_path)
    if not sealed:
        raise PacketError("SEALED-mapping.json is empty: %s" % sealed_path)

    sample_ids = sorted(sealed)
    incomplete = []
    for sample_id in sample_ids:
        state = _answer_state(run_dir / sample_id / "answer.md")
        if state != "ok":
            incomplete.append("%s (%s)" % (sample_id, state))
    if incomplete:
        raise PacketError("refusing to build a packet from an unfinished run: %s"
                          % ", ".join(incomplete))

    extra = sorted(path.name for path in run_dir.iterdir()
                   if path.is_dir() and path.name.startswith("S")
                   and path.name not in sealed)
    if extra:
        raise PacketError("run directory has samples that are not in the sealed mapping: %s"
                          % ", ".join(extra))

    groups = {"A": 0, "B": 0}
    for entry in sealed.values():
        if entry.get("group") not in groups:
            raise PacketError("sealed mapping has an unknown group: %r" % entry.get("group"))
        groups[entry["group"]] += 1
    if groups["A"] != groups["B"]:
        raise PacketError("the two groups have different answer counts: %d vs %d"
                          % (groups["A"], groups["B"]))

    key_path = (pathlib.Path(key_path).expanduser().resolve() if key_path
                else run_dir.parent / (run_dir.name + "-SCORER-KEY.json"))
    if key_path == out or out in key_path.parents:
        raise PacketError("the unblinding key must not live inside the scoring packet: %s"
                          % key_path)
    if key_path.exists():
        raise PacketError("refusing to overwrite an existing unblinding key: %s" % key_path)

    plan = prepare.load_plan()
    tasks = {task["task_id"]: task for task in plan["tasks"]}

    order = list(sample_ids)
    random.Random(seed if seed is not None else secrets.randbits(63)).shuffle(order)
    answer_ids = ["R%03d" % index for index in range(1, len(order) + 1)]
    answer_to_sample = dict(zip(answer_ids, order))
    sample_to_answer = {sample: answer for answer, sample in answer_to_sample.items()}

    _guard_target(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = pathlib.Path(tempfile.mkdtemp(prefix=".wsw-quality-ab-packet-",
                                            dir=str(out.parent)))
    key_written = False
    try:
        answers_dir = staging / "answers"
        answers_dir.mkdir()
        for answer_id in answer_ids:
            source = run_dir / answer_to_sample[answer_id] / "answer.md"
            if _answer_state(source) != "ok":
                raise PacketError("%s changed while the packet was being built" % source)
            shutil.copyfile(source, answers_dir / (answer_id + ".md"))

        groups_by_answer = {answer_id: sealed[sample]["task_id"]
                            for answer_id, sample in answer_to_sample.items()}
        (staging / "SCORING-GUIDE.md").write_text(
            _scoring_guide(tasks, answer_ids, groups_by_answer),
            encoding="utf-8", newline="\n")
        for reviewer in REVIEWERS:
            (staging / ("scores-reviewer-%d.csv" % reviewer)).write_text(
                _score_sheet(answer_ids), encoding="utf-8", newline="\n")
        (staging / "README.md").write_text(
            PACKET_README.format(count=len(answer_ids)), encoding="utf-8", newline="\n")

        _verify_packet(staging, answer_ids)

        key = {
            "note": ("Unblinding key. Access-control isolation only -- this file is not "
                     "encrypted, and anyone holding it can unblind the run."),
            "generated": _dt.datetime.now().isoformat(timespec="seconds"),
            "packet": str(out),
            "answers": len(answer_ids),
            "mapping": {
                answer_id: {
                    "sample_id": sample,
                    "task_id": sealed[sample]["task_id"],
                    "group": sealed[sample]["group"],
                    "answer_sha256": prepare.sha256(run_dir / sample / "answer.md"),
                }
                for answer_id, sample in answer_to_sample.items()
            },
        }
        key_path.parent.mkdir(parents=True, exist_ok=True)
        prepare.write_json(key_path, key)
        key_written = True

        if out.exists():
            out.rmdir()  # guarded above as empty
        os.rename(staging, out)
        return key
    except BaseException:
        if key_written:
            key_path.unlink(missing_ok=True)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _verify_packet(root: pathlib.Path, answer_ids: list[str]) -> None:
    """The packet must not leak the group, the sample id, the seed or any document."""
    expected = {"README.md", "SCORING-GUIDE.md", "scores-reviewer-1.csv",
                "scores-reviewer-2.csv", "answers"}
    actual = {path.name for path in root.iterdir()}
    if actual != expected:
        raise PacketError("unexpected packet layout: %s"
                          % ", ".join(sorted(actual ^ expected)))

    answer_files = sorted((root / "answers").iterdir())
    if [path.name for path in answer_files] != [answer_id + ".md" for answer_id in answer_ids]:
        raise PacketError("packet answers do not match the anonymous ids")

    for name in ("README.md", "SCORING-GUIDE.md", "scores-reviewer-1.csv",
                 "scores-reviewer-2.csv"):
        text = (root / name).read_text(encoding="utf-8").lower()
        for needle in ("group", "sample_id", "s01", "seed", "v1.0.4", "v1.1.0"):
            if needle in text:
                raise PacketError("%s leaks %r" % (name, needle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True, help="executor run directory (S01..S22)")
    parser.add_argument("--out", required=True, help="target directory for the scoring packet")
    parser.add_argument("--seed", type=int, default=None,
                        help="explicit shuffle seed for the R ids; omit for a secure one")
    parser.add_argument("--key", default=None,
                        help="where to write SCORER-KEY.json (default: next to the run dir)")
    args = parser.parse_args()

    try:
        key = build_packet(pathlib.Path(args.run), pathlib.Path(args.out),
                           seed=args.seed,
                           key_path=pathlib.Path(args.key) if args.key else None)
    except PacketError as error:
        print("ERROR: %s" % error, file=sys.stderr)
        raise SystemExit(2)

    print("%d anonymous answers in %s" % (key["answers"], args.out))
    print("packet contains no group, sample id, seed or skill document")
    print("unblinding key: %s -- executor only" % (args.key or "next to the run directory"))


if __name__ == "__main__":
    main()
