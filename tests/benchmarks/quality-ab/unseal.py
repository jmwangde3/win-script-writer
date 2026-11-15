#!/usr/bin/env python3
"""Join the reviewer sheets, unblind the groups and write the quality A/B report.

This is the last step and the only one that reads ``SCORER-KEY.json``. It refuses to run
until every answer has a score in every dimension, so a partially scored packet cannot
turn into a result.

Usage::

    python tests/benchmarks/quality-ab/unseal.py \
        --key D:/qa-SCORER-KEY.json \
        --scores D:/qa-packet/scores-reviewer-1.csv \
        --scores D:/qa-packet/scores-reviewer-2.csv \
        --out D:/qa-results.md

Optional:

  * ``--meta meta.json`` -- model id, version, client, sampling parameters, environment,
    limitations and conclusion. Anything omitted is written as "not recorded", because a
    blank field is honest and a guessed one is not.
  * ``--run D:/qa-run`` -- the executor bundle, used for the reference/token evidence
    sections. Without it those sections say "not supplied".

Exit codes: 0 ok, 2 refused (unscored answer, unknown id, out-of-range score, output
already exists).
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import pathlib
import statistics
import sys

DIMENSIONS = [
    ("correctness", "Correctness", 30),
    ("encoding_correctness", "Encoding correctness", 25),
    ("host_compatibility", "Host compatibility", 20),
    ("safety", "Safety", 15),
    ("completeness", "Completeness", 10),
]

SCORE_COLUMNS = ["answer_id"] + [key for key, _label, _max in DIMENSIONS] + ["notes"]

META_FIELDS = [
    ("model", "Model id"),
    ("model_version", "Model version"),
    ("client", "Client"),
    ("client_version", "Client version"),
    ("started_at", "Run started"),
    ("finished_at", "Run finished"),
    ("temperature", "temperature"),
    ("top_p", "top_p"),
    ("max_output_tokens", "max output tokens"),
    ("sampling_seed", "sampling seed"),
    ("environment", "Environment"),
]


class UnsealError(Exception):
    """The scores or the key cannot produce an honest result."""


def _read_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise UnsealError("cannot read %s: %s" % (path, error))
    except ValueError as error:
        raise UnsealError("%s is not valid JSON: %s" % (path, error))


def read_scores(path: pathlib.Path) -> dict:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as error:
        raise UnsealError("cannot read %s: %s" % (path, error))

    required = {"answer_id"} | {key for key, _label, _max in DIMENSIONS}
    if not rows:
        raise UnsealError("%s has no score rows" % path)
    missing = sorted(required - set(rows[0]))
    if missing:
        raise UnsealError("%s is missing columns: %s" % (path, ", ".join(missing)))

    scores = {}
    for row in rows:
        answer_id = (row.get("answer_id") or "").strip()
        if not answer_id:
            raise UnsealError("%s has a row without answer_id" % path)
        if answer_id in scores:
            raise UnsealError("%s scores %s twice" % (path, answer_id))
        values = {}
        for key, label, maximum in DIMENSIONS:
            raw = (row.get(key) or "").strip()
            if not raw:
                raise UnsealError("%s: %s has no %s score" % (path, answer_id, label))
            try:
                value = int(raw)
            except ValueError:
                raise UnsealError("%s: %s has a non-integer %s score: %r"
                                  % (path, answer_id, label, raw))
            if not 0 <= value <= maximum:
                raise UnsealError("%s: %s scores %s=%d, outside 0..%d"
                                  % (path, answer_id, label, value, maximum))
            values[key] = value
        values["notes"] = (row.get("notes") or "").strip()
        scores[answer_id] = values
    return scores


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"mean": _mean(ordered), "median": statistics.median(ordered),
            "min": ordered[0], "max": ordered[-1], "n": len(ordered)}


def _read_run_logs(run: pathlib.Path, sample_ids: list[str]) -> dict:
    logs = {}
    for sample_id in sample_ids:
        path = run / sample_id / "run-log.csv"
        if not path.is_file():
            logs[sample_id] = {}
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        logs[sample_id] = rows[0] if rows else {}
    return logs


def unseal(key_path: pathlib.Path, score_paths: list[pathlib.Path], out: pathlib.Path,
           meta: dict | None = None, run: pathlib.Path | None = None) -> str:
    key = _read_json(key_path)
    mapping = key.get("mapping") or {}
    if not mapping:
        raise UnsealError("%s has no mapping" % key_path)

    answer_ids = sorted(mapping)
    reviewers = [read_scores(path) for path in score_paths]
    for path, scores in zip(score_paths, reviewers):
        if sorted(scores) != answer_ids:
            missing = sorted(set(answer_ids) - set(scores))
            extra = sorted(set(scores) - set(answer_ids))
            raise UnsealError("%s does not match the key (missing: %s; unknown: %s)"
                              % (path, ", ".join(missing) or "-", ", ".join(extra) or "-"))

    # Combined score: the mean across reviewers, per dimension. Totals are the sum of the
    # dimension means, so a two-reviewer total is not double the 100-point scale.
    combined = {}
    reviewer_totals = []
    for scores in reviewers:
        reviewer_totals.append({answer_id: sum(scores[answer_id][key]
                                               for key, _label, _max in DIMENSIONS)
                                for answer_id in answer_ids})
    for answer_id in answer_ids:
        combined[answer_id] = {}
        for dim, _label, _maximum in DIMENSIONS:
            combined[answer_id][dim] = _mean([scores[answer_id][dim]
                                              for scores in reviewers])
        combined[answer_id]["notes"] = " / ".join(
            dict.fromkeys(scores[answer_id]["notes"]
                          for scores in reviewers if scores[answer_id]["notes"]))
        combined[answer_id]["total"] = sum(combined[answer_id][dim]
                                           for dim, _label, _max in DIMENSIONS)

    groups = {"A": [], "B": []}
    for answer_id, entry in mapping.items():
        if entry.get("group") not in groups:
            raise UnsealError("%s has an unknown group %r" % (answer_id, entry.get("group")))
        groups[entry["group"]].append(answer_id)
    if not groups["A"] or not groups["B"]:
        raise UnsealError("one group has no scored answer")

    group_totals = {group: [combined[answer_id]["total"] for answer_id in ids]
                    for group, ids in groups.items()}
    group_stats = {group: _stats(values) for group, values in group_totals.items()}
    dimension_means = {
        group: {dim: _mean([combined[answer_id][dim] for answer_id in ids])
                for dim, _label, _max in DIMENSIONS}
        for group, ids in groups.items()
    }
    delta = {dim: dimension_means["B"][dim] - dimension_means["A"][dim]
             for dim, _label, _max in DIMENSIONS}
    delta["total"] = group_stats["B"]["mean"] - group_stats["A"]["mean"]

    tasks = {}
    for answer_id, entry in mapping.items():
        tasks.setdefault(entry["task_id"], {"A": [], "B": []})[entry["group"]].append(
            combined[answer_id]["total"])
    movers = []
    for task_id, by_group in tasks.items():
        if not by_group["A"] or not by_group["B"]:
            continue
        movers.append((task_id, _mean(by_group["A"]), _mean(by_group["B"]),
                       _mean(by_group["B"]) - _mean(by_group["A"])))
    movers.sort(key=lambda row: abs(row[3]), reverse=True)

    disagreements = []
    if len(reviewer_totals) > 1:
        for answer_id in answer_ids:
            totals = [totals[answer_id] for totals in reviewer_totals]
            if max(totals) - min(totals) > 10:
                disagreements.append((answer_id, totals))

    sample_ids = [mapping[answer_id].get("sample_id", "?") for answer_id in answer_ids]
    logs = _read_run_logs(run, sample_ids) if run else {}

    report = _render(mapping=mapping, answer_ids=answer_ids, combined=combined,
                     groups=groups, group_stats=group_stats,
                     dimension_means=dimension_means, delta=delta, movers=movers,
                     disagreements=disagreements, reviewers=reviewers,
                     meta=meta or {}, logs=logs, run_supplied=run is not None)

    out = pathlib.Path(out).expanduser().resolve()
    if out.exists():
        raise UnsealError("refusing to overwrite an existing report: %s" % out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8", newline="\n")
    return report


def _render(*, mapping, answer_ids, combined, groups, group_stats, dimension_means,
            delta, movers, disagreements, reviewers, meta, logs, run_supplied) -> str:
    a, b = group_stats["A"], group_stats["B"]
    lines = [
        "# Model quality A/B report",
        "",
        "Generated %s by `unseal.py` from %d reviewer file(s) and %d answers."
        % (_dt.datetime.now().isoformat(timespec="seconds"), len(reviewers), len(answer_ids)),
        "",
        "> This report exists only because every answer was scored before the key was",
        "> opened. If any field below says \"not recorded\", it was not observed -- it was",
        "> not estimated.",
        "",
        "## 1-4. Run identity",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for field, label in META_FIELDS:
        lines.append("| %s | %s |" % (label, meta.get(field, "not recorded")))

    lines += [
        "",
        "## 5. Tasks tested",
        "",
        "%d tasks, %d answers per group." % (len({entry["task_id"] for entry in mapping.values()}),
                                            len(groups["A"])),
        "",
        "| Task | Answers |",
        "| --- | ---: |",
    ]
    task_counts = {}
    for entry in mapping.values():
        task_counts[entry["task_id"]] = task_counts.get(entry["task_id"], 0) + 1
    for task_id in sorted(task_counts):
        lines.append("| `%s` | %d |" % (task_id, task_counts[task_id]))

    lines += [
        "",
        "## 6. Per-sample scores",
        "",
        "Combined score = mean of the reviewer scores per dimension; total = sum of the",
        "five dimension means, on the 100-point scale.",
        "",
        "| Answer | Task | Group | Correctness /30 | Encoding /25 | Host /20 | Safety /15 "
        "| Completeness /10 | Total |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for answer_id in answer_ids:
        entry = mapping[answer_id]
        scores = combined[answer_id]
        lines.append(
            "| %s | `%s` | %s | %s | %.1f |" % (
                answer_id, entry["task_id"], entry["group"],
                " | ".join("%.1f" % scores[dim] for dim, _label, _max in DIMENSIONS),
                scores["total"]))

    lines += [
        "",
        "## 7-8. Group totals (100-point scale)",
        "",
        "| Group | n | Mean | Median | Min | Max |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        "| A (v1.0.4 Chinese) | %d | %.2f | %.2f | %.2f | %.2f |"
        % (a["n"], a["mean"], a["median"], a["min"], a["max"]),
        "| B (v1.1.0 English) | %d | %.2f | %.2f | %.2f | %.2f |"
        % (b["n"], b["mean"], b["median"], b["min"], b["max"]),
        "",
        "## 9. Per-dimension means",
        "",
        "| Dimension | A | B | Delta (B - A) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for dim, label, maximum in DIMENSIONS:
        lines.append("| %s /%d | %.2f | %.2f | %+.2f |"
                     % (label, maximum, dimension_means["A"][dim],
                        dimension_means["B"][dim], delta[dim]))

    lines += [
        "",
        "## 10. Overall delta",
        "",
        "**B - A = %+.2f points** on the combined 100-point total." % delta["total"],
        "",
        "A negative delta in any row above is a finding. Do not average it into the",
        "headline; name the dimension and the samples that carried it.",
        "",
        "## 11. Samples that moved most",
        "",
        "| Task | A mean | B mean | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for task_id, mean_a, mean_b, task_delta in movers:
        lines.append("| `%s` | %.2f | %.2f | %+.2f |" % (task_id, mean_a, mean_b, task_delta))

    lines += [
        "",
        "## 12-14. Error cases",
        "",
        "The tool does not re-derive error cases from the answer text; the record is the",
        "reviewer notes. Every non-empty note is listed below, with the answer's group.",
        "",
        "| Answer | Task | Group | Reviewer notes |",
        "| --- | --- | --- | --- |",
    ]
    noted = 0
    for answer_id in answer_ids:
        note = combined[answer_id]["notes"].replace("|", "/").replace("\n", " ")
        if not note:
            continue
        noted += 1
        entry = mapping[answer_id]
        lines.append("| %s | `%s` | %s | %s |"
                     % (answer_id, entry["task_id"], entry["group"], note))
    if not noted:
        lines.append("| — | — | — | no reviewer note was recorded |")
    lines += [
        "",
        "## 15-17. Reference and token evidence",
        "",
    ]
    if not run_supplied:
        lines += [
            "Not supplied. Re-run with `--run <executor bundle>` to include the",
            "`planned_references` / `provided_references` / `opened_references` columns",
            "and whether token usage was observable.",
            "",
        ]
    else:
        lines += [
            "| Sample | Group | Planned | Provided | Opened | Load evidence | "
            "total_tokens |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for answer_id in answer_ids:
            entry = mapping[answer_id]
            log = logs.get(entry.get("sample_id", ""), {})
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                entry.get("sample_id", "?"), entry["group"],
                log.get("planned_references") or "—",
                log.get("provided_references") or "—",
                log.get("opened_references") or "—",
                log.get("load_evidence") or "not observable",
                log.get("total_tokens") or "not observable",
            ))
        observable = any(logs.get(entry.get("sample_id", ""), {}).get("total_tokens")
                         for entry in mapping.values())
        lines += [
            "",
            "Token usage was %s in this client. Reported values are API `usage` fields "
            "copied from the response; they are never estimated from characters."
            % ("observable" if observable else "**not observable**"),
            "",
            "`opened_references` is a record, not a self-report: `self-reported` and",
            "`not observable` are different from an observed file-access log.",
            "",
        ]

    lines += [
        "## 18. Limitations",
        "",
        meta.get("limitations", "not recorded"),
        "",
        "State at least: one sample per task is a screening run, not a statistical proof;",
        "a model version change mid-run invalidates the comparison; and a client without",
        "file-access logging cannot support the dynamic-routing claim.",
        "",
        "## 19. Conclusion",
        "",
        meta.get("conclusion", "not recorded"),
        "",
        "A conclusion is only valid if B did not regress on correctness, encoding",
        "correctness or safety. If it did, say which dimension and which sample.",
        "",
        "## Unblinding record",
        "",
        "| Answer | Sample | Task | Group |",
        "| --- | --- | --- | --- |",
    ]
    for answer_id in answer_ids:
        entry = mapping[answer_id]
        lines.append("| %s | %s | `%s` | %s |"
                     % (answer_id, entry.get("sample_id", "?"),
                        entry["task_id"], entry["group"]))
    lines.append("")

    if disagreements:
        lines += ["## Reviewer disagreement over 10 points", "",
                  "| Answer | Reviewer totals | Difference |",
                  "| --- | --- | ---: |"]
        for answer_id, totals in disagreements:
            lines.append("| %s | %s | %d |"
                         % (answer_id, " / ".join(str(total) for total in totals),
                            max(totals) - min(totals)))
        lines += ["", "Each row must carry a recorded reason before the result is quoted.",
                  ""]
    else:
        lines += ["## Reviewer disagreement over 10 points", "",
                  "None recorded.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", required=True, help="SCORER-KEY.json (executor only)")
    parser.add_argument("--scores", action="append", required=True,
                        help="a filled reviewer CSV; pass it once per reviewer")
    parser.add_argument("--out", required=True, help="markdown report to write")
    parser.add_argument("--meta", default=None, help="JSON with the run identity fields")
    parser.add_argument("--run", default=None, help="executor bundle, for the evidence table")
    args = parser.parse_args()

    meta = _read_json(pathlib.Path(args.meta)) if args.meta else {}
    try:
        unseal(pathlib.Path(args.key), [pathlib.Path(p) for p in args.scores],
               pathlib.Path(args.out), meta=meta,
               run=pathlib.Path(args.run) if args.run else None)
    except UnsealError as error:
        print("ERROR: %s" % error, file=sys.stderr)
        raise SystemExit(2)
    print("report written to %s" % args.out)


if __name__ == "__main__":
    main()
