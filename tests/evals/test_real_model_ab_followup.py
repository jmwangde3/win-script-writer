# -*- coding: utf-8 -*-
"""Tests for the second reliability follow-up.

Covers the mechanical parts that decide whether a dynamic run may start:

  * every fenced block is found with its markdown position
  * PowerShell blocks are recognised by tag or by content when the tag is missing
  * a broken block is FAIL, and FAIL means the executor is not allowed to start
  * one root cause is not counted as six defects
  * the token comparison reports both the arithmetic and the weighted average
  * a routing record with a missing required page cannot be PASS

Parser tests need a Windows host; they skip elsewhere. The extraction, classification,
token and routing tests run everywhere.

Run with:
    python -m unittest discover -s tests/evals -v
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "tests" / "benchmarks" / "real-model-ab-followup" / "scripts"

HAS_POWERSHELL = sys.platform == "win32" and (
    shutil.which("pwsh") is not None
    or pathlib.Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe").is_file()
)


def load(name):
    spec = importlib.util.spec_from_file_location(
        "followup_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


coverage = load("parser_coverage")
tokens = load("token_comparison")
routing = load("routing_audit")


class ExtractionTests(unittest.TestCase):
    def test_blocks_carry_their_markdown_position(self):
        text = ("intro\n```powershell\nWrite-Output 'a'\n```\nprose\n"
                "```\n$b = 1\n```\n")
        blocks, unclosed = coverage.extract_blocks(text)
        self.assertFalse(unclosed)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["start_line"], 2)
        self.assertEqual(blocks[0]["language"], "powershell")
        self.assertEqual(blocks[1]["start_line"], 6)
        self.assertEqual(blocks[1]["language"], "")

    def test_unclosed_fence_is_reported(self):
        blocks, unclosed = coverage.extract_blocks("```powershell\nWrite-Output 'a'\n")
        self.assertTrue(unclosed)
        self.assertEqual(blocks, [])

    def test_language_tag_decides_first(self):
        self.assertTrue(coverage.is_powershell("powershell", "anything")[0])
        self.assertFalse(coverage.is_powershell("bat", "@echo off")[0])
        self.assertFalse(coverage.is_powershell("python", "print('x')")[0])

    def test_missing_tag_falls_back_to_content(self):
        is_ps, reason = coverage.is_powershell("", "Write-Output 'ok'\n")
        self.assertTrue(is_ps)
        self.assertEqual(reason, "content")

    def test_plain_prose_is_not_powershell(self):
        is_ps, _reason = coverage.is_powershell("", "这是一段说明文字，没有代码。\n")
        self.assertFalse(is_ps)

    def test_common_cmdlet_without_tag_is_powershell(self):
        self.assertTrue(coverage.is_powershell("", "Test-Path 'C:\\x'\n")[0])
        self.assertTrue(coverage.is_powershell("", "Set-Location C:\\x\n")[0])

    def test_structure_without_tag_is_powershell(self):
        self.assertTrue(coverage.is_powershell("", "foreach ($x in 1..2) { $x }\n")[0])
        self.assertTrue(coverage.is_powershell(
            "", "try { Get-Item x } catch { Write-Error $_ }\n")[0])

    def test_unknown_block_is_unclassified(self):
        kind, _reason = coverage.classify_block("", "一段无法判断用途的内容\n")
        self.assertEqual(kind, "UNCLASSIFIED")

    def test_bat_and_python_are_other(self):
        self.assertEqual(coverage.classify_block("bat", "@echo off\n")[0], "OTHER")
        self.assertEqual(coverage.classify_block("python", "print('x')\n")[0], "OTHER")

    def test_inline_command_is_extracted(self):
        spans = coverage.extract_inline("运行 `Get-ChildItem -Recurse` 查看。\n")
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["language"], "inline")

    def test_inline_identifier_is_not_a_command(self):
        self.assertEqual(coverage.extract_inline("文件是 `deploy.ps1`。\n"), [])


class ClassificationTests(unittest.TestCase):
    def test_structural_followups_are_cascades(self):
        errors = [
            {"line": 1, "column": 5, "error_id": "UnexpectedToken", "text": "'x'"},
            {"line": 1, "column": 9, "error_id": "MissingEndCurlyBrace", "text": "{"},
            {"line": 1, "column": 12, "error_id": "MissingCatchOrFinally", "text": "try"},
        ]
        result = coverage.classify(errors, "try { 'x' }")
        self.assertEqual(result["diagnostics"], 3)
        self.assertEqual(result["independent"], 1)
        self.assertEqual(result["cascade"], 2)

    def test_doubled_quote_is_one_root_cause(self):
        errors = [
            {"line": 1, "column": 11, "error_id": "UnexpectedToken", "text": "''H:\\work''"},
            {"line": 7, "column": 20, "error_id": "UnexpectedToken", "text": "''无法枚举''"},
            {"line": 9, "column": 1, "error_id": "MissingEndCurlyBrace", "text": "}"},
        ]
        result = coverage.classify(errors, "$root = ''H:\\work''")
        self.assertEqual(result["root_causes"], ["doubled-single-quote"])
        self.assertEqual(result["root_cause_count"], 1)
        self.assertEqual(result["independent"], 1)


@unittest.skipUnless(HAS_POWERSHELL, "needs Windows PowerShell and pwsh")
class CoverageIntegrationTests(unittest.TestCase):
    def report(self, text):
        return coverage.coverage_for_answer(text, "safety", "B", "inline fixture")

    def test_all_blocks_good(self):
        text = ("```powershell\nWrite-Output 'a'\n```\n"
                "```powershell\n$b = 1\nWrite-Output $b\n```\n")
        result = self.report(text)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["blocks_powershell"], 2)
        self.assertTrue(coverage.execution_allowed(result))

    def test_one_bad_block_fails_and_blocks_execution(self):
        text = ("```powershell\nWrite-Output 'a'\n```\n"
                "```powershell\n$root = ''H:\\work''\n```\n")
        result = self.report(text)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["blocks"][0]["parsed"] is False)
        self.assertTrue(result["blocks"][1]["parsed"] is False)
        self.assertFalse(coverage.execution_allowed(result))

    def test_no_blocks_is_not_applicable(self):
        result = self.report("只有文字说明，没有代码块。\n")
        self.assertEqual(result["status"], "N/A")
        self.assertEqual(result["blocks_total"], 0)
        self.assertTrue(coverage.execution_allowed(result))

    def test_missing_language_tag_is_still_parsed(self):
        result = self.report("```\nWrite-Output 'ok'\n```\n")
        self.assertEqual(result["blocks_powershell"], 1)
        self.assertEqual(result["blocks"][0]["detected_by"], "content")
        self.assertEqual(result["status"], "PASS")

    def test_prose_and_code_mix_only_parses_code(self):
        result = self.report(
            "先说明一下。\n\n```powershell\nWrite-Output 'ok'\n```\n\n再说明一下。\n")
        self.assertEqual(result["blocks_total"], 1)
        self.assertEqual(result["status"], "PASS")

    def test_unclosed_fence_blocks_execution(self):
        result = self.report("```powershell\nWrite-Output 'a'\n")
        self.assertTrue(result["unclosed_fence"])
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(coverage.execution_allowed(result))


class TokenMathTests(unittest.TestCase):
    def test_arithmetic_mean(self):
        self.assertEqual(tokens.arithmetic_mean([10.0, 20.0, 30.0]), 20.0)
        self.assertEqual(tokens.arithmetic_mean([]), 0.0)

    def test_weighted_saving_uses_token_totals(self):
        # (400 - 330) / 400 * 100
        self.assertAlmostEqual(tokens.weighted_saving([100, 300], [90, 240]), 17.5)

    def test_weighted_and_arithmetic_differ(self):
        a = [100, 900]
        b = [90, 450]
        arithmetic = tokens.arithmetic_mean([10.0, 50.0])
        weighted = tokens.weighted_saving(a, b)
        self.assertAlmostEqual(arithmetic, 30.0)
        self.assertAlmostEqual(weighted, 46.0)
        self.assertNotEqual(arithmetic, weighted)


class RoutingTests(unittest.TestCase):
    def test_consistent_record_passes(self):
        result = routing.audit_sample(
            ["references/a.md"], ["SKILL.md", "references/a.md"], ["references/a.md"],
            {"available": True, "counts": {"SKILL.md": 1, "references/a.md": 1},
             "order": ["SKILL.md", "references/a.md"]})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["extra"], [])
        self.assertEqual(result["entry_opened"], ["SKILL.md"])
        self.assertEqual(result["duplicates"], [])

    def test_missing_required_page_fails(self):
        result = routing.audit_sample(
            ["references/a.md", "references/b.md"], ["SKILL.md", "references/a.md"],
            ["references/a.md", "references/b.md"],
            {"available": False, "counts": {}, "order": []})
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("references/b.md", result["missing_required"])

    def test_extra_page_is_reported_without_failing(self):
        result = routing.audit_sample(
            ["references/a.md"], ["SKILL.md", "references/a.md", "references/c.md"],
            ["references/a.md"],
            {"available": True, "counts": {}, "order": []})
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["extra"], ["references/c.md"])

    def test_duplicate_read_fails(self):
        result = routing.audit_sample(
            ["references/a.md"], ["SKILL.md", "references/a.md"], ["references/a.md"],
            {"available": True,
             "counts": {"SKILL.md": 2, "references/a.md": 2},
             "order": ["SKILL.md", "references/a.md"]})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["duplicates"], ["references/a.md"])


if __name__ == "__main__":
    unittest.main()
