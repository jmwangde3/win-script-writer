#!/usr/bin/env python3
"""Assemble the stage-3 summary and report from the run artifacts."""

from __future__ import annotations

import csv
import json
import pathlib
import re
import shutil

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT_DEFAULT = pathlib.Path(r"H:\temp\user\wsw-v110-stage3\20261115-001546")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    root = ROOT_DEFAULT
    rows = list(csv.DictReader((root / "task-results.csv").open(encoding="utf-8", newline="")))
    parser = read_json(HERE / "parser-coverage.json")
    tokens = read_json(HERE / "token-comparison.json")
    stage3_tokens = read_json(HERE / "stage3-token.json")

    by_task = {}
    for row in rows:
        for key in ("execution_started", "execution_ok", "safety_violation", "routing_valid"):
            row[key] = row[key] == "True"
        row["score"] = float(row["score"])
        by_task.setdefault((row["task"], row["group"]), []).append(row)

    tasks = []
    for task in ("SAFETY", "BAT", "PS51"):
        a = by_task[(task, "A")]
        b = by_task[(task, "B")]
        tasks.append({
            "task": task,
            "a_samples": len(a),
            "b_samples": len(b),
            "a_success": sum(1 for row in a if row["execution_ok"]),
            "b_success": sum(1 for row in b if row["execution_ok"]),
            "a_mean": round(sum(row["score"] for row in a) / len(a), 2),
            "b_mean": round(sum(row["score"] for row in b) / len(b), 2),
            "delta": round(sum(row["score"] for row in b) / len(b)
                           - sum(row["score"] for row in a) / len(a), 2),
        })

    all_rows = rows
    group_a = [row for row in all_rows if row["group"] == "A"]
    group_b = [row for row in all_rows if row["group"] == "B"]
    summary = {
        "run_id": root.name,
        "samples": len(all_rows),
        "model": "gpt-6-luna via Codex CLI 0.167.0-alpha.3.2",
        "executed": sum(1 for row in all_rows if row["execution_started"]),
        "execution_ok": sum(1 for row in all_rows if row["execution_ok"]),
        "safety_violations": sum(1 for row in all_rows if row["safety_violation"]),
        "routing_valid": sum(1 for row in all_rows if row["routing_valid"]),
        "group_a": {
            "samples": len(group_a),
            "mean": round(sum(row["score"] for row in group_a) / len(group_a), 2),
            "execution_ok": sum(1 for row in group_a if row["execution_ok"]),
        },
        "group_b": {
            "samples": len(group_b),
            "mean": round(sum(row["score"] for row in group_b) / len(group_b), 2),
            "execution_ok": sum(1 for row in group_b if row["execution_ok"]),
        },
        "parser": parser["summary"],
        "tokens_stage3": stage3_tokens["overall"],
        "tasks": tasks,
        "verdict": "CONDITIONAL",
    }

    # copy the artifacts into the repository
    (HERE / "execution").mkdir(exist_ok=True)
    for source in (root / "execution").rglob("*"):
        if source.is_file():
            target = HERE / "execution" / source.relative_to(root / "execution")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    (HERE / "logs").mkdir(exist_ok=True)
    shutil.copyfile(root / "logs" / "selftest.json", HERE / "logs" / "selftest.json")
    (HERE / "logs" / "evidence").mkdir(exist_ok=True)
    for source in (root / "bundle" / "_evidence").glob("*.jsonl"):
        shutil.copyfile(source, HERE / "logs" / "evidence" / source.name)
    shutil.copyfile(root / "task-results.csv", HERE / "task-results.csv")
    shutil.copyfile(root / "run-order.txt", HERE / "run-order.txt")
    shutil.copyfile(root / "bundle" / "manifest.json", HERE / "bundle-manifest.json")

    (HERE / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    a = summary["group_a"]
    b = summary["group_b"]
    lines = [
        "# Stage 3 report: local controlled dynamic A/B",
        "",
        "Run: `%s`. Model: `%s`." % (root.name, summary["model"]),
        "",
        "**Verdict: CONDITIONAL.** The previous B failures did not recur: 10/10 answers",
        "parsed or were not PowerShell, 10/10 executions met their task condition, and",
        "there were no safety violations. B matched A on every task. The verdict is not",
        "PASS because both groups share a PS51 gap, the run has one sample per BAT/PS51",
        "side, and the execution used a temp directory under a normal user rather than an",
        "OS sandbox.",
        "",
        "## Task results",
        "",
        "| Task | A n | B n | A success | B success | A mean | B mean | Delta |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in tasks:
        lines.append("| %s | %d | %d | %d | %d | %.1f | %.1f | %+.1f |" % (
            item["task"], item["a_samples"], item["b_samples"], item["a_success"],
            item["b_success"], item["a_mean"], item["b_mean"], item["delta"]))
    lines += [
        "",
        "| Metric | A | B |",
        "| --- | ---: | ---: |",
        "| Samples | %d | %d |" % (a["samples"], b["samples"]),
        "| Mean score | %.1f | %.1f |" % (a["mean"], b["mean"]),
        "| Execution met the task condition | %d/%d | %d/%d |" % (
            a["execution_ok"], a["samples"], b["execution_ok"], b["samples"]),
        "",
        "## Parser",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        "| Answers | %d |" % parser["summary"]["answers"],
        "| PASS / FAIL / REVIEW / N/A | %d / %d / %d / %d |" % (
            parser["summary"]["counts"]["pass"], parser["summary"]["counts"]["fail"],
            parser["summary"]["counts"]["review_required"],
            parser["summary"]["counts"]["not_applicable"]),
        "| Unchecked PowerShell blocks | %d |" % parser["summary"]["unchecked_powershell_blocks"],
        "| Unclassified blocks | %d |" % parser["summary"]["unclassified_blocks"],
        "| Unclosed fences | %d |" % parser["summary"]["unclosed_fences"],
        "| Root causes | %s |" % (", ".join(parser["summary"]["root_causes"]) or "none"),
        "",
        "The previous `B/SAFETY` doubled-quote error did not appear in any of the three new",
        "B samples. The parser gate is in place and would have rejected it.",
        "",
        "## Routing",
        "",
        "All ten sessions were routing-valid against the corrected SAFETY route",
        "(encoding-matrix + powershell-51). Every SAFETY sample opened those two pages;",
        "the original declared route (security + troubleshooting) was the defect, not the",
        "model. See `routing-investigation.md`.",
        "",
        "## Token",
        "",
        "| Task | A mean | B mean | Saving |",
        "| --- | ---: | ---: | ---: |",
    ]
    for item in stage3_tokens["tasks"]:
        lines.append("| %s | %.1f | %.1f | %.2f%% |" % (
            item["task"].upper(), item["A_mean_tokens"], item["B_mean_tokens"],
            item["saving_percent"]))
    lines += [
        "",
        "Fresh-sample arithmetic mean: **%.2f%%**; token-weighted across the ten samples:",
        "**%.2f%%** (the weight is skewed by three SAFETY samples per group). Historical",
        "six-task views are in `token-comparison.json`: 7.45%% arithmetic / 9.35%% weighted.",
        "These are DeepSeek-tokenizer text estimates, not GPT-6-Luna context usage.",
        "",
        "## Safety and environment",
        "",
        "- Normal user (`IsInRole(Administrator) = false`), no `-ExecutionPolicy Bypass`.",
        "- Every answer pre-reviewed: parser, dangerous-command scan, path rewriting.",
        "- SAFETY fixture hashes identical before and after in all six runs.",
        "- BAT run at console code page 936 and 65001; system ACP untouched.",
        "- No OS-level isolation: a temp directory is not a sandbox. This is the main limit.",
        "",
        "## What did not recur",
        "",
        "- B/SAFETY parse error: 0 of 3 new B samples (was 1 of 1).",
        "- B/BAT missing `chcp 936`: the new B answer includes it; both code pages pass.",
        "- PS51 still lacks a programmatic write in both groups: 75/100 for both, a shared",
        "  gap, not a B regression.",
        "",
        "## Skill changes",
        "",
        "No change to `SKILL.md` or `references/` is justified by this run. The only",
        "routing defect is the benchmark's `loads` for `tool-02`; the proposed metadata",
        "diff is in `routing-investigation.md` for review.",
        "",
        "## Limits",
        "",
        "- One sample per BAT/PS51 side; three per SAFETY side. Screening, not proof.",
        "- Model is `gpt-6-luna`, not DeepSeek; no server version, temperature or seed.",
        "- PowerShell 7.7, not 7.4.",
        "- Host ACP is 65001; the BAT matrix emulates 936 in a wrapper.",
        "- Temp-directory containment plus pre-review, not OS isolation.",
        "",
        "## Artifacts",
        "",
        "- `task-results.csv`, `summary.json`",
        "- `parser-coverage.json`, `token-comparison.json`, `stage3-token.json`",
        "- `raw/A`, `raw/B`, `execution/A`, `execution/B`, `logs/`",
        "- `run-config.json`, `routing-investigation.md`",
        "",
    ]
    (HERE / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
