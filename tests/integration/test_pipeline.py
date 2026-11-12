# -*- coding: utf-8 -*-
"""End-to-end tests chaining the three PowerShell tools with the executor.

Run with:
    python -m unittest discover -s tests/integration -v

These tests are the ones that would have caught every v0 defect in combination:
a file written by the writer must be accepted by the detector and must execute
correctly through run_ps.py.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "data"
RUN_PS = SCRIPTS / "run_ps.py"

ZH = "\u4e2d\u6587"
CESHI = "\u6d4b\u8bd5"


def powershell_exe():
    """Full path to Windows PowerShell 5.1, which every Windows host has."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = pathlib.Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.exists() else "powershell.exe"


def ps_tool(name, args, timeout=180):
    argv = [powershell_exe(), "-NoProfile", "-NonInteractive", "-File", str(SCRIPTS / name)] + list(args)
    return subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)


def ps_file(script, timeout=120):
    """Runs a bare script file with the same host a user would get."""
    argv = [powershell_exe(), "-NoProfile", "-NonInteractive", "-File", str(script)]
    return subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)


def host_output_codepage():
    """Code page Windows PowerShell uses to encode its redirected stdout.

    PowerShell 5.1 derives its output encoding from the console output code
    page it inherits: 936 on a plain zh-CN console, 65001 as soon as the caller
    has switched the console to UTF-8. Tests that hard-code either value pass or
    fail depending on who launched them, so they decode with the real value.
    """
    import ctypes

    return int(ctypes.windll.kernel32.GetConsoleOutputCP())


def decode_console_output(raw):
    return raw.decode("cp%d" % host_output_codepage(), "replace")


def run_ps(args, stdin_bytes=None, timeout=180):
    kwargs = dict(capture_output=True, timeout=timeout)
    if stdin_bytes is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin_bytes
    return subprocess.run([sys.executable, str(RUN_PS)] + list(args), **kwargs)


class TestPipeline(unittest.TestCase):
    def test_written_file_is_accepted_and_executes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / (ZH + "_script.ps1")
            content = pathlib.Path(tmp) / "content.txt"
            content.write_text('Write-Output "%s%s"\n' % (ZH, CESHI), encoding="utf-8")

            w = ps_tool("New-EncodedScript.ps1", ["-Path", str(target), "-ContentFile", str(content), "-Encoding", "utf8-bom"])
            self.assertEqual(w.returncode, 0, w.stdout.decode("utf-8", "replace") + w.stderr.decode("utf-8", "replace"))
            self.assertTrue(target.exists())

            t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(target), "-Profile", "ps51"])
            self.assertEqual(t.returncode, 0, t.stdout.decode("utf-8", "replace"))

            r = run_ps(["--file", str(target), "--console-encoding", "utf8"])
            self.assertEqual(r.returncode, 0, r.stderr.decode("utf-8", "replace"))
            self.assertIn((ZH + CESHI).encode("utf-8"), r.stdout)

    def test_gbk_output_is_flagged_for_ps51_and_executes_on_cp936(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "gbk_script.ps1"
            content = pathlib.Path(tmp) / "content.txt"
            content.write_text('Write-Output "%s"\n' % ZH, encoding="utf-8")

            w = ps_tool("New-EncodedScript.ps1", ["-Path", str(target), "-ContentFile", str(content), "-Encoding", "gbk"])
            self.assertEqual(w.returncode, 0)

            t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(target), "-Profile", "ps51"])
            self.assertEqual(t.returncode, 1, t.stdout.decode("utf-8", "replace"))
            self.assertIn(b"ENCODING=gbk", t.stdout)

    def test_detector_rejects_bomless_utf8_that_the_writer_never_produces(self):
        t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(FIXTURES / "ps51-utf8nobom-cn.ps1"), "-Profile", "ps51"])
        self.assertEqual(t.returncode, 2)

    def test_environment_report_matches_this_machine(self):
        import ctypes

        acp = ctypes.windll.kernel32.GetACP()
        r = ps_tool("Get-WinScriptEnvironment.ps1", [])
        self.assertEqual(r.returncode, 0)
        self.assertIn(b"ACP=%d" % acp, r.stdout)


class TestUtf16Scripts(unittest.TestCase):
    """What UTF-16 really does, so the verdicts are backed by execution.

    The detector rates UTF-16LE with a BOM as WARN (runnable, not preferred) and
    UTF-16BE as FAIL. Both claims are assertions about a real interpreter, so
    they are executed here rather than assumed.
    """

    def _write(self, tmp, encoding, with_bom, marker):
        body = 'Write-Output "%s"\n' % marker
        path = pathlib.Path(tmp) / ("probe-%s.ps1" % encoding)
        raw = body.encode(encoding)
        if with_bom:
            raw = (b"\xff\xfe" if encoding == "utf-16-le" else b"\xfe\xff") + raw
        path.write_bytes(raw)
        return path

    def test_utf16le_with_bom_runs_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "utf-16-le", True, "utf16le-ran")
            r = run_ps(["--invoke-file", str(path)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"utf16le-ran", r.stdout)

    def test_utf16be_with_bom_also_runs(self):
        # Measured, not assumed: with a real FE FF mark both runtimes honour it
        # and execute the script. The first version of this test asserted the
        # opposite and was wrong -- the fixture it used had been written by a
        # codec that does not emit a BOM, so it was measuring BOM-less UTF-16.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "utf-16-be", True, "utf16be-ran")
            r = run_ps(["--invoke-file", str(path)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"utf16be-ran", r.stdout)

    def test_utf16_without_a_bom_does_not_run_and_still_exits_zero(self):
        # This is the form that really fails: the NUL pattern is tokenised as
        # single-byte text, the script dies at the first character, and the
        # process still reports success.
        for encoding, bom in (("utf-16-le", b""), ("utf-16-be", b"")):
            with self.subTest(encoding=encoding):
                with tempfile.TemporaryDirectory() as tmp:
                    path = self._write(tmp, encoding, False, "nobom-ran")
                    r = run_ps(["--invoke-file", str(path)])
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn(b"nobom-ran", r.stdout)

    def test_detector_verdicts_match_the_execution_results(self):
        for fixture, code, reason in (
            ("ps51-utf16le-bom.ps1", 1, b"UTF16LE_RUNNABLE_NOT_PREFERRED"),
            ("ps51-utf16be-bom.ps1", 1, b"UTF16BE_RUNNABLE_NOT_PREFERRED"),
            ("utf16le-nobom.ps1", 2, b"UTF16_NO_BOM"),
            ("utf16be-nobom.ps1", 2, b"UTF16_NO_BOM"),
        ):
            with self.subTest(fixture=fixture):
                r = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(FIXTURES / fixture), "-Profile", "ps51"])
                self.assertEqual(r.returncode, code, r.stdout)
                self.assertIn(reason, r.stdout)


class TestBomPayloadPipeline(unittest.TestCase):
    def test_a_bom_with_a_corrupt_payload_is_rejected_before_it_runs(self):
        # The file executes in 5.1 -- partially, with an error, and exit 0. The
        # detector is the only thing standing between that and a green build.
        fixture = FIXTURES / "utf8bom-invalid-ff.bin"
        t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(fixture), "-Profile", "ps51"])
        self.assertEqual(t.returncode, 2, t.stdout)
        self.assertIn(b"PAYLOAD_VALID=False", t.stdout)
        self.assertIn(b"INVALID_ENCODING_PAYLOAD", t.stdout)


class TestCp936Host(unittest.TestCase):
    """Only meaningful on a host whose ANSI code page really is 936.

    A hosted CI runner is en-US (ACP 1252), so these assertions are skipped
    there instead of being faked. The dedicated CP936 gate lives in
    .github/workflows/cp936.yml and runs on a self-hosted runner.
    """

    @classmethod
    def setUpClass(cls):
        import ctypes

        cls.acp = ctypes.windll.kernel32.GetACP()
        if cls.acp != 936:
            raise unittest.SkipTest("host ANSI code page is %d, not 936" % cls.acp)

    def test_ps51_parses_bomless_utf8_as_gbk(self):
        # Documents the defect the detector exists to catch: without a BOM,
        # Windows PowerShell 5.1 decodes the bytes as the ANSI code page, so the
        # Chinese text arrives mangled no matter how the console encodes stdout.
        r = ps_file(FIXTURES / "ps51-utf8nobom-cn.ps1")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn(ZH, decode_console_output(r.stdout))

    def test_ps51_parses_utf8_bom_correctly(self):
        r = ps_file(FIXTURES / "ps51-utf8bom.ps1")
        self.assertEqual(r.returncode, 0)
        self.assertIn(ZH, decode_console_output(r.stdout))

    def test_writer_round_trip_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "roundtrip.ps1"
            content = FIXTURES / "content-utf8.txt"
            first = ps_tool("New-EncodedScript.ps1", ["-Path", str(target), "-ContentFile", str(content), "-Encoding", "utf8-bom", "-Force"])
            self.assertEqual(first.returncode, 0)
            before = target.read_bytes()
            again = ps_tool("New-EncodedScript.ps1", ["-Path", str(target), "-ContentFile", str(content), "-Encoding", "utf8-bom", "-Force"])
            self.assertEqual(again.returncode, 0)
            self.assertEqual(before, target.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
