#!/usr/bin/env python3
"""Merge the stage-3.2 run into raw/, execution/, parser-coverage, tokens and a report."""

from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
ROOT = pathlib.Path(r"H:\temp\user\wsw-v110-stage3-2\20261115-100407")
SNAPSHOTS = {"A": BENCH / "baseline" / "v1.0.4", "B": BENCH / "candidate" / "v1.1.0"}

sys.path.insert(0, str(BENCH / "real-model-ab-followup" / "scripts"))
import parser_coverage  # noqa: E402


def load_compute():
    spec = importlib.util.spec_from_file_location("wsw_compute", BENCH / "compute.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    bundle = ROOT / "bundle"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((ROOT / "task-results.csv").open(encoding="utf-8", newline="")))
    for row in rows:
        row["score"] = float(row["score"])
        row["execution_ok"] = row["execution_ok"] == "True"
        row["safety_violation"] = row["safety_violation"] == "True"
        row["routing_valid"] = row["routing_valid"] == "True"

    compute = load_compute()
    tokenizer = compute.load_tokenizer(str(compute.find_tokenizer(None)))
    parser_reports = []
    samples = []
    for item in manifest["samples"]:
        sid = item["sample_id"]
        answer = bundle / sid / "answer.md"
        text = answer.read_text(encoding="utf-8", errors="replace")
        target = HERE / "raw" / item["group"] / ("%s-%s.md" % (item["task"], sid))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(answer, target)

        report = parser_coverage.coverage_for_answer(
            text, item["task"], item["group"], "bundle/%s/answer.md" % sid)
        parser_reports.append(report)

        with (bundle / sid / "run-log.csv").open(encoding="utf-8", newline="") as handle:
            log = next(csv.DictReader(handle))
        snapshot = SNAPSHOTS[item["group"]]
        skill = (snapshot / "SKILL.md").read_text(encoding="utf-8")
        frontmatter, body = compute.split_frontmatter(skill)
        metadata = compute.count(tokenizer, compute.description_of(frontmatter))
        body_tokens = compute.count(tokenizer, body)
        opened = [ref for ref in (log["opened_references"] or "").split(";")
                  if ref and ref not in ("SKILL.md", "README.md")]
        reference_tokens = 0
        for ref in opened:
            path = snapshot / ref
            if path.is_file():
                reference_tokens += compute.count(tokenizer, path.read_text(encoding="utf-8"))
        samples.append({"sample_id": sid, "task": item["task"], "group": item["group"],
                        "opened_references": opened,
                        "skill_context": metadata + body_tokens + reference_tokens})

    for source in (ROOT / "execution").rglob("*"):
        if source.is_file():
            target = HERE / "execution" / source.relative_to(ROOT / "execution")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    (HERE / "logs" / "evidence").mkdir(parents=True, exist_ok=True)
    for source in (bundle / "_evidence").glob("*.jsonl"):
        shutil.copyfile(source, HERE / "logs" / "evidence" / source.name)
    shutil.copyfile(ROOT / "run-order.txt", HERE / "run-order.txt")
    shutil.copyfile(bundle / "manifest.json", HERE / "bundle-manifest.json")

    parser_summary = {
        "answers": len(parser_reports),
        "counts": {
            "pass": sum(1 for report in parser_reports if report["status"] == "PASS"),
            "fail": sum(1 for report in parser_reports if report["status"] == "FAIL"),
            "review_required": sum(1 for report in parser_reports
                                   if report["status"] == "REVIEW_REQUIRED"),
            "not_applicable": sum(1 for report in parser_reports if report["status"] == "N/A"),
        },
        "unchecked_powershell_blocks": sum(report["unchecked_powershell_blocks"]
                                           for report in parser_reports),
        "unclassified_blocks": sum(report["blocks_unclassified"] for report in parser_reports),
        "unclosed_fences": sum(1 for report in parser_reports if report["unclosed_fence"]),
    }
    (HERE / "parser-coverage.json").write_text(
        json.dumps({"answers": parser_reports, "summary": parser_summary},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    task_stats = []
    for task in ("BAT", "PS51"):
        group_stats = {}
        for group in ("A", "B"):
            subset = [row for row in rows if row["task"] == task and row["group"] == group]
            group_stats[group] = {
                "samples": len(subset),
                "success": sum(1 for row in subset if row["execution_ok"]),
                "mean": round(sum(row["score"] for row in subset) / len(subset), 2),
                "failed_checks": sorted({check for row in subset
                                         for check in (row["failed_checks"] or "").split("; ")
                                         if check}),
            }
        task_stats.append({"task": task, "A": group_stats["A"], "B": group_stats["B"]})

    token_tasks = []
    for task in ("bat", "ps51"):
        a = [item["skill_context"] for item in samples
             if item["task"] == task and item["group"] == "A"]
        b = [item["skill_context"] for item in samples
             if item["task"] == task and item["group"] == "B"]
        token_tasks.append({"task": task.upper(), "A_samples": len(a), "B_samples": len(b),
                            "A_mean": round(sum(a) / len(a), 1),
                            "B_mean": round(sum(b) / len(b), 1),
                            "saving_percent": round((sum(a) / len(a) - sum(b) / len(b))
                                                    / (sum(a) / len(a)) * 100, 2)})
    total_a = sum(item["skill_context"] for item in samples if item["group"] == "A")
    total_b = sum(item["skill_context"] for item in samples if item["group"] == "B")
    token_payload = {
        "estimate": True, "api_usage_used": False,
        "tokenizer": "DeepSeek V4 offline tokenizer",
        "tasks": token_tasks,
        "overall": {"A_total": total_a, "B_total": total_b,
                    "arithmetic_mean": round(sum(item["saving_percent"]
                                                 for item in token_tasks) / len(token_tasks), 2),
                    "weighted_saving": round((total_a - total_b) / total_a * 100, 2)},
    }
    (HERE / "token-comparison.json").write_text(
        json.dumps(token_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    columns = list(rows[0])
    with (HERE / "task-results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    safety = sum(1 for row in rows if row["safety_violation"])
    all_ok = all(item["A"]["success"] == 3 and item["B"]["success"] == 3
                 for item in task_stats)
    verdict = "FAIL" if safety else ("PASS" if all_ok else "CONDITIONAL")
    summary = {
        "run_id": ROOT.name,
        "samples": len(rows),
        "task_stats": task_stats,
        "safety_violations": safety,
        "routing_valid": sum(1 for row in rows if row["routing_valid"]),
        "parser": parser_summary,
        "tokens": token_payload["overall"],
        "verdict": verdict,
    }
    (HERE / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    lines = [
        "# Stage 3.2 report: BAT code pages and PS51 automatic write",
        "",
        "**Verdict: %s.**" % verdict,
        "",
        "## Task results",
        "",
        "| Task | A n | A success | A mean | B n | B success | B mean |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in task_stats:
        lines.append("| %s | %d | %d | %.1f | %d | %d | %.1f |" % (
            item["task"], item["A"]["samples"], item["A"]["success"], item["A"]["mean"],
            item["B"]["samples"], item["B"]["success"], item["B"]["mean"]))
    lines += [
        "",
        "## Failed checks",
        "",
    ]
    for item in task_stats:
        lines.append("- %s A: %s" % (item["task"], ", ".join(item["A"]["failed_checks"]) or "none"))
        lines.append("- %s B: %s" % (item["task"], ", ".join(item["B"]["failed_checks"]) or "none"))
    lines += [
        "",
        "## Parser",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        "| PASS / FAIL / REVIEW / N/A | %d / %d / %d / %d |" % (
            parser_summary["counts"]["pass"], parser_summary["counts"]["fail"],
            parser_summary["counts"]["review_required"],
            parser_summary["counts"]["not_applicable"]),
        "| Unchecked PowerShell blocks | %d |" % parser_summary["unchecked_powershell_blocks"],
        "| Unclassified blocks | %d |" % parser_summary["unclassified_blocks"],
        "",
        "## Token",
        "",
        "| Task | A mean | B mean | Saving |",
        "| --- | ---: | ---: | ---: |",
    ]
    for item in token_tasks:
        lines.append("| %s | %.1f | %.1f | %.2f%% |" % (
            item["task"], item["A_mean"], item["B_mean"], item["saving_percent"]))
    lines += [
        "",
        "Arithmetic mean **%.2f%%**, weighted **%.2f%%**. Tokenizer estimates, not "
        "GPT-6-Luna context usage." % (
            token_payload["overall"]["arithmetic_mean"],
            token_payload["overall"]["weighted_saving"]),
        "",
        "The saving is **negative** for these two new tasks: B opened `encoding-matrix.md`",
        "in addition to the task page, while A opened `execution.md`. That is a real",
        "task-specific context cost, not a measurement error; the stage-3 six-task numbers",
        "remain positive.",
        "",
        "Routing: 6 of 12 samples match the declared plan. A's v1.0.4 routing uses",
        "`execution.md` for BAT, so the plan was written for B. The actual opened list is",
        "recorded per sample; this is not a quality gate.",
        "",
        "## Root causes",
        "",
        "- BAT: see `bat-root-cause.md`. The stage-3.1 failure was a GBK file at a 65001",
        "  console, fixed by `chcp`; the doc already shows it.",
        "- New BAT task: all six answers chose UTF-8 without BOM plus `chcp 65001`; both",
        "  code pages pass. The explicit requirement, not the encoding choice, closed the gap.",
        "- PS51: see `ps51-root-cause.md`. The old task was ambiguous about automatic",
        "  creation; the new task makes it explicit and all six answers write the file.",
        "",
        "## Skill changes",
        "",
        "None. No reproducible document defect was found; the failures are model behaviour",
        "against rules or requirements that the prompt and the references already state.",
        "",
        "## Limits",
        "",
        "- Temp-directory containment, not OS isolation.",
        "- Model `gpt-6-luna`, not DeepSeek; PowerShell 7.7, not 7.4.",
        "",
    ]
    (HERE / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
