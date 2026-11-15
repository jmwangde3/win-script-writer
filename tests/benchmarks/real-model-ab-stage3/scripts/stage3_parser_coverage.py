#!/usr/bin/env python3
"""Per-block parser coverage for the ten stage-3 answers.

Reuses the follow-up coverage module, but reads the bundle's fresh answers instead of
the historical raw directory.

Usage::

    python tests/benchmarks/real-model-ab-stage3/scripts/stage3_parser_coverage.py --root <root>
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "real-model-ab-followup" / "scripts"))

import parser_coverage  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    bundle = root / "bundle"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    answers = []
    for sample in manifest["samples"]:
        path = bundle / sample["sample_id"] / "answer.md"
        text = path.read_text(encoding="utf-8", errors="replace")
        answers.append(parser_coverage.coverage_for_answer(
            text, sample["task"], sample["group"],
            "bundle/%s/answer.md" % sample["sample_id"]))

    summary = {
        "answers": len(answers),
        "parser": "Parser.ParseFile, hosts 5.1 and 7",
        "executes_target": False,
        "status": ("FAIL" if any(item["status"] == "FAIL" for item in answers)
                   else "REVIEW_REQUIRED"
                   if any(item["status"] == "REVIEW_REQUIRED" for item in answers)
                   else "PASS"),
        "counts": {
            "pass": sum(1 for item in answers if item["status"] == "PASS"),
            "fail": sum(1 for item in answers if item["status"] == "FAIL"),
            "review_required": sum(1 for item in answers
                                   if item["status"] == "REVIEW_REQUIRED"),
            "not_applicable": sum(1 for item in answers if item["status"] == "N/A"),
        },
        "unclassified_blocks": sum(item["blocks_unclassified"] for item in answers),
        "unchecked_powershell_blocks": sum(item["unchecked_powershell_blocks"]
                                           for item in answers),
        "unclosed_fences": sum(1 for item in answers if item["unclosed_fence"]),
        "root_causes": sorted({cause for item in answers for cause in item["root_causes"]}),
    }
    payload = {"generated": "2026-11-15", "answers": answers, "summary": summary}
    target = HERE / "parser-coverage.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    for item in answers:
        print("%s/%s status=%s ps=%d unclassified=%d roots=%s"
              % (item["group"], item["task"], item["status"],
                 item["blocks_powershell"], item["blocks_unclassified"],
                 ",".join(item["root_causes"]) or "-"))
    print("wrote", target)


if __name__ == "__main__":
    main()
