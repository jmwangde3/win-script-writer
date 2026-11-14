#!/usr/bin/env python3
"""Build the run bundle for the v1.0.4 vs v1.1.0 model quality A/B.

What this does:

  * reads ``tasks.json`` next to this file (10 tasks, chosen from ../tasks.json)
  * for every task and both documentation snapshots, copies the *documentation only*
    into an isolated directory
  * shuffles the 20 (task, group) pairs into blind sample ids S01..S20
  * writes one prompt file per sample, a run log with the fields to record, and a
    scoring sheet that never names the group

What this deliberately does **not** do:

  * it never calls a model, a CLI or an agent -- no answer is produced here
  * it never scores anything -- the scoring sheet ships with empty cells
  * it never guesses token usage -- those columns are filled from the API response,
    or left empty

Usage::

    python tests/benchmarks/quality-ab/prepare.py                     # build into %TEMP%
    python tests/benchmarks/quality-ab/prepare.py --out D:/qa-run     # explicit target
    python tests/benchmarks/quality-ab/prepare.py --dry-run           # print, write nothing

Exit codes: 0 ok, 2 bad input (missing task / missing snapshot).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import random
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
BENCH = HERE.parent

DOC_FILES = ["SKILL.md", "README.md"]
DEFAULT_SEED = 20261114


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_plan() -> dict:
    plan = json.loads((HERE / "tasks.json").read_text(encoding="utf-8"))
    if len(plan["tasks"]) != 10:
        sys.exit("quality-ab/tasks.json must hold exactly 10 tasks")
    return plan


def snapshot_files(snapshot: pathlib.Path) -> list[pathlib.Path]:
    files = [snapshot / name for name in DOC_FILES if (snapshot / name).is_file()]
    refs = sorted((snapshot / "references").glob("*.md"))
    if not files or not refs:
        sys.exit("snapshot is incomplete: %s" % snapshot)
    return files + refs


PROMPT_TEMPLATE = """\
# Sample {sample_id}

You are answering one question about scripting on Chinese Windows. Work only from the
documentation in `./skill/` in this directory. Do not read `../` and do not use any other
copy of this skill that may exist on the machine -- the run is only valid if the
documentation you read is the one in this folder.

Read `skill/SKILL.md` first; it routes to the other pages. Load only the pages you decide
you need, and write down which ones you loaded in the log line at the end.

Write `answer.md` in this directory. Answer in Chinese, as you would to a colleague.
Give code that can be run as written -- no placeholders, no "rest is the same".

Do not read `../SEALED-mapping.json`.

## Question

{prompt}

## When you are done

Append exactly one line to `run-log.csv` (header already there), filling every column you
can observe and leaving the rest empty -- an empty cell is honest, a guessed number is
not:

    sample_id,model,session_id,started_at,reference_files_loaded,prompt_tokens,completion_tokens,total_tokens,cached_tokens,notes

`reference_files_loaded` takes semicolon-separated paths relative to `skill/`.
Token columns come from the API response; if the client does not expose them, leave them
blank and say so in `notes`.
"""


def build(plan: dict, out: pathlib.Path, seed: int, dry_run: bool) -> None:
    pairs = [(t["task_id"], group) for t in plan["tasks"] for group in ("A", "B")]
    random.Random(seed).shuffle(pairs)

    snaps = {g: (HERE / plan["groups"][g]["snapshot"]).resolve() for g in ("A", "B")}
    for group, snap in snaps.items():
        if not snap.is_dir():
            sys.exit("missing snapshot for group %s: %s" % (group, snap))

    manifest = {
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "seed": seed,
        "tasks": len(plan["tasks"]),
        "samples": len(pairs),
        "snapshots": {g: {"path": str(p), "files": {
            f.relative_to(p).as_posix(): sha256(f) for f in snapshot_files(p)
        }} for g, p in snaps.items()},
        "samples_meta": [],
    }
    mapping = {}

    if dry_run:
        for i, (task_id, group) in enumerate(pairs, start=1):
            print("S%02d  task=%s  group=%s" % (i, task_id, group))
        print("\n20 samples, %d tasks x 2 snapshots, seed %d -- nothing written"
              % (len(plan["tasks"]), seed))
        return

    out.mkdir(parents=True, exist_ok=True)
    for i, (task_id, group) in enumerate(pairs, start=1):
        sid = "S%02d" % i
        sample = out / sid
        sample.mkdir(exist_ok=True)
        skill = sample / "skill"
        if skill.exists():
            shutil.rmtree(skill)
        skill.mkdir()
        for src in snapshot_files(snaps[group]):
            rel = src.relative_to(snaps[group])
            dst = skill / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        task = next(t for t in plan["tasks"] if t["task_id"] == task_id)
        (sample / "PROMPT.md").write_text(
            PROMPT_TEMPLATE.format(sample_id=sid, prompt=task["prompt"]),
            encoding="utf-8", newline="\n")
        (sample / "run-log.csv").write_text(
            "sample_id,model,session_id,started_at,reference_files_loaded,"
            "prompt_tokens,completion_tokens,total_tokens,cached_tokens,notes\n",
            encoding="utf-8", newline="\n")
        (sample / "answer.md").write_text(
            "<!-- written by the model under test; empty on purpose -->\n",
            encoding="utf-8", newline="\n")

        mapping[sid] = {"task_id": task_id, "group": group,
                        "snapshot": str(snaps[group])}
        manifest["samples_meta"].append({"sample_id": sid, "task_id": task_id,
                                         "files_copied": len(snapshot_files(snaps[group]))})
        print("built %s" % sid)

    (out / "SEALED-mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    (out / "scoring-sheet.md").write_text(
        scoring_sheet(plan, pairs), encoding="utf-8", newline="\n")

    print("\n%d samples in %s" % (len(pairs), out))
    print("scorer gets: scoring-sheet.md + each S*/answer.md")
    print("scorer never gets: SEALED-mapping.json")


def scoring_sheet(plan: dict, pairs: list[tuple[str, str]]) -> str:
    tasks = {t["task_id"]: t for t in plan["tasks"]}
    lines = [
        "# Blind scoring sheet",
        "",
        "Twenty answers, two documentation snapshots, order shuffled with a fixed seed. The",
        "sample id does not tell you which snapshot produced the answer. Do not open",
        "`SEALED-mapping.json` until every row below is filled.",
        "",
        "## Rubric (100 points)",
        "",
        "| Dimension | Max | What earns the points |",
        "| --- | ---: | --- |",
        "| Correctness | 30 | Does it solve the stated problem? Wrong root cause caps this at 10. |",
        "| Encoding correctness | 25 | Right bytes on disk, right code page, right BOM decision, right stream encoding. |",
        "| Host compatibility | 20 | 5.1 vs 7 differences that matter here are handled, not papered over. |",
        "| Safety | 15 | Nothing wider than asked: no policy change, no silent overwrite, no invented success. |",
        "| Completeness | 10 | Runnable as written, imports and parameters present, nothing left as a comment. |",
        "",
        "Score each dimension on its own, then add. A dimension at 0 must carry a one-line",
        "reason -- \"it does not address this\" is a reason; a bare 0 is not.",
        "",
        "`CHANGELOG.md` is not part of any sample. The two groups differ in documentation",
        "language and in how the pages are cut, so an answer may refer to \"the English",
        "doc\" or quote a heading. **That is not evidence of quality either way** -- score",
        "the technical content only, and note the meta-commentary separately if it matters.",
        "",
        "## Sheet",
        "",
    ]
    for i, (task_id, _group) in enumerate(pairs, start=1):
        sid = "S%02d" % i
        task = tasks[task_id]
        lines += [
            "### %s" % sid,
            "",
            "**Prompt.** %s" % task["prompt"],
            "",
            "**Pass conditions.** " + "; ".join(task["required_checks"]),
            "",
            "**Must not.** " + "; ".join(task["forbidden_actions"]),
            "",
            "| Correctness /30 | Encoding /25 | Host /20 | Safety /15 | Completeness /10 | Total |",
            "| --- | --- | --- | --- | --- | --- |",
            "|  |  |  |  |  |  |",
            "",
            "Notes: ",
            "",
        ]
    lines += [
        "## After scoring",
        "",
        "1. Open `SEALED-mapping.json` and join the scores onto the group column.",
        "2. Report per group: mean, median, min, and the per-dimension means.",
        "3. Report the delta and its direction. A negative delta on any dimension is a",
        "   finding, not a rounding error -- write it down.",
        "4. Record the model name and version, the client, and whether token usage was",
        "   observable. If it was not, say so; do not estimate it from character counts.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=None,
                    help="target directory (default: a new folder under the system temp dir)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help="shuffle seed for the blind sample ids (default %d)" % DEFAULT_SEED)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args()

    plan = load_plan()
    if args.out:
        out = pathlib.Path(args.out).expanduser().resolve()
    else:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        out = pathlib.Path(tempfile.gettempdir()) / ("wsw-quality-ab-" + stamp)
    build(plan, out, args.seed, args.dry_run)


if __name__ == "__main__":
    main()
