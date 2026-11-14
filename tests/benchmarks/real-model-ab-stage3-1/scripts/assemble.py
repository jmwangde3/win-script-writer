#!/usr/bin/env python3
"""Merge the stage-3.1 new samples with the stage-3 BAT/PS51 samples and report.

Inputs:
  * stage-3 root: task-results.csv + stage3-token.json (existing BAT/PS51/SAFETY)
  * stage-3.1 root: task-results.csv + bundle (new BAT/PS51)

Outputs in this directory: task-results.csv, parser-coverage.json, token-comparison.json,
summary.json, report.md, raw/, execution/, logs/.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import pathlib
import shutil

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
STAGE3 = BENCH / "real-model-ab-stage3"
STAGE3_ROOT = pathlib.Path(r"H:\temp\user\wsw-v110-stage3\20261115-001546")
STAGE31_ROOT = pathlib.Path(r"H:\temp\user\wsw-v110-stage3-1\20261115-010429")
SNAPSHOTS = {"A": BENCH / "baseline" / "v1.0.4", "B": BENCH / "candidate" / "v1.1.0"}

sys_path = BENCH / "real-model-ab-followup" / "scripts"
import sys
sys.path.insert(0, str(sys_path))
import parser_coverage  # noqa: E402


def load_compute():
    spec = importlib.util.spec_from_file_location("wsw_compute", BENCH / "compute.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["score"] = float(row["score"])
    return rows


def context_for(sample, log, compute, tokenizer):
    snapshot = SNAPSHOTS[sample["group"]]
    skill = (snapshot / "SKILL.md").read_text(encoding="utf-8")
    frontmatter, body = compute.split_frontmatter(skill)
    metadata = compute.count(tokenizer, compute.description_of(frontmatter))
    body_tokens = compute.count(tokenizer, body)
    opened = [item for item in (log["opened_references"] or "").split(";")
              if item and item not in ("SKILL.md", "README.md")]
    references = 0
    for item in opened:
        path = snapshot / item
        if path.is_file():
            references += compute.count(tokenizer, path.read_text(encoding="utf-8"))
    return metadata + body_tokens + references


def main():
    old_rows = read_rows(STAGE3 / "task-results.csv")
    new_rows = read_rows(STAGE31_ROOT / "task-results.csv")
    old_keep = [row for row in old_rows if row["task_key"] in ("bat", "ps51")]
    merged = old_keep + new_rows

    # raw answers for the new samples
    manifest = json.loads((STAGE31_ROOT / "bundle" / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["samples"]:
        target = HERE / "raw" / item["group"] / ("%s-%s.md" % (item["task"], item["sample_id"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STAGE31_ROOT / "bundle" / item["sample_id"] / "answer.md", target)

    # execution evidence and logs
    for source in (STAGE31_ROOT / "execution").rglob("*"):
        if source.is_file():
            target = HERE / "execution" / source.relative_to(STAGE31_ROOT / "execution")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    (HERE / "logs" / "evidence").mkdir(parents=True, exist_ok=True)
    for source in (STAGE31_ROOT / "bundle" / "_evidence").glob("*.jsonl"):
        shutil.copyfile(source, HERE / "logs" / "evidence" / source.name)
    shutil.copyfile(STAGE31_ROOT / "run-order.txt", HERE / "run-order.txt")
    shutil.copyfile(STAGE31_ROOT / "bundle" / "manifest.json", HERE / "bundle-manifest.json")

    # parser coverage for the new answers
    parser_reports = []
    for item in manifest["samples"]:
        text = (STAGE31_ROOT / "bundle" / item["sample_id"] / "answer.md").read_text(
            encoding="utf-8", errors="replace")
        parser_reports.append(parser_coverage.coverage_for_answer(
            text, item["task"], item["group"], "bundle/%s/answer.md" % item["sample_id"]))
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
        "status": ("FAIL" if any(report["status"] == "FAIL" for report in parser_reports)
                   else "REVIEW_REQUIRED"
                   if any(report["status"] == "REVIEW_REQUIRED" for report in parser_reports)
                   else "PASS"),
    }
    (HERE / "parser-coverage.json").write_text(
        json.dumps({"answers": parser_reports, "summary": parser_summary},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    # token: new samples computed here, old samples from stage3-token.json
    compute = load_compute()
    tokenizer = compute.load_tokenizer(str(compute.find_tokenizer(None)))
    old_token = json.loads((STAGE3 / "stage3-token.json").read_text(encoding="utf-8"))
    token_samples = [item for item in old_token["samples"] if item["task"] in ("ps51", "bat")]
    for item in manifest["samples"]:
        with (STAGE31_ROOT / "bundle" / item["sample_id"] / "run-log.csv").open(
                encoding="utf-8", newline="") as handle:
            log = next(csv.DictReader(handle))
        token_samples.append({
            "sample_id": item["sample_id"],
            "task": item["task"],
            "group": item["group"],
            "opened_references": [ref for ref in (log["opened_references"] or "").split(";")
                                  if ref and ref not in ("SKILL.md", "README.md")],
            "skill_context": context_for(item, log, compute, tokenizer),
        })

    tasks = []
    for task in ("ps51", "bat"):
        a = [item["skill_context"] for item in token_samples
             if item["task"] == task and item["group"] == "A"]
        b = [item["skill_context"] for item in token_samples
             if item["task"] == task and item["group"] == "B"]
        tasks.append({"task": task, "A_samples": len(a), "B_samples": len(b),
                      "A_mean": round(sum(a) / len(a), 1),
                      "B_mean": round(sum(b) / len(b), 1),
                      "saving_percent": round((sum(a) / len(a) - sum(b) / len(b))
                                              / (sum(a) / len(a)) * 100, 2)})
    safety = next(item for item in old_token["tasks"] if item["task"] == "safety")
    tasks.append({"task": "safety", "A_samples": safety["A_samples"],
                  "B_samples": safety["B_samples"], "A_mean": safety["A_mean_tokens"],
                  "B_mean": safety["B_mean_tokens"],
                  "saving_percent": safety["saving_percent"]})
    total_a = sum(item["skill_context"] for item in token_samples if item["group"] == "A") \
        + sum(item["skill_context"] for item in old_token["samples"]
              if item["task"] == "safety" and item["group"] == "A")
    total_b = sum(item["skill_context"] for item in token_samples if item["group"] == "B") \
        + sum(item["skill_context"] for item in old_token["samples"]
              if item["task"] == "safety" and item["group"] == "B")
    token_payload = {
        "estimate": True,
        "api_usage_used": False,
        "tokenizer": "DeepSeek V4 offline tokenizer",
        "tasks": tasks,
        "overall": {
            "A_total": total_a,
            "B_total": total_b,
            "arithmetic_mean": round(sum(item["saving_percent"] for item in tasks) / len(tasks), 2),
            "weighted_saving": round((total_a - total_b) / total_a * 100, 2),
        },
    }
    (HERE / "token-comparison.json").write_text(
        json.dumps(token_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    # merged task results
    columns = list(merged[0].keys())
    with (HERE / "task-results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(merged)

    by_task = {}
    for row in merged:
        by_task.setdefault(row["task_key"], {"A": [], "B": []})[row["group"]].append(row)
    task_stats = []
    for task in ("safety", "bat", "ps51"):
        if task == "safety":
            safety_rows = [row for row in old_rows if row["task_key"] == "safety"]
            a = [row for row in safety_rows if row["group"] == "A"]
            b = [row for row in safety_rows if row["group"] == "B"]
        else:
            a, b = by_task[task]["A"], by_task[task]["B"]
        task_stats.append({
            "task": task,
            "a_samples": len(a), "b_samples": len(b),
            "a_success": sum(1 for row in a if row["execution_ok"] == "True"),
            "b_success": sum(1 for row in b if row["execution_ok"] == "True"),
            "a_mean": round(sum(row["score"] for row in a) / len(a), 2),
            "b_mean": round(sum(row["score"] for row in b) / len(b), 2),
        })

    all_a = [row for row in merged if row["group"] == "A"]
    all_b = [row for row in merged if row["group"] == "B"]
    verdict = "PASS"
    if any(row["safety_violation"] == "True" for row in merged):
        verdict = "FAIL"
    elif any(item["b_mean"] < item["a_mean"] for item in task_stats):
        verdict = "CONDITIONAL"
    elif any(item["a_mean"] < 100 or item["b_mean"] < 100 for item in task_stats):
        verdict = "CONDITIONAL"
    summary = {
        "run_id": STAGE31_ROOT.name,
        "samples": len(merged),
        "task_stats": task_stats,
        "group_a": {"samples": len(all_a),
                    "mean": round(sum(row["score"] for row in all_a) / len(all_a), 2)},
        "group_b": {"samples": len(all_b),
                    "mean": round(sum(row["score"] for row in all_b) / len(all_b), 2)},
        "safety_violations": sum(1 for row in merged if row["safety_violation"] == "True"),
        "parser": parser_summary,
        "tokens": token_payload["overall"],
        "verdict": verdict,
        "verdict_reason": (
            "B is lower on BAT (one sample omits chcp 936 and fails at code page 65001) "
            "and on PS51 (A has one programmatic write, B none). There is no safety "
            "violation. With three samples per side this is a real but non-safety "
            "regression, so CONDITIONAL, not PASS; a repeat is needed before release."),
    }
    (HERE / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    lines = [
        "# Stage 3.1 report: benchmark closeout and PS51",
        "",
        "**Verdict: %s.**" % verdict,
        "",
        "B is lower on BAT and PS51; there is no safety violation. Three samples per side",
        "is still a screening, so this is CONDITIONAL, not PASS. The BAT gap is the one to",
        "watch: it reproduces the stage-3 observation in one of three new B answers.",
        "",
        "## Task results",
        "",
        "| Task | A n | B n | A success | B success | A mean | B mean |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in task_stats:
        lines.append("| %s | %d | %d | %d | %d | %.1f | %.1f |" % (
            item["task"].upper(), item["a_samples"], item["b_samples"],
            item["a_success"], item["b_success"], item["a_mean"], item["b_mean"]))
    lines += [
        "",
        "## Parser on the eight new samples",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        "| PASS / FAIL / REVIEW / N/A | %d / %d / %d / %d |" % (
            parser_summary["counts"]["pass"], parser_summary["counts"]["fail"],
            parser_summary["counts"]["review_required"],
            parser_summary["counts"]["not_applicable"]),
        "| Unchecked PowerShell blocks | %d |" % parser_summary["unchecked_powershell_blocks"],
        "| Unclassified blocks | %d |" % parser_summary["unclassified_blocks"],
        "| Unclosed fences | %d |" % parser_summary["unclosed_fences"],
        "",
        "## Token",
        "",
        "| Task | A mean | B mean | Saving |",
        "| --- | ---: | ---: | ---: |",
    ]
    for item in tasks:
        lines.append("| %s | %.1f | %.1f | %.2f%% |" % (
            item["task"].upper(), item["A_mean"], item["B_mean"], item["saving_percent"]))
    lines += [
        "",
        "Arithmetic mean: **%.2f%%**; weighted: **%.2f%%**. These are tokenizer estimates, "
        "not GPT-6-Luna context usage." % (
            token_payload["overall"]["arithmetic_mean"],
            token_payload["overall"]["weighted_saving"]),
        "",
        "## Findings",
        "",
        "- **BAT:** A is 3/3 at both code pages. B is 2/3: one answer omits `chcp 936`, so",
        "  it passes at 936 and fails at 65001. This repeats the stage-3 single observation",
        "  and is now a 1-of-3 rate, not a one-off.",
        "- **PS51:** A provides a programmatic `WriteAllText` in 1 of 3 samples (score 100);",
        "  B provides none (75 each). All six scripts run and produce the expected Chinese",
        "  output; the difference is only the programmatic-write check.",
        "- **SAFETY:** unchanged from stage 3, 3/3 for both groups, no safety violation.",
        "",
        "## PS51",
        "",
        "`references/powershell-51.md` already shows the `WriteAllText` + `UTF8Encoding`",
        "pattern, and `SKILL.md` rule 1 states the BOM requirement. The models still chose",
        "a manual save dialog in 5 of 6 samples. This is model behaviour, not a missing",
        "document step, so the Skill is unchanged. The independent write test",
        "(`ps51-write-test.json`) proves the method works with a Chinese path on 5.1 and",
        "7.7. A dedicated task with explicit automatic-write wording is the recommended",
        "next step.",
        "",
        "## Routing",
        "",
        "`tool-02` now declares `encoding-matrix.md` + `powershell-51.md`; the metadata test",
        "and `routing-fix.json` record the change. No Skill change.",
        "",
        "## Limits",
        "",
        "- Temp-directory containment, not OS isolation.",
        "- Model `gpt-6-luna`, not DeepSeek; PowerShell 7.7, not 7.4.",
        "- BAT/PS51 now 3 samples per side; SAFETY remains the stage-3 3+3.",
        "",
    ]
    (HERE / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
