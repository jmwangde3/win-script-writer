# -*- coding: utf-8 -*-
"""Release package checks: what the zip contains, and that it still works.

Run with:
    python -m unittest discover -s tests/integration -v

The package is built by tests/package.ps1, the same script the release workflow
calls, so this suite tests the artefact a tag really produces rather than a
reimplementation of it. Everything here reads the archive back from disk: an
assertion about what was meant to be staged proves nothing about what shipped.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "tests" / "package.ps1"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "data"

#: The tag whose notes section must exist in CHANGELOG.md. Kept at a released
#: version so the packaging test cannot drift into depending on unreleased text.
NOTES_TAG = "v1.0.0"

REQUIRED_ENTRIES = [
    "SKILL.md",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "scripts/Test-ScriptEncoding.ps1",
    "scripts/New-EncodedScript.ps1",
    "scripts/Get-WinScriptEnvironment.ps1",
    "scripts/run_ps.py",
]

REFERENCE_COUNT = 10


def powershell_exe():
    root = pathlib.Path(_os_environ("SystemRoot", r"C:\Windows"))
    candidate = root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.exists() else "powershell.exe"


def _os_environ(name, default):
    import os

    return os.environ.get(name, default)


class TestReleasePackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(cls._tmp.name)
        cls.zip_path = tmp / "package.zip"
        cls.notes_path = tmp / "notes.md"

        result = subprocess.run(
            [
                powershell_exe(), "-NoProfile", "-NonInteractive", "-File", str(PACKAGE),
                "-Tag", NOTES_TAG,
                "-OutputPath", str(cls.zip_path),
                "-NotesPath", str(cls.notes_path),
            ],
            capture_output=True,
            timeout=300,
            stdin=subprocess.DEVNULL,
        )
        cls.build = result
        if result.returncode != 0:
            raise AssertionError(
                "packaging failed: %s%s"
                % (result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace"))
            )
        with zipfile.ZipFile(cls.zip_path) as archive:
            cls.entries = archive.namelist()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_packaging_script_reports_what_it_shipped(self):
        out = self.build.stdout.decode("utf-8", "replace")
        self.assertIn("ENTRY_SEPARATOR=FORWARD_SLASH_OK", out)
        self.assertIn("ENTRY_ALLOWLIST=OK", out)
        self.assertIn("NOTES_SOURCE=changelog", out)

    def test_every_entry_uses_a_forward_slash(self):
        for name in self.entries:
            with self.subTest(entry=name):
                self.assertNotIn("\\", name)
                self.assertTrue(name.startswith("win-script-writer/"), name)

    def test_no_bytecode_or_cache_is_shipped(self):
        # The first release shipped scripts/__pycache__/run_ps.cpython-313.pyc,
        # because CI runs the suite in the same checkout before packaging.
        for name in self.entries:
            with self.subTest(entry=name):
                self.assertFalse(name.endswith((".pyc", ".pyo")), name)
                self.assertNotIn("__pycache__", name)

    def test_no_test_material_is_shipped(self):
        for name in self.entries:
            with self.subTest(entry=name):
                self.assertFalse(name.startswith("win-script-writer/tests/"), name)
                self.assertFalse(name.endswith((".log", ".trx", ".xml")), name)

    def test_the_documented_files_are_all_present(self):
        for required in REQUIRED_ENTRIES:
            with self.subTest(entry=required):
                self.assertIn("win-script-writer/" + required, self.entries)

    def test_all_references_are_present(self):
        references = [n for n in self.entries if "/references/" in n]
        self.assertEqual(len(references), REFERENCE_COUNT, references)

    def test_release_notes_are_utf8_and_come_from_the_changelog(self):
        raw = self.notes_path.read_bytes()
        text = raw.decode("utf-8")  # raises if it is not valid UTF-8
        self.assertTrue(text.startswith("## [" + NOTES_TAG.lstrip("v") + "]"), text[:60])
        self.assertNotIn("\ufffd", text)

    def test_the_extracted_tools_run_without_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with zipfile.ZipFile(self.zip_path) as archive:
                archive.extractall(root)
            package_root = root / "win-script-writer"
            self.assertTrue(package_root.is_dir())

            # The detector, run on a copy of a fixture, from the extracted tree.
            probe = root / "probe.ps1"
            probe.write_bytes((FIXTURES / "ps51-utf8bom.ps1").read_bytes())
            detect = subprocess.run(
                [powershell_exe(), "-NoProfile", "-NonInteractive", "-File",
                 str(package_root / "scripts" / "Test-ScriptEncoding.ps1"),
                 "-Path", str(probe), "-Profile", "ps51"],
                capture_output=True, timeout=180, stdin=subprocess.DEVNULL,
            )
            self.assertEqual(detect.returncode, 0, detect.stdout.decode("utf-8", "replace"))
            self.assertIn(b"VERDICT=OK", detect.stdout)

            # The executor, run from the extracted tree, with no repo on the path.
            run = subprocess.run(
                [sys.executable, str(package_root / "scripts" / "run_ps.py"),
                 "--command", 'Write-Output "package-ok"'],
                capture_output=True, timeout=180, stdin=subprocess.DEVNULL,
                cwd=str(root),
            )
            self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
            self.assertIn(b"package-ok", run.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
