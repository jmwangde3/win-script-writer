# -*- coding: utf-8 -*-
"""End-to-end tests chaining the three PowerShell tools with the executor.

Run with:
    python -m unittest discover -s tests/integration -v

These tests are the ones that would have caught every v0 defect in combination:
a file written by the writer must be accepted by the detector and must execute
correctly through run_ps.py.
"""

from __future__ import annotations

import json
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
        ("py-coding-gb2312.py", 0, 1, b"PY_SOURCE_CODING_DECLARED"),
        ("py-coding-euc-cn.py", 0, 1, b"PY_SOURCE_CODING_DECLARED"),
        ("py-coding-hz.py", 0, 1, b"PY_SOURCE_CODING_HZ"),
        ("py-coding-gb18030.py", 0, 1, b"PY_SOURCE_CODING_DECLARED"),
        ("py-nocoding-gbk.py", 1, 2, b"CP936_PYTHON"),
        ("py-coding-conflict-bom.py", 1, 2, b"PY_SOURCE_CODING_BOM_CONFLICT"),
        ("py-coding-unknown.py", 1, 2, b"PY_SOURCE_CODING_UNKNOWN"),
        ("py-coding-windows936.py", 1, 2, b"PY_SOURCE_CODING_UNKNOWN"),
        ("py-coding-cp54936.py", 1, 2, b"PY_SOURCE_CODING_UNKNOWN"),
        ("py-coding-gbk-as-gb2312.py", 1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
        ("py-coding-hz-truncated.py", 1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
        # Names CPython resolves and this tool cannot verify: the file runs, so
        # the only honest verdict is a warning.
        ("py-coding-cp1252.py", 0, 1, b"PY_SOURCE_CODING_UNVERIFIED"),
        ("py-coding-shift-jis.py", 0, 1, b"PY_SOURCE_CODING_UNVERIFIED"),
        ("py-coding-big5.py", 0, 1, b"PY_SOURCE_CODING_UNVERIFIED"),
        # Names that look like codecs and are not.
        ("py-coding-54936.py", 1, 2, b"PY_SOURCE_CODING_UNKNOWN"),
        ("py-coding-hzgb2312.py", 1, 2, b"PY_SOURCE_CODING_UNKNOWN"),
        ("py-coding-cn-gb.py", 1, 2, b"PY_SOURCE_CODING_UNKNOWN"),
        # Latin-1 has no invalid byte sequence; a non-ASCII body is legal and
        # a BOM beside it is not.
        ("py-coding-latin1.py", 0, 1, b"PY_SOURCE_CODING_DECLARED"),
        ("py-coding-latin1-ascii.py", 0, 0, b"VERDICT=OK"),
        ("py-coding-latin1-utf8.py", 0, 1, b"PY_SOURCE_CODING_AMBIGUOUS"),
        ("py-coding-latin1-bom.py", 1, 2, b"PY_SOURCE_CODING_BOM_CONFLICT"),
        # utf-8-sig is utf-8, and the utf8 spelling is not: CPython compares the
        # normalised name with "utf-8" before it accepts a BOM.
        ("py-coding-utf8-sig.py", 0, 0, b"VERDICT=OK"),
        ("py-coding-utf8-spelling-bom.py", 1, 2, b"PY_SOURCE_CODING_BOM_CONFLICT"),
        # The BOM outranks the name lookup: this one is reported as a BOM
        # conflict even though the name never resolves either.
        ("py-coding-unknown-bom.py", 1, 2, b"PY_SOURCE_CODING_BOM_CONFLICT"),
        # The declaration cannot decode these bytes at all.
        ("py-coding-utf8-as-gbk.py", 1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
        ("py-coding-utf8-as-gb2312.py", 1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
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


class TestGb2312Grid(unittest.TestCase):
    """The GB2312 table the detector carries against the one CPython has.

    Windows has no GB2312 code page, so the detector maps the assigned cells by
    hand. A hand written map drifts; this is the check that notices. Both files
    are built from the interpreter's own codec, so a cell only appears when
    Python itself decodes and re-encodes it byte for byte.
    """

    @staticmethod
    def _assigned_pairs():
        pairs = []
        for lead in range(0xA1, 0xF8):
            for trail in range(0xA1, 0xFF):
                pair = bytes((lead, trail))
                try:
                    text = pair.decode("gb2312")
                except UnicodeDecodeError:
                    continue
                if text.encode("gb2312") != pair:
                    continue
                pairs.append(pair)
        return pairs

    def _write(self, directory, pairs, name):
        lines = [b"# -*- coding: gb2312 -*-"]
        for index in range(0, len(pairs), 60):
            chunk = b"".join(pairs[index:index + 60])
            lines.append(b'MARKER_%d = "' % (index // 60) + chunk + b'"')
        body = b"\n".join(lines) + b"\n"
        path = pathlib.Path(directory) / name
        path.write_bytes(body)
        return path

    def test_every_assigned_cell_is_accepted(self):
        pairs = self._assigned_pairs()
        # 7445 on CPython 3.13. A lower bound keeps the test meaningful if the
        # codec gains cells later, without pretending the number is fixed.
        self.assertGreater(len(pairs), 7000)
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, pairs, "grid-all.py")
            run = run_python_fixture(path)
            self.assertEqual(run.returncode, 0, run.stderr[:400])
            t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(path), "-Profile", "python"])
            self.assertEqual(t.returncode, 1, t.stdout[-800:])
            self.assertIn(b"VERDICT=WARN", t.stdout)
            self.assertNotIn(b"PY_SOURCE_CODING_INVALID_BYTES", t.stdout)

    def test_a_gbk_only_cell_is_refused(self):
        # Leads GB2312 leaves empty (AA-AF), leads past its ceiling (F8-FF) and
        # the two byte extensions below A1. Any one of them makes the file
        # illegal, because Python decodes the whole source with gb2312.
        found = []
        for lead in (0x81, 0x82, 0xAA, 0xAB, 0xF8, 0xFE):
            for trail in (0x40, 0x41, 0xA0, 0xA1, 0xFE):
                pair = bytes((lead, trail))
                try:
                    text = pair.decode("gbk")
                except UnicodeDecodeError:
                    continue
                if text.encode("gbk") != pair:
                    continue
                try:
                    pair.decode("gb2312")
                except UnicodeDecodeError:
                    found.append(pair)
        self.assertGreater(len(found), 3)
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, found, "grid-gbk-only.py")
            run = run_python_fixture(path)
            self.assertNotEqual(run.returncode, 0)
            t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(path), "-Profile", "python"])
            self.assertEqual(t.returncode, 2, t.stdout[-800:])
            self.assertIn(b"PY_SOURCE_CODING_INVALID_BYTES", t.stdout)


class TestHzStateMachine(unittest.TestCase):
    """HZ against the interpreter's own codec, byte for byte.

    Every payload here is produced by a codec at run time instead of pasted in
    as hex, so the escapes this test trusts are the ones CPython emits. The
    expected interpreter result is measured on each case before the detector is
    asked, and the two answers have to agree.

    CPython's hz decoder is stricter than RFC 1843 in three places and looser in
    one, and all four are covered: ~~ and ~<LF> are ASCII-mode only, ~} is not an
    escape outside GB mode, a trailing 0x7E can be the second half of a cell, and
    a file that ends inside GB mode still decodes.
    """

    @staticmethod
    def _file(directory, name, body):
        path = pathlib.Path(directory) / name
        path.write_bytes(b"# -*- coding: hz -*-\n" + body)
        return path

    def test_the_detector_matches_the_codec_case_by_case(self):
        run7e = b""
        zhu = "\u7b51"                      # 筑, whose GB2312 cell is D6 FE
        gb = zhu.encode("gb2312")
        run7e = bytes(b - 0x80 for b in gb)
        self.assertIn(b"\x7e", run7e, "the fixture needs a 0x7E in the payload")

        hz_run = ZH.encode("hz")
        self.assertTrue(hz_run.startswith(b"~{"), hz_run)

        cases = (
            # label, body, interpreter exit, detector exit, reason
            ("well formed run", b'MARKER = "' + hz_run + b'"\n', 0, 1, b"PY_SOURCE_CODING_HZ"),
            ("literal tilde in ASCII mode", b'MARKER = "~~"\n', 0, 1, b"PY_SOURCE_CODING_HZ"),
            ("line continuation in ASCII mode", b'MARKER = "ab~\ncd"\n', 0, 1, b"PY_SOURCE_CODING_HZ"),
            ("0x7E as the second half of a cell", b'MARKER = "~{' + run7e + b'~}"\n',
             0, 1, b"PY_SOURCE_CODING_HZ"),
            ("~~ inside GB mode", b'MARKER = "~{~~}"\n', 1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
            ("~} outside GB mode", b'MARKER = "~}"\n', 1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
            ("dangling byte after a run", b"# ~{VPND\n", 1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
            # RFC 1843 allows a line continuation in both modes; the interpreter
            # allows it in one. Inside GB mode the tilde starts a cell whose
            # second byte would be 0x0A, and 0x0A is outside 0x21-0x7E. Both
            # endings are pinned because the answer came from the codec and not
            # from the document, and a rule that only handled LF would pass a
            # CRLF file the interpreter rejects.
            ("line continuation inside GB mode, LF", b'MARKER = "~{VP~\nXX~}"\n',
             1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
            ("line continuation inside GB mode, CRLF", b'MARKER = "~{VP~\r\nXX~}"\n',
             1, 2, b"PY_SOURCE_CODING_INVALID_BYTES"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            for index, (label, body, py_code, detector_code, reason) in enumerate(cases):
                with self.subTest(case=label):
                    path = self._file(tmp, "hz-%02d.py" % index, body)
                    run = run_python_fixture(path)
                    self.assertEqual(run.returncode, py_code, (label, run.stderr[:300]))
                    t = ps_tool("Test-ScriptEncoding.ps1",
                                ["-Path", str(path), "-Profile", "python"])
                    self.assertEqual(t.returncode, detector_code, (label, t.stdout[-600:]))
                    self.assertIn(reason, t.stdout, label)

            # A run left open is the one case where the interpreter is the
            # looser of the two: it decodes the file, so a failure here would be
            # a false alarm. The open state still has to be reported.
            with self.subTest(case="run left open at end of file"):
                path = self._file(tmp, "hz-open.py", b"# ~{VPND")
                run = run_python_fixture(path)
                self.assertEqual(run.returncode, 0, run.stderr[:300])
                t = ps_tool("Test-ScriptEncoding.ps1",
                            ["-Path", str(path), "-Profile", "python"])
                self.assertEqual(t.returncode, 1, t.stdout[-600:])
                self.assertIn(b"ends inside GB mode", t.stdout)
                self.assertNotIn(b"PY_SOURCE_CODING_INVALID_BYTES", t.stdout)


class TestEncodingOverlap(unittest.TestCase):
    """Bytes two codecs both accept, and what the interpreter does with them.

    C3 A9 is 茅 in every Chinese codec and é in UTF-8. The interpreter decodes
    with the declaration, so the file runs; calling it a conflict was a false
    alarm about a file that works. The detector has to say "ambiguous" without
    going soft on bytes the declaration genuinely cannot decode.
    """

    def test_bytes_two_codecs_accept_are_called_ambiguous(self):
        char = "\u8305"                     # 茅, C3 A9 in GB2312, GBK and GB18030
        for codec in ("gb2312", "gbk", "gb18030"):
            with self.subTest(codec=codec):
                body = char.encode(codec)
                # The overlap is a fact about the interpreter, not an assumption
                # of this test: if the bytes stopped being valid UTF-8 the case
                # would be meaningless and must not be silently kept.
                self.assertEqual(body.decode("utf-8"), "\u00e9", body.hex())
                with tempfile.TemporaryDirectory() as tmp:
                    path = pathlib.Path(tmp) / ("overlap-%s.py" % codec)
                    path.write_bytes(b"# -*- coding: " + codec.encode() + b" -*-\n"
                                     + b'MARKER = "' + body + b'"\n'
                                     + b'print("OVERLAP_OK")\n')
                    run = run_python_fixture(path)
                    self.assertEqual(run.returncode, 0, run.stderr[:300])
                    t = ps_tool("Test-ScriptEncoding.ps1",
                                ["-Path", str(path), "-Profile", "python"])
                    self.assertEqual(t.returncode, 1, t.stdout[-600:])
                    self.assertIn(b"PY_SOURCE_CODING_AMBIGUOUS", t.stdout)
                    self.assertNotIn(b"PY_SOURCE_CODING_CONFLICT", t.stdout)

    def test_a_declaration_that_cannot_decode_the_bytes_still_fails(self):
        # UTF-8 CJK is not GBK: 0xAD is a legal CP936 lead and an unassigned GBK
        # cell, so the interpreter raises and the verdict has to be a failure.
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "utf8-as-gbk.py"
            path.write_bytes(b"# -*- coding: gbk -*-\nMARKER = \"" + ZH.encode("utf-8") + b"\"\n")
            run = run_python_fixture(path)
            self.assertNotEqual(run.returncode, 0)
            t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(path), "-Profile", "python"])
            self.assertEqual(t.returncode, 2, t.stdout[-600:])
            self.assertIn(b"PY_SOURCE_CODING_INVALID_BYTES", t.stdout)

    def test_latin1_handles_a_non_ascii_body(self):
        eacute = "\u00e9"
        with tempfile.TemporaryDirectory() as tmp:
            # Latin-1 bytes: legal, and not valid UTF-8, so nothing competes.
            latin_path = pathlib.Path(tmp) / "latin1.py"
            latin_path.write_bytes(b"# -*- coding: latin-1 -*-\nMARKER = \""
                                   + eacute.encode("latin-1") + b"\"\n")
            self.assertRaises(UnicodeDecodeError,
                              latin_path.read_bytes()[-4:-2].decode, "utf-8")
            run = run_python_fixture(latin_path)
            self.assertEqual(run.returncode, 0, run.stderr[:300])
            t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(latin_path), "-Profile", "python"])
            self.assertEqual(t.returncode, 1, t.stdout[-600:])
            self.assertIn(b"PY_SOURCE_CODING_DECLARED", t.stdout)

            # The same declaration over UTF-8 bytes: runs, prints mojibake, and
            # the detector may not pick a side.
            utf8_path = pathlib.Path(tmp) / "latin1-utf8.py"
            utf8_path.write_bytes(b"# -*- coding: latin-1 -*-\nMARKER = \""
                                  + eacute.encode("utf-8") + b"\"\n")
            run = run_python_fixture(utf8_path)
            self.assertEqual(run.returncode, 0, run.stderr[:300])
            t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(utf8_path), "-Profile", "python"])
            self.assertEqual(t.returncode, 1, t.stdout[-600:])
            self.assertIn(b"PY_SOURCE_CODING_AMBIGUOUS", t.stdout)


class TestCodingNameAgreement(unittest.TestCase):
    """Every codec name the detector classifies, checked against CPython.

    The detector cannot import Python, so its list of names is data, and data
    drifts. Each name below is written into a real source file with an ASCII
    body; the interpreter then decides whether the name is usable at all, and
    the detector has to give the same answer. Nothing here spells out which
    answer a given name should get, so the test survives a stdlib that adds or
    drops an alias -- only genuine disagreement fails.

    The list is deliberately made of the name's shape, not of one release's
    behaviour: names the detector verifies byte by byte, names it merely
    recognises, spellings that read like aliases and are not, and transforms
    that resolve in codecs.lookup() but are not text codecs.
    """

    NAMES = (
        # verified byte by byte
        "utf-8", "ascii", "latin-1", "gbk", "gb2312", "hz", "gb18030",
        # recognised, not verified: CPython runs these, this tool cannot check
        # the bytes and says so instead of calling the name invalid
        "cp1252", "shift_jis", "big5", "euc-jp", "mac-roman", "csisolatin2",
        "latin2", "utf-8-unix", "iso-latin-1", "1252", "ansi",
        # spellings that read like aliases and are not
        "windows-936", "cp54936", "54936", "hzgb2312", "cn-gb", "gb-2312",
        "utf8-sig", "latin-2", "cp424",
        # transforms: codecs.lookup() resolves them, the tokenizer refuses them
        "base64", "rot13",
    )

    def test_the_detector_agrees_with_the_interpreter_name_by_name(self):
        disagreements = []
        with tempfile.TemporaryDirectory() as tmp:
            for index, name in enumerate(self.NAMES):
                with self.subTest(name=name):
                    path = pathlib.Path(tmp) / ("codec-%02d.py" % index)
                    path.write_bytes(("# coding: %s\ns = 'A'\n" % name).encode("ascii"))
                    run = run_python_fixture(path)
                    t = ps_tool("Test-ScriptEncoding.ps1",
                                ["-Path", str(path), "-Profile", "python"])
                    detector_fails = t.returncode == 2
                    # exit 0/1 means the detector thinks the file runs. Exit 3 is
                    # a tool error and would otherwise read as "runs".
                    self.assertIn(t.returncode, (0, 1, 2), t.stdout[-400:])
                    if detector_fails != (run.returncode != 0):
                        support = [line for line in decode_console_output(t.stdout).splitlines()
                                   if line.startswith(("SOURCE_CODING_SUPPORT", "REASON"))]
                        disagreements.append(
                            (name, run.returncode, t.returncode, support))
        self.assertEqual(disagreements, [],
                         "detector and interpreter disagree: %r" % (disagreements,))


class TestUnusableCodecReason(unittest.TestCase):
    """A transform codec is a third diagnosis, not a misspelt name.

    codecs.lookup() resolves base64, rot13, hex, zlib, uu, bz2 and quopri; the
    tokenizer then refuses the declaration because none of them is a text
    codec, and says so in its own words. v1.0.3 filed all of them under
    "unknown encoding", which points at a typo that is not there. The verdict
    stays FAIL -- only the reason changes -- and this test holds both halves:
    the interpreter really does refuse on the name, and the detector really
    does use the other code.
    """

    TRANSFORMS = (
        "base64", "base64_codec", "base_64",
        "rot13", "rot_13",
        "hex", "hex_codec",
        "zlib", "zlib_codec", "zip",
        "uu", "uu_codec",
        "bz2", "bz2_codec",
        "quopri", "quopri_codec", "quoted_printable", "quotedprintable",
    )

    def test_the_interpreter_refuses_the_declaration_on_the_name(self):
        for name in self.TRANSFORMS:
            with self.subTest(name=name):
                data = ("# coding: %s\ns = 'A'\n" % name).encode("ascii")
                with self.assertRaises(SyntaxError) as caught:
                    compile(data, "<%s>" % name, "exec")
                # The wording matters: it is the sentence the detector quotes
                # and the reason the name is not the thing to fix.
                self.assertIn("is not a text encoding", caught.exception.msg)

    def test_the_detector_reports_unusable_and_not_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index, name in enumerate(self.TRANSFORMS):
                path = pathlib.Path(tmp) / ("transform-%02d.py" % index)
                path.write_bytes(("# coding: %s\ns = 'A'\n" % name).encode("ascii"))
                paths.append((name, path))

            result = run_detector_over_many([p for _, p in paths])
            document = json.loads(decode_console_output(result.stdout))
            by_path = {item["Path"]: item for item in document["Files"]}

            for name, path in paths:
                item = by_path[str(path)]
                with self.subTest(name=name):
                    self.assertEqual(item["Verdict"], "FAIL", item.get("Reasons"))
                    self.assertEqual(item["SourceCodingKind"], "unusable-codec")
                    self.assertEqual(item["SourceCodingSupport"], "unusable")
                    reasons = " ".join(item.get("Reasons") or [])
                    self.assertIn("PY_SOURCE_CODING_UNUSABLE", reasons)
                    self.assertNotIn("PY_SOURCE_CODING_UNKNOWN", reasons)

    def test_an_unknown_name_keeps_the_other_reason(self):
        """The two diagnoses must stay apart.

        Same FAIL, different advice: one is "fix the spelling", the other is
        "that codec is for codecs.decode(), not for a source file".
        """
        with tempfile.TemporaryDirectory() as tmp:
            unknown = pathlib.Path(tmp) / "unknown.py"
            unknown.write_bytes(b"# coding: ghost-codec\ns = 'A'\n")
            transform = pathlib.Path(tmp) / "transform.py"
            transform.write_bytes(b"# coding: base64\ns = 'A'\n")

            result = run_detector_over_many([unknown, transform])
            document = json.loads(decode_console_output(result.stdout))
            by_name = {pathlib.Path(i["Path"]).stem: i for i in document["Files"]}

            ghost = by_name["unknown"]
            self.assertEqual(ghost["Verdict"], "FAIL")
            self.assertEqual(ghost["SourceCodingKind"], "unknown-name")
            self.assertIn("PY_SOURCE_CODING_UNKNOWN", " ".join(ghost["Reasons"]))
            self.assertNotIn("PY_SOURCE_CODING_UNUSABLE", " ".join(ghost["Reasons"]))

            base = by_name["transform"]
            self.assertEqual(base["Verdict"], "FAIL")
            self.assertEqual(base["SourceCodingKind"], "unusable-codec")


class TestCodecCompatibilitySet(unittest.TestCase):
    """The name table is a union over releases, and says so.

    cp858 gained the spelling cp00858 with gh-149801, which first shipped in
    3.13.14 and 3.14.6 (3.15.0b2 on the 3.15 line): 3.11.17, 3.13.9 and 3.14.8
    were each asked, and the first two answer "unknown encoding: cp00858" while
    the last compiles it. A detector that copied one host's stdlib would either
    reject a file the newer patch runs or promise a file the older patch cannot
    compile. Neither is acceptable, so the answer is a WARN that names the set
    instead of the interpreter, with the payload left unverified -- on every
    host, whichever side of that line it sits on.
    """

    NAME = "cp00858"

    def setUp(self):
        import codecs

        try:
            self.resolved = codecs.lookup(self.NAME).name
        except LookupError:
            self.resolved = None

    def test_the_host_really_sits_on_one_side_of_the_split(self):
        data = ("# coding: %s\ns = 'A'\n" % self.NAME).encode("ascii")
        if self.resolved is None:
            with self.assertRaises(SyntaxError) as caught:
                compile(data, "<compat>", "exec")
            self.assertIn("unknown encoding", caught.exception.msg)
        else:
            compile(data, "<compat>", "exec")

    def test_the_detector_warns_and_never_passes_or_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "compat.py"
            path.write_bytes(("# coding: %s\ns = 'A'\n" % self.NAME).encode("ascii"))

            text = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(path), "-Profile", "python"])
            body = decode_console_output(text.stdout)

            print("\n[compat-set] python=%s %s resolves=%s"
                  % (sys.version.split()[0], self.NAME, self.resolved))
            # 1 is WARN. 0 would be a pass on a file one of the two hosts in
            # the matrix cannot compile, and 2 would fail a file the other runs.
            self.assertEqual(text.returncode, 1, body[-800:])
            self.assertIn("VERDICT=WARN", body)
            self.assertIn("SOURCE_CODING_SUPPORT=python-only", body)
            self.assertIn("SOURCE_CODING_PAYLOAD=unverified", body)
            self.assertIn("compatibility set", body)
            self.assertNotIn("CPython recognizes this codec", body)

            document = json.loads(decode_console_output(
                ps_tool("Test-ScriptEncoding.ps1",
                        ["-Path", str(path), "-Profile", "python", "-Output", "json"]).stdout))
            item = document["Files"][0]
            self.assertEqual(item["Verdict"], "WARN")
            self.assertEqual(item["SourceCodingPayload"], "unverified")
            self.assertNotEqual(item["Verdict"], "OK")


def run_detector_over_many(paths, timeout=600, exe=None):
    """Detect a whole directory in one process.

    One process per file would add half a second of PowerShell startup to each
    of several hundred names. The paths go through a list file rather than the
    command line: the Windows limit is 32767 characters and a few hundred paths
    get close enough to matter.
    """
    host = exe or selected_host()[0]
    listfile = pathlib.Path(tempfile.mkdtemp()) / "paths.txt"
    listfile.write_text("\n".join(str(p) for p in paths), encoding="utf-8")
    env = dict(os.environ)
    env["WSW_BATCH_LIST"] = str(listfile)
    env["WSW_BATCH_TOOL"] = str(SCRIPTS / "Test-ScriptEncoding.ps1")
    command = (
        "$list = Get-Content -LiteralPath $env:WSW_BATCH_LIST -Encoding UTF8; "
        "& $env:WSW_BATCH_TOOL -Path $list -Profile python -Output json"
    )
    argv = [host, "-NoProfile", "-NonInteractive", "-Command", command]
    return subprocess.run(argv, capture_output=True, timeout=timeout, env=env,
                          stdin=subprocess.DEVNULL)


def alias_spellings():
    """Every spelling CPython itself offers, plus the shapes worth distrusting.

    Taken from encodings.aliases and the module names in encodings/, so the set
    follows the interpreter rather than a list someone typed. The extras are the
    look-alikes: a separator dropped, a word glued on, a code page number.
    """
    import encodings
    import encodings.aliases
    import pkgutil

    names = set(encodings.aliases.aliases)
    names |= set(encodings.aliases.aliases.values())
    for module in pkgutil.iter_modules(encodings.__path__):
        names.add(module.name)
    names |= {
        "mac-bogus", "shift_jis_typo", "big5-nope", "ibm99999",
        "windows-936", "cp54936", "54936", "hzgb2312", "cn-gb", "gb-2312",
        "utf8-sig", "utf-8.unix", "latin-2", "latin_2", "iso_646_us",
        "jisx0208", "x_mac_cyrillic", "pt_154", "cshproman8", "macos", "macx",
        "ansi-x3.4-1968", "iso-2022-jp-2004", "utf-8-ucs2", "utf8-sig",
    }
    return sorted(names)


class TestCodecAliasCoverage(unittest.TestCase):
    """Every alias the interpreter has, compiled and detected, compared.

    The detector's name tables are data, and data drifts: a stdlib release can
    add an alias, and a table built by hand can quietly stop matching it. This
    walks encodings.aliases instead of a fixed list, so the only way to pass is
    to agree with the interpreter that is actually running.

    The comparison is one-directional on purpose. It asks whether the detector
    fails exactly when CPython fails, not which of several reasons was used --
    the reason codes have their own tests.
    """

    def test_every_alias_agrees_with_the_interpreter(self):
        names = alias_spellings()
        with tempfile.TemporaryDirectory() as tmp:
            cases = []
            for index, name in enumerate(names):
                path = pathlib.Path(tmp) / ("alias-%03d.py" % index)
                path.write_bytes(("# coding: %s\ns = 'A'\n" % name).encode("ascii"))
                cases.append((name, path))

            interpreter_ok = {}
            for name, path in cases:
                data = path.read_bytes()
                try:
                    compile(data, str(path), "exec")
                    interpreter_ok[name] = True
                except SyntaxError:
                    interpreter_ok[name] = False
                except Exception as error:          # noqa: BLE001
                    # A codec that raises something else is still a refusal.
                    interpreter_ok[name] = False
                    if name in ("utf-8", "ascii", "gbk"):
                        self.fail("%s raised %r" % (name, error))

            result = run_detector_over_many([path for _, path in cases])
            # Exit 0 or 1 both mean "every file was inspected": the batch exit
            # code rolls the per-file verdicts up, and a corpus this wide is
            # bound to contain warnings. Exit 2 (all files failed) or 3 (tool
            # error) would mean the run never got to the comparison.
            self.assertIn(result.returncode, (0, 1),
                          "batch detection exited %d: %s"
                          % (result.returncode, decode_console_output(result.stdout)[-800:]))
            document = json.loads(decode_console_output(result.stdout))
            by_path = {item["Path"]: item for item in document["Files"]}

            disagreements = []
            for name, path in cases:
                item = by_path.get(str(path))
                self.assertIsNotNone(item, "no result for %s" % name)
                detector_fails = item["Verdict"] == "FAIL"
                if detector_fails == interpreter_ok[name]:
                    disagreements.append(
                        (name, interpreter_ok[name], item["Verdict"],
                         item.get("SourceCodingSupport", "")))

            usable = sum(1 for ok in interpreter_ok.values() if ok)
            print("\n[codec-alias] python=%s checked=%d usable_as_source=%d "
                  "refused=%d disagreements=%d"
                  % (sys.version.split()[0], len(cases), usable,
                     len(cases) - usable, len(disagreements)))
            for row in disagreements[:20]:
                print("  disagree: %r" % (row,))
            self.assertEqual(disagreements, [],
                             "detector and interpreter disagree on %d names"
                             % len(disagreements))

    def test_the_utf8_and_latin1_families_are_not_table_lookups(self):
        """The two families are rewritten by the tokenizer, not resolved.

        Every "utf-8-" spelling compiles even though lookup rejects the long
        form, and every "latin-1-" spelling does the same. A detector that
        looked those up as ordinary names would fail both families.
        """
        cases = [b"utf-8-unix", b"utf-8-bogus", b"iso-latin-1", b"latin-1-x",
                 b"iso-8859-1-x"]
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index, name in enumerate(cases):
                path = pathlib.Path(tmp) / ("family-%02d.py" % index)
                path.write_bytes(b"# coding: " + name + b"\ns = 'A'\n")
                paths.append(path)
                compile(path.read_bytes(), str(path), "exec")

            result = run_detector_over_many(paths)
            document = json.loads(decode_console_output(result.stdout))
            for item in document["Files"]:
                name = pathlib.Path(item["Path"]).read_bytes().split(b"\n")[0]
                with self.subTest(name=name):
                    self.assertEqual(item["Verdict"], "OK", (name, item["Reasons"]))
                    self.assertEqual(item["SourceCodingSupport"], "supported")


class TestPythonOnlyPayload(unittest.TestCase):
    """A resolved name is not a verified payload.

    shift_jis, big5 and cp1252 are codecs CPython decodes with, and the detector
    has no table for any of them. A truncated multi-byte character in one of
    those files is invisible to this tool, so it must say "unverified" and not
    guess. That means the same answer for the complete character and for the
    truncated one -- which is the point, not an oversight.
    """

    CASES = (
        # file, codec, what the byte sequence is, what CPython does with it
        ("py-coding-shift-jis-bytes.py", "shift_jis", "complete character", 0),
        ("py-coding-shift-jis-truncated.py", "shift_jis", "lead byte only", 1),
        ("py-coding-big5-bytes.py", "big5", "complete character", 0),
        ("py-coding-big5-truncated.py", "big5", "lead byte only", 1),
        ("py-coding-cp1252-bytes.py", "cp1252", "assigned slots", 0),
        # 0x81 has no mapping in cp1252 and the byte sits on the second line,
        # so CPython refuses it while looking for the coding spec and reports
        # "encoding problem: cp1252" rather than a body decode error. Either
        # way the file does not run, and the detector still cannot see why.
        ("py-coding-cp1252-undefined.py", "cp1252", "0x81, unassigned", 1),
    )

    def test_the_payload_is_reported_unverified_in_both_outputs(self):
        fixtures = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "data"
        for name, codec, label, interpreter_rc in self.CASES:
            with self.subTest(file=name, codec=codec, payload=label):
                path = fixtures / name
                self.assertTrue(path.exists(), path)

                text = ps_tool("Test-ScriptEncoding.ps1",
                               ["-Path", str(path), "-Profile", "python"])
                self.assertEqual(text.returncode, 1, decode_console_output(text.stdout)[-500:])
                body = decode_console_output(text.stdout)
                self.assertIn("VERDICT=WARN", body)
                self.assertIn("SOURCE_CODING_SUPPORT=python-only", body)
                self.assertIn("SOURCE_CODING_PAYLOAD=unverified", body)
                self.assertIn("PY_SOURCE_CODING_UNVERIFIED", body)
                self.assertNotIn("the file runs", body)

                jsonr = ps_tool("Test-ScriptEncoding.ps1",
                                ["-Path", str(path), "-Profile", "python",
                                 "-Output", "json"])
                document = json.loads(decode_console_output(jsonr.stdout))
                item = document["Files"][0]
                self.assertEqual(item["Verdict"], "WARN")
                self.assertEqual(item["SourceCodingSupport"], "python-only")
                self.assertEqual(item["SourceCodingPayload"], "unverified")

                # The interpreter's own answer is measured, not assumed: the
                # complete characters run and the damaged ones do not. The
                # detector says unverified either way, which is why it must not
                # be compared against this value.
                run = run_python_fixture(path)
                self.assertEqual(run.returncode, interpreter_rc,
                                 (name, run.stderr[:300]))

    def test_ansi_is_the_console_code_page_and_not_ascii(self):
        """'ansi' resolves to mbcs; 'ansi_x3.4-1968' and 'ansi-x3.4-1968' to ascii.

        Three spellings, two codecs, and they look like one family. Folding them
        together is invisible to the name corpus, whose bodies are ASCII: the
        difference only shows when the payload leaves ascii. Here it does -- the
        same GBK bytes under all three declarations. A table that called 'ansi'
        ascii would fail a file the interpreter runs; a table that called the
        ascii aliases mbcs would pass two files that never compile.
        """
        payload = "中文".encode("gbk")
        cases = (
            ("ansi", "python-only"),
            ("ansi_x3.4-1968", "supported"),
            ("ansi-x3.4-1968", "supported"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for index, (name, support) in enumerate(cases):
                with self.subTest(name=name):
                    path = pathlib.Path(tmp) / ("ansi-%02d.py" % index)
                    path.write_bytes(("# coding: %s\ns = \"" % name).encode("ascii")
                                     + payload + b"\"\n")
                    document = json.loads(decode_console_output(
                        ps_tool("Test-ScriptEncoding.ps1",
                                ["-Path", str(path), "-Profile", "python",
                                 "-Output", "json"]).stdout))
                    item = document["Files"][0]
                    self.assertEqual(item["SourceCodingSupport"], support, name)
                    run = run_python_fixture(path)
                    if support == "python-only":
                        # mbcs decodes whatever the ANSI code page says, so the
                        # interpreter's answer is host dependent -- 936 here,
                        # 1252 on a hosted runner. The invariant that holds
                        # everywhere is that the detector never fails the name.
                        self.assertEqual(item["Verdict"], "WARN", name)
                        self.assertEqual(item["SourceCodingPayload"], "unverified")
                    else:
                        self.assertEqual(item["Verdict"], "FAIL", name)
                        self.assertNotEqual(run.returncode, 0, name)

    def test_the_payload_key_is_absent_when_the_question_does_not_apply(self):
        fixtures = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "data"
        for name in ("py-coding-gbk.py", "py-coding-utf8-sig.py", "py-coding-54936.py"):
            with self.subTest(file=name):
                path = fixtures / name
                jsonr = ps_tool("Test-ScriptEncoding.ps1",
                                ["-Path", str(path), "-Profile", "python", "-Output", "json"])
                item = json.loads(decode_console_output(jsonr.stdout))["Files"][0]
                self.assertNotIn("SourceCodingPayload", item,
                                 "%s should not carry a payload state" % name)

                text = ps_tool("Test-ScriptEncoding.ps1",
                               ["-Path", str(path), "-Profile", "python"])
                self.assertNotIn("SOURCE_CODING_PAYLOAD",
                                 decode_console_output(text.stdout))


class TestGbkGrid(unittest.TestCase):
    """The GBK table against CPython's own codec.

    Windows code page 936 is not GBK: it maps 2149 cells that CPython rejects
    onto private use characters, plus 0x80 and 0xFF. The detector carries the
    grid itself now, and this is the check that notices when it drifts.
    """

    @staticmethod
    def _cells():
        accepted = []
        holes = {}
        trails = list(range(0x40, 0x7F)) + list(range(0x80, 0xFF))
        for lead in range(0x81, 0xFF):
            for trail in trails:
                pair = bytes((lead, trail))
                try:
                    text = pair.decode("gbk")
                    same = text.encode("gbk") == pair
                except UnicodeDecodeError:
                    same = False
                if same:
                    accepted.append(pair)
                else:
                    holes.setdefault(lead, []).append(pair)
        return accepted, holes

    def test_every_cell_python_accepts_is_accepted(self):
        accepted, holes = self._cells()
        # 21791 on CPython 3.13; the bound keeps the test meaningful without
        # pretending the number is frozen.
        self.assertGreater(len(accepted), 21000)
        self.assertGreater(len(holes), 20)

        lines = [b"# -*- coding: gbk -*-"]
        for index in range(0, len(accepted), 60):
            chunk = b"".join(accepted[index:index + 60])
            lines.append(b'MARKER_%d = "' % (index // 60) + chunk + b'"')
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "gbk-grid-all.py"
            path.write_bytes(b"\n".join(lines) + b"\n")
            run = run_python_fixture(path)
            self.assertEqual(run.returncode, 0, run.stderr[:400])
            t = ps_tool("Test-ScriptEncoding.ps1", ["-Path", str(path), "-Profile", "python"])
            self.assertEqual(t.returncode, 1, t.stdout[-800:])
            self.assertNotIn(b"PY_SOURCE_CODING_INVALID_BYTES", t.stdout)

    def test_the_holes_are_refused(self):
        # One cell per lead with a gap: enough to pin the shape of every rule in
        # the table without one process per hole.
        _, holes = self._cells()
        with tempfile.TemporaryDirectory() as tmp:
            for lead in sorted(holes):
                pair = holes[lead][0]
                with self.subTest(lead="%02X" % lead, cell=pair.hex()):
                    path = pathlib.Path(tmp) / ("hole-%02x.py" % lead)
                    path.write_bytes(b"# -*- coding: gbk -*-\nMARKER = \"" + pair + b"\"\n")
                    run = run_python_fixture(path)
                    self.assertNotEqual(run.returncode, 0)
                    t = ps_tool("Test-ScriptEncoding.ps1",
                                ["-Path", str(path), "-Profile", "python"])
                    self.assertEqual(t.returncode, 2, (pair.hex(), t.stdout[-500:]))

    def test_the_two_single_byte_holes_are_refused(self):
        # 0x80 and 0xFF are errors in CPython's gbk and map to a euro sign and
        # U+F8F5 in code page 936.
        with tempfile.TemporaryDirectory() as tmp:
            for byte in (0x80, 0xFF):
                with self.subTest(byte="%02X" % byte):
                    for pair in (bytes((byte,)), bytes((0x41, byte, 0x42))):
                        try:
                            pair.decode("gbk")
                            self.fail("CPython accepted %s" % pair.hex())
                        except UnicodeDecodeError:
                            pass
                    path = pathlib.Path(tmp) / ("single-%02x.py" % byte)
                    path.write_bytes(b"# -*- coding: gbk -*-\nMARKER = \""
                                     + bytes((byte,)) + b"\"\n")
                    t = ps_tool("Test-ScriptEncoding.ps1",
                                ["-Path", str(path), "-Profile", "python"])
                    self.assertEqual(t.returncode, 2, (byte, t.stdout[-500:]))


class TestCodecAliases(unittest.TestCase):
    """The alias table against codecs.lookup(), name by name.

    The names are the only part of this feature that is data rather than logic,
    which makes them the part most likely to drift. Every alias is written into
    a real source file with a body it can legally describe, and the detector's
    canonical name is compared with the one CPython resolves. Names Python does
    not know have to come back as failures rather than as a guess.
    """

    FAMILIES = (
        # canonical, aliases, body the declaration can legally describe
        ("gbk", ("gbk", "cp936", "ms936", "936"), b'MARKER = "' + ZH.encode("gb2312") + b'"\n'),
        ("gb2312", ("gb2312", "euc-cn", "euccn", "gb2312-80", "iso-ir-58", "chinese"),
         b'MARKER = "' + ZH.encode("gb2312") + b'"\n'),
        ("hz", ("hz", "hzgb", "hz-gb-2312", "hz_gb_2312"), b'MARKER = "~{VPND~}"\n'),
        ("gb18030", ("gb18030", "gb18030-2000"),
         b'MARKER = "' + ZH.encode("gb18030") + "\U00010000".encode("gb18030") + b'"\n'),
    )

    # Plausible names that are not aliases. Both look like the code page they
    # belong to; Python raises LookupError before reading the file.
    REJECTED = ("windows-936", "cp54936", "54936", "hzgb2312", "cn-gb")

    PROBE = (
        "import codecs, json, sys\n"
        "out = {}\n"
        "for name in json.loads(sys.argv[1]):\n"
        "    try:\n"
        "        out[name] = codecs.lookup(name).name\n"
        "    except LookupError:\n"
        "        out[name] = None\n"
        "print(json.dumps(out))\n"
    )

    def test_the_detector_agrees_with_codecs_lookup(self):
        cases = []
        for canonical, aliases, body in self.FAMILIES:
            for alias in aliases:
                cases.append((alias, canonical, body))
        for alias in self.REJECTED:
            cases.append((alias, None, b'MARKER = "x"\n'))

        names = [alias for alias, _, _ in cases]
        probe = subprocess.run(
            [sys.executable, "-c", self.PROBE, json.dumps(names)],
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        resolved = json.loads(probe.stdout.decode("utf-8"))

        # Every name Python refuses must be in REJECTED, and every name it
        # resolves must map to the family this test claims it maps to.
        for alias, canonical, _ in cases:
            with self.subTest(alias=alias, stage="codecs.lookup"):
                if canonical is None:
                    self.assertIsNone(resolved[alias], alias)
                else:
                    self.assertEqual(resolved[alias], canonical, alias)

        # One file per run: -Path takes an array, but -File does not split a
        # comma separated string into one, so a single call would inspect a path
        # with commas in it and report NOT_FOUND for all of them.
        with tempfile.TemporaryDirectory() as tmp:
            for index, (alias, canonical, body) in enumerate(cases):
                path = pathlib.Path(tmp) / ("alias-%02d.py" % index)
                path.write_bytes(b"# -*- coding: " + alias.encode("ascii") + b" -*-\n" + body)

                t = ps_tool(
                    "Test-ScriptEncoding.ps1",
                    ["-Path", str(path), "-Profile", "python", "-Output", "json"],
                )
                with self.subTest(alias=alias, stage="detector"):
                    document = json.loads(t.stdout.decode("utf-8"))
                    self.assertEqual(len(document["Files"]), 1, t.stderr)
                    item = document["Files"][0]
                    if canonical is None:
                        self.assertEqual(item["Verdict"], "FAIL", alias)
                        self.assertIn("PY_SOURCE_CODING_UNKNOWN", " ".join(item["Reasons"]))
                        self.assertEqual(item["SourceCodingKind"], "unknown-name")
                    else:
                        self.assertEqual(item["Verdict"], "WARN", alias)
                        self.assertEqual(item["SourceCodingName"], canonical, alias)


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
