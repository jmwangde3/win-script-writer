# -*- coding: utf-8 -*-
"""Deterministic checks for the skill packaging itself.

There is no way to unit-test "an agent loaded the right reference file", so this
suite tests the part that is mechanical and therefore worth guarding:

  * SKILL.md stays small (progressive disclosure is only real if the entry file
    is small).
  * every reference file exists, is routed from SKILL.md, and the entry file
    does not inline their content.
  * every tool named in SKILL.md exists under scripts/.
  * no local absolute paths, no TODOs, no secrets.

Run with:
    python -m unittest discover -s tests/evals -v
"""

from __future__ import annotations

import pathlib
import re
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "SKILL.md"
REFERENCES = REPO_ROOT / "references"
SCRIPTS = REPO_ROOT / "scripts"

MAX_SKILL_BYTES = 6000
MAX_REFERENCE_BYTES = 16000
MAX_FENCED_CODE_LINES = 80

REQUIRED_REFERENCES = [
    "encoding-matrix.md",
    "powershell-51.md",
    "powershell-7.md",
    "dual-version-compatibility.md",
    "cmd-bat.md",
    "python.md",
    "git-bash.md",
    "execution.md",
    "security.md",
    "troubleshooting.md",
]

REQUIRED_SCRIPTS = [
    "Test-ScriptEncoding.ps1",
    "New-EncodedScript.ps1",
    "Get-WinScriptEnvironment.ps1",
    "run_ps.py",
]


def read_skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end]
    data = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
    return data


class TestSkillEntryPoint(unittest.TestCase):
    def test_skill_file_exists(self):
        self.assertTrue(SKILL.exists())

    def test_frontmatter_has_name_and_description(self):
        fm = frontmatter(read_skill())
        self.assertEqual(fm.get("name"), "win-script-writer")
        self.assertTrue(fm.get("description"))

    def test_description_stays_within_the_documented_limit(self):
        fm = frontmatter(read_skill())
        self.assertLessEqual(len(fm.get("description", "")), 1024)

    def test_description_carries_the_trigger_words(self):
        text = read_skill()
        for word in ("PowerShell", "encoding", "GBK"):
            self.assertIn(word, text)

    def test_entry_file_stays_small(self):
        size = SKILL.stat().st_size
        self.assertLessEqual(size, MAX_SKILL_BYTES, "SKILL.md is %d bytes" % size)

    def test_entry_file_does_not_inline_fenced_code_dumps(self):
        text = read_skill()
        lines = 0
        inside = False
        for line in text.splitlines():
            if line.strip().startswith("```"):
                inside = not inside
                continue
            if inside:
                lines += 1
        self.assertLessEqual(lines, MAX_FENCED_CODE_LINES)


class TestReferenceRouting(unittest.TestCase):
    def test_every_required_reference_exists(self):
        for name in REQUIRED_REFERENCES:
            self.assertTrue((REFERENCES / name).exists(), "missing references/%s" % name)

    def test_every_reference_is_routed_from_skill(self):
        text = read_skill()
        for name in REQUIRED_REFERENCES:
            self.assertIn(name, text, "references/%s is not routed from SKILL.md" % name)

    def test_every_routed_reference_is_on_disk(self):
        text = read_skill()
        for match in re.findall(r"references/([A-Za-z0-9._-]+\.md)", text):
            self.assertTrue((REFERENCES / match).exists(), "SKILL.md routes to a missing file: %s" % match)

    def test_no_orphan_reference(self):
        text = read_skill()
        for path in REFERENCES.glob("*.md"):
            self.assertIn(path.name, text, "%s is never routed" % path.name)

    def test_references_stay_small(self):
        for path in REFERENCES.glob("*.md"):
            size = path.stat().st_size
            self.assertLessEqual(size, MAX_REFERENCE_BYTES, "%s is %d bytes" % (path.name, size))


class TestScriptContract(unittest.TestCase):
    def test_every_named_tool_exists(self):
        for name in REQUIRED_SCRIPTS:
            self.assertTrue((SCRIPTS / name).exists(), "missing scripts/%s" % name)

    def test_skill_documents_the_documented_tools(self):
        text = read_skill()
        for name in REQUIRED_SCRIPTS:
            self.assertIn(name, text)


class TestHygiene(unittest.TestCase):
    def test_no_local_absolute_paths(self):
        text = read_skill()
        self.assertIsNone(re.search(r"[A-Za-z]:\\Users\\", text))
        self.assertNotIn("H:\\", text)

    def test_no_unfinished_markers(self):
        for path in [SKILL] + list(REFERENCES.glob("*.md")) + list(SCRIPTS.iterdir()):
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("TODO:", body, "unfinished marker in %s" % path.name)

    def test_no_placeholder_secrets(self):
        text = read_skill()
        for needle in ("password=", "api_key=", "Authorization: Bearer"):
            self.assertNotIn(needle, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
