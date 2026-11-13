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


def windows_ps51_exe():
    """Full path to Windows PowerShell 5.1, which every Windows host has."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = pathlib.Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.exists() else "powershell.exe"


def selected_host():
    """Return (exe, edition) for the PowerShell child processes must use.

    tests/run-all.ps1 exports WSW_PS_HOST / WSW_PS_EDITION from the host that is
    running it, so a matrix run under 5.1 exercises 5.1 and a run under 7
    exercises 7. Without that variable -- a plain `python -m unittest` -- the
    default is Windows PowerShell 5.1, which is what every Windows machine has.

    Guessing from the process name is not possible here: this process is
    python.exe, not a shell.
    """
    override = os.environ.get("WSW_PS_HOST")
    if override and pathlib.Path(override).exists():
        edition = os.environ.get("WSW_PS_EDITION")
        if not edition:
            edition = "Core" if pathlib.Path(override).name.lower().startswith("pwsh") else "Desktop"
        return override, edition
    return windows_ps51_exe(), "Desktop"


def shell_switch():
    """The run_ps.py --shell value that matches the selected host."""
    return "pwsh" if selected_host()[1] == "Core" else "powershell"


def run_python_fixture(path, timeout=120):
    """Execute a fixture with the current interpreter and capture its output.

    PYTHONIOENCODING is pinned to utf-8, on purpose. Whether the interpreter can
    write CJK to stdout depends on the encoding of that stream -- the host ANSI
    code page on Windows, which is 1252 on a hosted runner -- and has nothing to
    do with the encoding of the source file. Leaving it unset made these tests
    pass on a zh-CN machine and die with UnicodeEncodeError on every CI runner,
    which is a fact about the runner, not about PEP 263. Pinning the output
    stream leaves the source declaration as the only variable under test.
    """
    return subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        timeout=timeout,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )


def ps_tool(name, args, timeout=180, exe=None):
    host = exe or selected_host()[0]
    argv = [host, "-NoProfile", "-NonInteractive", "-File", str(SCRIPTS / name)] + list(args)
    return subprocess.run(argv, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)


def ps_file(script, timeout=120, exe=None):
    """Runs a bare script file with the same host a user would get."""
    host = exe or selected_host()[0]
    argv = [host, "-NoProfile", "-NonInteractive", "-File", str(script)]
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


def run_ps(args, stdin_bytes=None, timeout=180, shell=None):
    kwargs = dict(capture_output=True, timeout=timeout)
    if stdin_bytes is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin_bytes
    # The executor defaults to 5.1. Saying so explicitly keeps the execution half
    # of these tests on the same edition as the detection and writing halves.
    argv = [sys.executable, str(RUN_PS), "--shell", shell or shell_switch()] + list(args)
    return subprocess.run(argv, **kwargs)


def setUpModule():
    """Print which PowerShell this module is driving, once per run.

    Without this line a log shows identical test names for a 5.1 run and a 7
    run, and there is no way to tell them apart afterwards.
    """
    host, edition = selected_host()
    print("\n[integration] CHILD_PS=%s EDITION=%s SHELL_SWITCH=%s" % (host, edition, shell_switch()))


class TestHostSelection(unittest.TestCase):
    """Which PowerShell the child processes actually run, asserted not assumed.

    A suite that hard-codes powershell.exe still passes when the outer host is
    pwsh -- it just never exercises pwsh. These tests make the choice visible and
    fail when the intent and the process disagree.
    """

    def _report(self, host):
        argv = [
            host,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$PSVersionTable.PSEdition + '|' + $PSVersionTable.PSVersion.ToString()",
        ]
        r = subprocess.run(argv, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        edition, version = r.stdout.decode("ascii", "replace").strip().split("|")
        return edition, version

    def test_the_selected_host_is_the_one_the_launcher_named(self):
        host, edition = selected_host()
        self.assertTrue(pathlib.Path(host).exists(), host)
        override = os.environ.get("WSW_PS_HOST")
        if override:
            self.assertEqual(
                os.path.normcase(host), os.path.normcase(override),
                "the suite is not using the host the launcher exported",
            )

    def test_the_child_reports_the_expected_edition(self):
        host, edition = selected_host()
        actual_edition, version = self._report(host)
        print("CHILD_PS_HOST=%s EDITION=%s VERSION=%s" % (host, actual_edition, version))
        self.assertEqual(actual_edition, edition)
        self.assertIn(version.split(".")[0], ("5", "7"))

    def test_the_pinned_51_host_really_is_51(self):
        # Tests that depend on a 5.1-specific decode path pin this exe instead of
        # the selected one, so the pin has to be checked rather than trusted.
        edition, version = self._report(windows_ps51_exe())
        self.assertEqual(edition, "Desktop")
        self.assertEqual(version.split(".")[0], "5")


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


class TestPythonSourceCoding(unittest.TestCase):
    """The verdict has to match what a real interpreter does with the file.

    Each case is executed by Python first and judged by the detector second, and
    the two answers are required to agree. A detector that only pattern-matches
    the declaration without running anything would pass the first half of this
    and fail the second the day Python changes its mind.
    """

    CASES = (
        # fixture, interpreter exit, detector exit, reason that must appear
        ("py-coding-gbk.py", 0, 1, b"PY_SOURCE_CODING_DECLARED"),
        ("py-coding-equals.py", 0, 1, b"PY_SOURCE_CODING_DECLARED"),
        ("py-nocoding-gbk.py", 1, 2, b"CP936_PYTHON"),
        ("py-coding-conflict-bom.py", 1, 2, b"PY_SOURCE_CODING_CONFLICT"),
        ("py-coding-unknown.py", 1, 2, b"PY_SOURCE_CODING_UNKNOWN"),
    )

    def test_the_interpreter_and_the_detector_agree(self):
        for fixture, py_code, detector_code, reason in self.CASES:
            with self.subTest(fixture=fixture):
                path = FIXTURES / fixture
                run = run_python_fixture(path)
                self.assertEqual(run.returncode, py_code, (fixture, run.stderr[:400]))
                t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(path), "-Profile", "python"])
                self.assertEqual(t.returncode, detector_code, t.stdout)
                self.assertIn(reason, t.stdout)

    def test_a_declared_gbk_file_really_prints_its_cjk(self):
        path = FIXTURES / "py-coding-gbk.py"
        run = run_python_fixture(path)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(b"PYCODING_GBK_OK", run.stdout)
        self.assertIn(ZH.encode("utf-8"), run.stdout)

    def test_without_a_declaration_the_interpreter_refuses_the_file(self):
        path = FIXTURES / "py-nocoding-gbk.py"
        run = run_python_fixture(path)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(b"SyntaxError", run.stderr)

    def test_the_declaration_line_is_reported(self):
        # The reason text names the line, and it has to be the line the
        # declaration is really on, not a constant.
        t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(FIXTURES / "py-coding-gbk.py")])
        self.assertIn(b"SOURCE_CODING_LINE=1", t.stdout)
        self.assertIn(b"SOURCE_CODING=gbk", t.stdout)


class TestUtf32(unittest.TestCase):
    """Four byte marks, and the control case that keeps UTF-16 honest."""

    def test_a_four_byte_bom_is_not_reported_as_utf16(self):
        for fixture, expected in (
            ("utf32le-bom.ps1", b"ENCODING=utf32le-bom"),
            ("utf32be-bom.ps1", b"ENCODING=utf32be-bom"),
        ):
            with self.subTest(fixture=fixture):
                t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(FIXTURES / fixture), "-Profile", "ps51"])
                self.assertEqual(t.returncode, 2, t.stdout)
                self.assertIn(expected, t.stdout)
                self.assertNotIn(b"ENCODING=utf16", t.stdout)
                self.assertIn(b"UTF32_UNSUPPORTED", t.stdout)

    def test_a_two_byte_mark_is_still_utf16(self):
        # The control case. Without it, "detects UTF-32" could have been
        # implemented by refusing every FF FE file.
        for fixture, expected in (
            ("ps51-utf16le-bom.ps1", b"ENCODING=utf16le-bom"),
            ("ps51-utf16be-bom.ps1", b"ENCODING=utf16be-bom"),
        ):
            with self.subTest(fixture=fixture):
                t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(FIXTURES / fixture), "-Profile", "ps51"])
                self.assertIn(expected, t.stdout)
                self.assertNotIn(b"utf32", t.stdout)


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
        # Pinned to 5.1 on purpose: this is the defect the detector exists to
        # catch, and PowerShell 7 reads the same file as UTF-8 and prints it
        # correctly, so the assertion would invert under the selected host.
        r = ps_file(FIXTURES / "ps51-utf8nobom-cn.ps1", exe=windows_ps51_exe())
        self.assertEqual(r.returncode, 0)
        self.assertNotIn(ZH, decode_console_output(r.stdout))

    def test_ps51_parses_utf8_bom_correctly(self):
        # Also pinned: the claim is about 5.1 specifically.
        r = ps_file(FIXTURES / "ps51-utf8bom.ps1", exe=windows_ps51_exe())
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


class TestLauncher(unittest.TestCase):
    """tests/run-all.ps1: what it announces, and what it refuses to do.

    Two claims are checked here rather than assumed: the launcher names the host
    it drives (so two matrix jobs are traceable), and a missing test dependency
    is reported with the exact command instead of being installed silently.
    """

    def _run(self, suite, env=None):
        argv = [
            selected_host()[0], "-NoProfile", "-NonInteractive",
            "-File", str(REPO_ROOT / "tests" / "run-all.ps1"), "-Suite", suite,
        ]
        base = dict(os.environ, WSW_PS_HOST="", WSW_PS_EDITION="")
        if env:
            base.update(env)
        r = subprocess.run(argv, capture_output=True, timeout=300,
                           stdin=subprocess.DEVNULL, env=base)
        return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")

    def test_the_launcher_announces_the_host_it_exports(self):
        # -Suite python is deliberate. This asserts what the launcher prints
        # before it runs anything, and the python suite imports nothing outside
        # the standard library. Driving the evals suite instead made the
        # assertion depend on PyYAML being installed, so a host that had not
        # installed the test requirements reported a failure about the launcher
        # that was really a missing module.
        code, out, err = self._run("python")
        self.assertEqual(code, 0, out + err)
        self.assertIn("INTEGRATION_PS_HOST=", out)
        self.assertIn("EDITION=", out)
        self.assertIn("PYTHON_SUITE_OK=python", out)

    def test_a_missing_dependency_is_reported_not_installed(self):
        # Shadowing the module on PYTHONPATH reproduces "not installed" without
        # uninstalling anything. If the launcher still installs on its own, the
        # PYTHON_DEP_INSTALL marker appears and this fails.
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "yaml.py").write_text(
                "raise ImportError('shadowed for the test')\n", encoding="ascii"
            )
            code, out, err = self._run("evals", env={"PYTHONPATH": tmp})
        combined = out + err
        self.assertNotEqual(code, 0, combined)
        self.assertIn("PYTHON_DEP_MISSING=yaml", combined)
        self.assertIn("INSTALL_WITH=", combined)
        self.assertIn("-m pip install PyYAML", combined)
        self.assertNotIn("PYTHON_DEP_INSTALL=", combined)

    def test_the_dependency_file_names_what_the_suite_imports(self):
        text = (REPO_ROOT / "tests" / "requirements-test.txt").read_text(encoding="utf-8")
        self.assertIn("PyYAML", text)
        for line in text.splitlines():
            if line.startswith(("PyYAML", "pyyaml")):
                break
        else:
            self.fail("requirements-test.txt does not pin PyYAML")


if __name__ == "__main__":
    unittest.main(verbosity=2)
