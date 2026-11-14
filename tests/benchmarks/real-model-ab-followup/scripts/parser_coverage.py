#!/usr/bin/env python3
"""Check every PowerShell block in an answer, not just the longest one.

The first follow-up parsed one block per answer. That is enough to catch a broken
SAFETY script, but it cannot claim "the PowerShell in this answer parses": a second
block may be broken, a fence may be unclosed, or a block may never have been checked.

This module records, per answer:

  * every fenced block with its position in the markdown
  * which blocks are PowerShell (by language tag, or by content when the tag is missing)
  * a SHA-256 of the original answer and of each extracted block
  * the parser result on 5.1 and 7 for every PowerShell block
  * a classification of the diagnostics: independent, cascade, extraction, environment

``status`` is PASS only when every PowerShell block parsed on both hosts, no fence was
left open and no block was skipped. Anything else is FAIL or N/A (an answer with no
PowerShell at all).

Nothing here executes the extracted code; ``ps_parse`` uses Parser.ParseFile only.

Usage::

    python tests/benchmarks/real-model-ab-followup/scripts/parser_coverage.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parents[1]
BENCH = HERE.parent
ORIGINAL = BENCH / "real-model-ab"
RAW = ORIGINAL / "raw"
SCRIPTS = ORIGINAL / "scripts"

sys.path.insert(0, str(SCRIPTS))
import ps_parse  # noqa: E402

PS_LANGS = {"powershell", "ps1", "ps", "pwsh"}
NON_PS_LANGS = {"bat", "cmd", "python", "py", "bash", "sh", "json", "text", "plain",
                "markdown", "md", "yaml", "yml", "xml", "csharp", "cs", "html"}
PS_HINTS = re.compile(
    r"(?mi)^\s*(#Requires|\$[A-Za-z_][\w:]*\s*=|Write-(Host|Output|Error)|"
    r"(Get|Set|New|Remove|Test|Start|Stop|Add|Import|Export|Invoke|Select|Where|"
    r"Join|Split|ForEach)-[A-Z]\w+|ForEach-Object|foreach\s*\(|catch\s*\{|switch\s*\(|"
    r"while\s*\(|try\s*\{|if\s*\(|param\s*\(|function\s+\w+)")
OTHER_HINTS = re.compile(
    r"(?mi)^\s*(@echo\s+off|import\s+[\w.]+|from\s+[\w.]+\s+import|def\s+\w+|"
    r"class\s+\w+|#include|<!doctype|<html|[\[{])")
INLINE = re.compile(r"`([^`\n]{3,180})`")
INLINE_COMMAND = re.compile(
    r"(?i)^\s*(Get|Set|New|Remove|Test|Start|Stop|Write|Add|Import|Export|Invoke|"
    r"Select|Where|Join|Split|ForEach|powershell|pwsh|cmd|python|py|git)\b[^`]*$")

_CACHE: dict[tuple[str, str], dict] = {}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_blocks(text: str) -> tuple[list[dict], bool]:
    """Return (blocks, unclosed_fence). Positions are 1-based markdown lines."""
    lines = text.splitlines()
    blocks = []
    in_block = False
    start = 0
    language = ""
    body: list[str] = []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not in_block and stripped.startswith("```"):
            in_block = True
            start = number
            language = stripped[3:].strip().split()[0].lower() if stripped[3:].strip() else ""
            body = []
        elif in_block and stripped == "```":
            blocks.append({
                "index": len(blocks),
                "start_line": start,
                "end_line": number,
                "language": language,
                "body": "\n".join(body) + ("\n" if body else ""),
                "implicit": False,
            })
            in_block = False
        elif in_block:
            body.append(line)
    return blocks, in_block


def classify_block(language: str, body: str) -> tuple[str, str]:
    """Return (kind, reason) where kind is POWERSHELL, OTHER or UNCLASSIFIED."""
    if language in PS_LANGS:
        return "POWERSHELL", "tag"
    if language in NON_PS_LANGS:
        return "OTHER", "tag"
    if PS_HINTS.search(body):
        return "POWERSHELL", "content"
    if OTHER_HINTS.search(body):
        return "OTHER", "content"
    return "UNCLASSIFIED", "content" if language in ("", "inline") else "tag"


def is_powershell(language: str, body: str) -> tuple[bool, str]:
    kind, reason = classify_block(language, body)
    return kind == "POWERSHELL", reason


def extract_inline(text: str) -> list[dict]:
    """Inline command spans outside fenced blocks, e.g. `Get-ChildItem -Recurse`."""
    spans = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in INLINE.finditer(line):
            body = match.group(1)
            if not INLINE_COMMAND.match(body):
                continue
            if not PS_HINTS.search(body):
                continue
            spans.append({
                "index": len(spans),
                "start_line": number,
                "end_line": number,
                "language": "inline",
                "body": body + "\n",
                "implicit": False,
                "inline": True,
            })
    return spans


def classify(errors: list[dict], source_text: str = "") -> dict:
    """Separate independent diagnostics from cascades.

    A broken quote or brace does not produce one error; it produces a tail of
    ``MissingEndCurlyBrace`` / ``MissingCatchOrFinally`` diagnostics that are symptoms of
    the first mistake. Counting those as separate defects is how a single typo looks like
    six problems. The first diagnostic is the primary; structural follow-ups, nearby
    diagnostics and every diagnostic in a block that contains ``''`` are cascades.
    """
    doubled_quote = "''" in source_text
    structural = ("MissingEnd", "Incomplete", "MissingCatch", "MissingClose",
                  "MissingExpression", "UnexpectedToken")
    classified = []
    for index, error in enumerate(errors):
        item = dict(error)
        item["index"] = index
        item["class"] = "independent"
        item["caused_by"] = None
        error_id = item.get("error_id") or ""
        if index > 0:
            primary = classified[0]
            same_line = abs((item.get("line") or 0) - (primary.get("line") or 0)) <= 1
            overlap = (item.get("text") and primary.get("text")
                       and (item["text"] in primary["text"]
                            or primary["text"] in item["text"]))
            if doubled_quote or same_line or overlap or error_id.startswith(structural):
                item["class"] = "cascade"
                item["caused_by"] = 0
        if doubled_quote and "''" in (item.get("text") or ""):
            item["root_cause"] = "doubled-single-quote"
        elif item["class"] == "cascade":
            item["root_cause"] = classified[0].get("root_cause") or "cascade"
        elif error_id.startswith(structural):
            item["root_cause"] = error_id or "structural"
        else:
            item["root_cause"] = error_id or "parser-error"
        classified.append(item)
    root_causes = sorted({item["root_cause"] for item in classified})
    return {
        "diagnostics": len(classified),
        "independent": sum(1 for item in classified if item["class"] == "independent"),
        "cascade": sum(1 for item in classified if item["class"] == "cascade"),
        "root_causes": root_causes,
        "root_cause_count": len(root_causes),
        "errors": classified,
    }


def parse_block(body: str) -> dict:
    """Parse one block on both hosts. The code is written, never run."""
    digest = sha256_text(body)
    result = {}
    for host in ("5.1", "7"):
        key = (digest, host)
        if key not in _CACHE:
            with tempfile.TemporaryDirectory(prefix="wsw-block-") as directory:
                path = pathlib.Path(directory) / "block.ps1"
                path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
                _CACHE[key] = ps_parse.parse_file(path, host)
        result[host] = _CACHE[key]
    return result


def coverage_for_answer(text: str, task: str, group: str, source: str) -> dict:
    blocks, unclosed = extract_blocks(text)
    inline = extract_inline(text)
    blocks = blocks + inline
    for index, block in enumerate(blocks):
        block["index"] = index
    implicit = False
    if not blocks and PS_HINTS.search(text):
        blocks = [{"index": 0, "start_line": 1, "end_line": len(text.splitlines()),
                   "language": "implicit", "body": text, "implicit": True}]
        implicit = True

    records = []
    kinds = {"POWERSHELL": 0, "OTHER": 0, "UNCLASSIFIED": 0}
    unclassified = []
    unchecked = 0
    for block in blocks:
        kind, detected_by = classify_block(block["language"], block["body"])
        kinds[kind] += 1
        record = {
            "index": block["index"],
            "start_line": block["start_line"],
            "end_line": block["end_line"],
            "language": block["language"],
            "implicit": block.get("implicit", False),
            "inline": block.get("inline", False),
            "detected_by": detected_by,
            "kind": kind,
            "powershell": kind == "POWERSHELL",
            "body_sha256": sha256_text(block["body"]),
            "body_bytes": len(block["body"].encode("utf-8")),
        }
        if kind == "UNCLASSIFIED":
            unclassified.append({
                "index": block["index"],
                "start_line": block["start_line"],
                "language": block["language"],
                "body_sha256": record["body_sha256"],
                "reason": "not recognisable as PowerShell or a known other language",
            })
            record["parsed"] = None
        elif kind == "POWERSHELL":
            reports = parse_block(block["body"])
            parsed = {}
            for host, report in reports.items():
                parsed[host] = {
                    "ok": report.get("ok"),
                    "host": report.get("host"),
                    "harness_error": report.get("harness_error"),
                    "classification": classify(report.get("errors") or [], block["body"]),
                }
                if report.get("ok") is None:
                    unchecked += 1
            record["parse"] = parsed
            record["parsed"] = all(item["ok"] is True for item in parsed.values())
        else:
            record["parsed"] = None
        records.append(record)

    if unclosed:
        unchecked += 1
    if unclassified:
        status = "REVIEW_REQUIRED"
    elif kinds["POWERSHELL"] == 0:
        status = "N/A"
    elif unchecked or unclosed or not all(record["parsed"] for record in records
                                          if record["powershell"]):
        status = "FAIL"
    else:
        status = "PASS"

    diagnostics = sum(
        record["parse"][host]["classification"]["diagnostics"]
        for record in records if record["powershell"]
        for host in ("5.1", "7"))
    root_causes = sorted({
        cause
        for record in records if record["powershell"]
        for host in ("5.1", "7")
        for cause in record["parse"][host]["classification"]["root_causes"]})

    return {
        "task": task,
        "group": group,
        "source": source,
        "answer_sha256": sha256_text(text),
        "answer_bytes": len(text.encode("utf-8")),
        "blocks_total": len(records),
        "blocks_inline": sum(1 for record in records if record["inline"]),
        "blocks_powershell": kinds["POWERSHELL"],
        "blocks_other": kinds["OTHER"],
        "blocks_unclassified": kinds["UNCLASSIFIED"],
        "blocks_parsed": sum(1 for record in records if record["powershell"]),
        "unchecked_powershell_blocks": unchecked,
        "unclosed_fence": unclosed,
        "implicit_script": implicit,
        "status": status,
        "unclassified": unclassified,
        "diagnostics": diagnostics,
        "root_causes": root_causes,
        "blocks": records,
    }


def execution_allowed(report: dict) -> bool:
    """A PowerShell answer may only run when every block parsed and none was skipped."""
    return (report["status"] in ("PASS", "N/A")
            and report["unchecked_powershell_blocks"] == 0
            and not report["unclosed_fence"]
            and report.get("blocks_unclassified", 0) == 0)


def main() -> None:
    answers = []
    for group in ("A", "B"):
        for task in ("ps51", "ps7", "dual", "bat", "python", "safety"):
            path = RAW / group / (task + ".md")
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            report = coverage_for_answer(
                text, task, group,
                "../real-model-ab/raw/%s/%s.md" % (group, task))
            answers.append(report)

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
    payload = {
        "generated": "2026-11-14",
        "method": ("every fenced block is extracted with its markdown position; blocks "
                   "tagged powershell or recognised by content are parsed on both hosts"),
        "answers": answers,
        "summary": summary,
    }
    target = HERE / "parser-coverage.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    for item in answers:
        print("%s/%s status=%s blocks=%d ps=%d unchecked=%d roots=%s"
              % (item["group"], item["task"], item["status"], item["blocks_total"],
                 item["blocks_powershell"], item["unchecked_powershell_blocks"],
                 ",".join(item["root_causes"]) or "-"))
    print("wrote", target)


if __name__ == "__main__":
    main()
