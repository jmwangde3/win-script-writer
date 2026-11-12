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
        self.assertFalse(run_ps.needs_file_fallback(run_ps.MAX_COMMAND_LINE_CHARS))
        self.assertTrue(run_ps.needs_file_fallback(run_ps.MAX_COMMAND_LINE_CHARS + 1))


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
        # The payload has to be large while the *invocation* stays short, so the
        # script comes from a file: a 40000 character --command would exceed the
        # Windows command line limit before run_ps.py ever started.
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "long.ps1"
            filler = "\n".join("# padding line %d" % i for i in range(2200))
            path.write_text(filler + '\nWrite-Output "long-ok"\n', encoding="utf-8")
            self.assertGreater(path.stat().st_size, 32000)
            r = invoke(["--file", str(path)])
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

    def test_prelude_does_not_displace_a_param_block(self):
        # param() and [CmdletBinding()] are only legal as the first statement of
        # a script or script block. Concatenating the prelude in front of them
        # used to make PowerShell report "param is not recognized", run the rest
        # of the script anyway, and still exit 0.
        with tempfile.TemporaryDirectory() as tmp:
            script = pathlib.Path(tmp) / "params.ps1"
            script.write_text(
                "[CmdletBinding()]\n"
                "param([int]$Value = 7)\n"
                'Write-Output ("VALUE=" + $Value)\n',
                encoding="utf-8",
            )
            plain = invoke(["--file", str(script)])
            self.assertEqual(plain.returncode, 0, plain.stderr)
            self.assertIn(b"VALUE=7", plain.stdout)

            with_prelude = invoke(["--console-encoding", "utf8", "--file", str(script)])
            self.assertEqual(with_prelude.returncode, 0, with_prelude.stderr)
            self.assertIn(b"VALUE=7", with_prelude.stdout)
            self.assertNotIn(b"is not recognized", with_prelude.stderr)

    def test_prelude_still_applies_inside_the_wrapper(self):
        # The wrapper must not put the prelude out of scope: the script inside it
        # still has to see the encodings the flag asked for.
        r = invoke(["--console-encoding", "utf8",
                    'Write-Output $OutputEncoding.WebName; Write-Output ([Console]::OutputEncoding.CodePage)'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"utf-8", r.stdout)
        self.assertIn(b"65001", r.stdout)

    def test_wrapper_survives_a_trailing_comment(self):
        # Without the newline before the closing brace the comment would swallow
        # the brace and the payload would not parse.
        r = invoke(["--console-encoding", "utf8", 'Write-Output "OK" # trailing comment'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"OK", r.stdout)

    def test_no_temp_script_is_left_behind(self):
        pattern = "ws-run-ps-"
        before = {p.name for p in pathlib.Path(tempfile.gettempdir()).iterdir() if pattern in p.name}
        invoke(['Write-Output "clean"'])
        after = {p.name for p in pathlib.Path(tempfile.gettempdir()).iterdir() if pattern in p.name}
        self.assertEqual(before - after, set())


CONTEXT_PROBE = (
    'Write-Output ("ROOT=[" + $PSScriptRoot + "]")\n'
    'Write-Output ("CMD=[" + $PSCommandPath + "]")\n'
    'Write-Output ("MINE=[" + $MyInvocation.MyCommand.Path + "]")\n'
)


def field(stdout, key):
    for line in stdout.decode("utf-8", "replace").splitlines():
        if line.startswith(key + "=["):
            return line[len(key) + 2:-1]
    return None


class TestTextModeHasNoFileContext(unittest.TestCase):
    """Pins the documented difference instead of pretending it is not there."""

    def test_file_flag_leaves_the_context_variables_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = pathlib.Path(tmp) / "probe.ps1"
            script.write_text(CONTEXT_PROBE, encoding="utf-8")
            r = invoke(["--file", str(script)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(field(r.stdout, "ROOT"), "")
        self.assertEqual(field(r.stdout, "CMD"), "")
        self.assertEqual(field(r.stdout, "MINE"), "")

    def test_a_long_payload_changes_the_context_and_says_so(self):
        # The same script, past the command line limit, is staged as a file and
        # therefore sees a temp directory as $PSScriptRoot. The behaviour is
        # different, so it must be announced rather than discovered.
        with tempfile.TemporaryDirectory() as tmp:
            script = pathlib.Path(tmp) / "long.ps1"
            filler = "\n".join("# padding line %d" % i for i in range(2200))
            script.write_text(filler + "\n" + CONTEXT_PROBE, encoding="utf-8")
            r = invoke(["--file", str(script)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ws-run-ps-", field(r.stdout, "ROOT") or "")
        self.assertIn(b"exceeded the command line limit", r.stderr)
        self.assertIn(b"--invoke-file", r.stderr)

    def test_a_short_payload_prints_no_note(self):
        r = invoke(['Write-Output "short"'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(b"exceeded the command line limit", r.stderr)


class TestInvokeFile(unittest.TestCase):
    """--invoke-file must reproduce the child's own -File semantics."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.folder = self.root / (ZH + "_dir")
        self.folder.mkdir()
        self.script = self.folder / (CESHI + ".ps1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_keeps_script_root_and_command_path(self):
        self.script.write_text(CONTEXT_PROBE, encoding="utf-8")
        r = invoke(["--invoke-file", str(self.script)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(field(r.stdout, "ROOT"), str(self.folder))
        self.assertEqual(field(r.stdout, "CMD"), str(self.script))
        self.assertEqual(field(r.stdout, "MINE"), str(self.script))

    def test_relative_dot_sourcing_resolves_next_to_the_script(self):
        (self.folder / "helper.ps1").write_text(
            "function Get-HelperValue { return 'from-helper' }\n", encoding="utf-8"
        )
        self.script.write_text(
            '. "$PSScriptRoot\\helper.ps1"\nWrite-Output ("HELPER=" + (Get-HelperValue))\n',
            encoding="utf-8",
        )
        r = invoke(["--invoke-file", str(self.script)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"HELPER=from-helper", r.stdout)

    def test_param_block_keeps_its_default(self):
        self.script.write_text(
            "[CmdletBinding()]\nparam([int]$Value = 7)\nWrite-Output (\"VALUE=\" + $Value)\n",
            encoding="utf-8",
        )
        r = invoke(["--invoke-file", str(self.script)])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"VALUE=7", r.stdout)

    def test_script_args_reach_the_param_block(self):
        self.script.write_text(
            "[CmdletBinding()]\nparam([int]$Value = 7)\nWrite-Output (\"VALUE=\" + $Value)\n",
            encoding="utf-8",
        )
        r = invoke(["--invoke-file", str(self.script), "--script-args", "-Value", "11"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"VALUE=11", r.stdout)

    def test_exit_code_is_propagated(self):
        self.script.write_text("exit 9\n", encoding="utf-8")
        self.assertEqual(invoke(["--invoke-file", str(self.script)]).returncode, 9)

    def test_native_command_failure_sets_a_non_zero_code(self):
        self.script.write_text(
            "cmd /c exit 4\nWrite-Output (\"LASTEXITCODE=\" + $LASTEXITCODE)\nexit $LASTEXITCODE\n",
            encoding="utf-8",
        )
        r = invoke(["--invoke-file", str(self.script)])
        self.assertEqual(r.returncode, 4, r.stdout)
        self.assertIn(b"LASTEXITCODE=4", r.stdout)

    def test_missing_file_returns_3(self):
        r = invoke(["--invoke-file", str(self.root / "nope.ps1")])
        self.assertEqual(r.returncode, 3)
        self.assertIn(b"not found", r.stderr.lower())

    def test_no_execution_policy_is_injected_by_default(self):
        self.script.write_text('Write-Output "ok"\n', encoding="utf-8")
        captured = {}
        original = run_ps.spawn

        def spy(exe, argv, timeout):
            captured["argv"] = list(argv)
            return original(exe, argv, timeout)

        run_ps.spawn = spy
        try:
            code, _, _ = run_ps.run_file(str(self.script))
        finally:
            run_ps.spawn = original
        self.assertEqual(code, 0)
        self.assertNotIn("-ExecutionPolicy", captured["argv"])
        self.assertEqual(captured["argv"][-2], "-File")

    def test_a_restrictive_policy_fails_instead_of_being_bypassed(self):
        self.script.write_text('Write-Output "should-not-run"\n', encoding="utf-8")
        r = invoke(["--invoke-file", str(self.script), "--execution-policy", "Restricted"])
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn(b"should-not-run", r.stdout)
        self.assertTrue(
            b"cannot be loaded" in r.stderr or b"disabled" in r.stderr,
            r.stderr,
        )

    def test_incompatible_flags_are_rejected_not_ignored(self):
        self.script.write_text('Write-Output "x"\n', encoding="utf-8")
        cases = [
            ["--console-encoding", "utf8"],
            ["--input-encoding", "gbk"],
            ["--command", "Write-Output 1"],
            ["--file", str(self.script)],
            ["--stdin"],
        ]
        for extra in cases:
            r = invoke(["--invoke-file", str(self.script)] + extra)
            self.assertEqual(r.returncode, 3, extra)
            self.assertIn(b"cannot honour", r.stderr, extra)

    def test_script_args_without_invoke_file_is_rejected(self):
        r = invoke(["--command", "Write-Output 1", "--script-args", "--nope"])
        self.assertEqual(r.returncode, 3)
        self.assertIn(b"only valid with --invoke-file", r.stderr)

    def test_usage_error_returns_3_not_argparse_2(self):
        r = invoke(["--bogus-flag"])
        self.assertEqual(r.returncode, 3)


class TestStagingFailures(unittest.TestCase):
    """The staging path must fail with 3, never with a traceback."""

    def test_temp_directory_failure_returns_3(self):
        import unittest.mock

        with unittest.mock.patch.object(
            run_ps.tempfile, "mkdtemp", side_effect=OSError("no space")
        ):
            code, out, err = run_ps.run("x" * 40000)
        self.assertEqual(code, 3)
        self.assertEqual(out, b"")
        self.assertIn(b"cannot stage the script", err)

    def test_cleanup_failure_does_not_replace_the_exit_code(self):
        import unittest.mock

        real_mkdtemp = run_ps.tempfile.mkdtemp
        with unittest.mock.patch.object(run_ps.tempfile, "mkdtemp", real_mkdtemp):
            with unittest.mock.patch.object(
                run_ps.shutil, "rmtree", side_effect=OSError("locked")
            ):
                code, out, err = run_ps.run('Write-Output "cleanup"')
        self.assertEqual(code, 0, err)
        self.assertIn(b"cleanup", out)

    def test_missing_shell_returns_127(self):
        import unittest.mock

        with unittest.mock.patch.object(run_ps, "resolve_shell", return_value=None):
            code, out, err = run_ps.run('Write-Output "x"')
            code_file, _, err_file = run_ps.run_file("whatever.ps1")
        self.assertEqual(code, 127)
        self.assertEqual(code_file, 127)
        self.assertIn(b"not found", err)
        self.assertIn(b"not found", err_file)


if __name__ == "__main__":
    unittest.main(verbosity=2)
