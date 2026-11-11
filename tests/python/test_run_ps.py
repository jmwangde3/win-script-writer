# -*- coding: utf-8 -*-
"""Contract tests for scripts/run_ps.py.

Run with:
    python -m unittest discover -s tests/python -v

Every test spawns the real script through subprocess so that argv handling,
stream handling and exit codes are exercised end to end.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "run_ps.py"

_spec = importlib.util.spec_from_file_location("run_ps_under_test", SCRIPT)
run_ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_ps)

ZH = "\u4e2d\u6587"          # zhongwen
CESHI = "\u6d4b\u8bd5"       # ceshi


def invoke(args, stdin_bytes=None, timeout=180):
    kwargs = dict(
        capture_output=True,
        timeout=timeout,
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    if stdin_bytes is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin_bytes
    return subprocess.run([sys.executable, str(SCRIPT)] + list(args), **kwargs)


class TestArgvConstruction(unittest.TestCase):
    """Pure unit tests: no child process involved."""

    def test_execution_policy_is_not_added_by_default(self):
        argv = run_ps.build_argv("powershell.exe", encoded="AAAA")
        self.assertNotIn("-ExecutionPolicy", argv)

    def test_execution_policy_is_added_on_request(self):
        argv = run_ps.build_argv("powershell.exe", encoded="AAAA", execution_policy="RemoteSigned")
        idx = argv.index("-ExecutionPolicy")
        self.assertEqual(argv[idx + 1], "RemoteSigned")

    def test_no_profile_and_non_interactive_are_always_present(self):
        argv = run_ps.build_argv("powershell.exe", encoded="AAAA")
        self.assertIn("-NoProfile", argv)
        self.assertIn("-NonInteractive", argv)

    def test_source_never_uses_shell_true(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("shell=True", text)

    def test_prelude_is_empty_by_default(self):
        self.assertEqual(run_ps.build_prelude(None), "")
        self.assertEqual(run_ps.build_prelude("none"), "")

    def test_prelude_can_opt_into_utf8_console(self):
        prelude = run_ps.build_prelude("utf8")
        self.assertIn("[Console]::OutputEncoding", prelude)

    def test_long_payload_is_detected(self):
        self.assertFalse(run_ps.needs_file_fallback(100))
        self.assertTrue(run_ps.needs_file_fallback(run_ps.MAX_COMMAND_LINE_CHARS))


class TestExecution(unittest.TestCase):
    def test_positional_command_still_works(self):
        r = invoke(['Write-Output "legacy-ok"'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"legacy-ok", r.stdout)

    def test_command_flag(self):
        r = invoke(["--command", 'Write-Output "flag-ok"'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"flag-ok", r.stdout)

    def test_stdin_dash(self):
        payload = ('Write-Output "' + ZH + '"').encode("utf-8")
        r = invoke(["-", "--console-encoding", "utf8"], stdin_bytes=payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(ZH.encode("utf-8"), r.stdout)

    def test_stdin_flag(self):
        payload = ('Write-Output "' + CESHI + '"').encode("utf-8")
        r = invoke(["--stdin", "--console-encoding", "utf8"], stdin_bytes=payload)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(CESHI.encode("utf-8"), r.stdout)

    def test_file_flag_reads_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "script.ps1"
            path.write_bytes(b"\xef\xbb\xbf" + ('Write-Output "' + ZH + '"').encode("utf-8"))
            r = invoke(["--file", str(path), "--console-encoding", "utf8"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(ZH.encode("utf-8"), r.stdout)

    def test_file_flag_reads_gbk_when_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "gbk.ps1"
            path.write_bytes(('Write-Output "' + ZH + '"').encode("gbk"))
            r = invoke(["--file", str(path), "--input-encoding", "gbk", "--console-encoding", "utf8"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(ZH.encode("utf-8"), r.stdout)

    def test_long_command_falls_back_to_a_temp_script(self):
        filler = "\n".join("# padding line %d" % i for i in range(1200))
        script = filler + '\nWrite-Output "long-ok"\n'
        self.assertGreater(len(script), 32000)
        r = invoke(["--command", script])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"long-ok", r.stdout)

    def test_chinese_path_with_nested_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp) / (ZH + "_dir")
            folder.mkdir()
            (folder / "marker.txt").write_text("x", encoding="utf-8")
            script = 'Get-ChildItem -LiteralPath "%s" -Name | Select-Object -First 1' % folder
            r = invoke(["--command", script, "--console-encoding", "utf8"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(b"marker.txt", r.stdout)

    def test_pwsh_shell(self):
        r = invoke(["--shell", "pwsh", "--command", "$PSVersionTable.PSEdition"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"Core", r.stdout)

    def test_exit_code_is_propagated(self):
        r = invoke(["exit 7"])
        self.assertEqual(r.returncode, 7)

    def test_timeout_returns_124(self):
        start = time.time()
        r = invoke(["--timeout", "1", "Start-Sleep -Seconds 30"], timeout=60)
        elapsed = time.time() - start
        self.assertEqual(r.returncode, 124)
        self.assertLess(elapsed, 20)

    def test_missing_file_returns_3(self):
        r = invoke(["--file", str(pathlib.Path(tempfile.gettempdir()) / "no-such-file-xyz.ps1")])
        self.assertEqual(r.returncode, 3)
        self.assertIn(b"not found", r.stderr.lower())

    def test_undecodable_stdin_returns_3(self):
        r = invoke(["-", "--input-encoding", "utf-8"], stdin_bytes=b"\xff\xfe\xff")
        self.assertEqual(r.returncode, 3)

    def test_empty_input_returns_3(self):
        r = invoke(["-"], stdin_bytes=b"")
        self.assertEqual(r.returncode, 3)

    def test_version(self):
        r = invoke(["--version"])
        self.assertEqual(r.returncode, 0)
        self.assertIn(run_ps.__version__.encode("ascii"), r.stdout)

    def test_help(self):
        r = invoke(["--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn(b"--timeout", r.stdout)

    def test_console_encoding_is_left_alone_by_default(self):
        # Without --console-encoding the tool must not inject a prelude that
        # rewrites [Console]::OutputEncoding: the child value has to match a
        # bare PowerShell invocation exactly.
        exe = run_ps.resolve_shell("powershell")
        direct = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding.CodePage"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
        )
        r = invoke(['[Console]::OutputEncoding.CodePage'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), direct.stdout.strip())

    def test_console_encoding_utf8_is_opt_in(self):
        r = invoke(["--console-encoding", "utf8", '[Console]::OutputEncoding.CodePage'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"65001", r.stdout)

    def test_no_temp_script_is_left_behind(self):
        pattern = "ws-run-ps-"
        before = {p.name for p in pathlib.Path(tempfile.gettempdir()).iterdir() if pattern in p.name}
        invoke(['Write-Output "clean"'])
        after = {p.name for p in pathlib.Path(tempfile.gettempdir()).iterdir() if pattern in p.name}
        self.assertEqual(before - after, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
