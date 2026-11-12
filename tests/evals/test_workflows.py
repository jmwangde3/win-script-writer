# -*- coding: utf-8 -*-
"""Structural checks for the GitHub Actions workflows.

The first push of this repository failed in zero seconds with

    Invalid workflow file: .github/workflows/test.yml#L1
    (Line: 49, Col: 16): Unrecognized named-value: 'matrix'.
    Located at position 1 within expression: matrix.shell

GitHub resolves `jobs.<id>.steps[*].shell` before it expands the matrix, so the
key accepts literals only. Nothing in the local suite could have caught that:
`python -m unittest` never parses YAML, and a hand-run `run-all.ps1` does not
care how CI wires its shells. The cost of the gap was a red build on the very
first push, so the rule that was learned the hard way is now a test.

These checks are deliberately about shape, not behaviour. Whether the tests
inside a job pass is the job's business; this file only asserts that the
workflow will be accepted by the validator and that it wires the matrix the
way the repository claims.

Run with:
    python -m unittest discover -s tests/evals -v
"""

from __future__ import annotations

import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

try:
    import yaml
except ImportError as exc:  # pragma: no cover - the docs job installs it
    raise SystemExit(
        "PyYAML is required for the workflow contract tests: pip install pyyaml"
    ) from exc


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def steps_of(document):
    """Yield (job_id, step) for every step in every job."""
    for job_id, job in (document.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            yield job_id, step


def triggers_of(document):
    # PyYAML reads a bare `on:` key as the boolean True (YAML 1.1), so both
    # spellings have to be looked up.
    return document.get("on") or document.get(True)


class TestWorkflowFilesParse(unittest.TestCase):
    def test_all_three_workflows_exist(self):
        found = sorted(p.name for p in WORKFLOWS.glob("*.yml"))
        self.assertEqual(found, ["cp936.yml", "release.yml", "test.yml"])

    def test_every_workflow_parses_and_names_itself(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=path.name):
                document = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(document, dict)
                self.assertIn("jobs", document)
                # A workflow whose `name` GitHub falls back to the file path has
                # failed to parse. That fallback is the symptom that started
                # this file, so assert the name is a real one.
                self.assertTrue(document.get("name"), path.name)
                self.assertNotIn("/", document["name"])


class TestStepShape(unittest.TestCase):
    def test_every_step_runs_something(self):
        for name in ("test.yml", "cp936.yml", "release.yml"):
            for job_id, step in steps_of(load(name)):
                with self.subTest(workflow=name, job=job_id, step=step.get("name")):
                    self.assertTrue(
                        step.get("uses") or step.get("run"),
                        "a step with neither `uses` nor `run` is rejected",
                    )

    def test_shell_is_never_an_expression(self):
        # This is the exact failure GitHub reported. `shell` is resolved before
        # the matrix expands, so `${{ matrix.shell }}` is an invalid named-value
        # there even though `run` and `name` accept the same expression.
        for name in ("test.yml", "cp936.yml", "release.yml"):
            for job_id, step in steps_of(load(name)):
                shell = step.get("shell")
                if not isinstance(shell, str):
                    continue
                with self.subTest(workflow=name, job=job_id, step=step.get("name")):
                    self.assertNotIn(
                        "${{",
                        shell,
                        "jobs.<id>.steps[*].shell accepts literals only; "
                        "give each edition its own job instead",
                    )
                    self.assertIn(
                        shell,
                        {"powershell", "pwsh", "cmd", "bash", "python"},
                        "unexpected shell literal",
                    )


class TestMatrixCoversBothEditions(unittest.TestCase):
    def test_test_workflow_has_one_job_per_edition(self):
        document = load("test.yml")
        jobs = document["jobs"]

        powershell_jobs = [
            job_id
            for job_id, job in jobs.items()
            if any(s.get("shell") == "powershell" for s in job.get("steps") or [])
        ]
        pwsh_jobs = [
            job_id
            for job_id, job in jobs.items()
            if any(s.get("shell") == "pwsh" for s in job.get("steps") or [])
        ]

        self.assertEqual(len(powershell_jobs), 1, "exactly one 5.1 job expected")
        self.assertEqual(len(pwsh_jobs), 1, "exactly one 7 job expected")

        for job_id in powershell_jobs + pwsh_jobs:
            runs = [
                s.get("run", "")
                for s in jobs[job_id].get("steps") or []
                if s.get("run")
            ]
            self.assertTrue(
                any("tests/run-all.ps1" in r for r in runs),
                "every edition job must run the whole matrix: %s" % job_id,
            )

    def test_each_edition_installs_its_own_modules(self):
        # `Install-Module -Scope CurrentUser` from pwsh 7 writes to
        # Documents/PowerShell/Modules. Windows PowerShell 5.1 searches only
        # Documents/WindowsPowerShell/Modules, so an install step that runs in
        # the other edition's shell silently leaves this job without Pester.
        #
        # cp936.yml is exempt on purpose: its runner requirements say the
        # modules are pre-installed for the runner account.
        for name in ("test.yml", "release.yml"):
            document = load(name)
            for job_id, job in (document.get("jobs") or {}).items():
                steps = job.get("steps") or []
                runs_matrix = any(
                    "tests/run-all.ps1" in (s.get("run") or "") for s in steps
                )
                if not runs_matrix:
                    continue

                # Every shell that actually executes the suite must also be the
                # shell that installed the modules for it.
                shells_used = {
                    s.get("shell")
                    for s in steps
                    if "tests/run-all.ps1" in (s.get("run") or "")
                }
                install_shells = {
                    s.get("shell")
                    for s in steps
                    if "Install-Module" in (s.get("run") or "")
                }
                with self.subTest(workflow=name, job=job_id):
                    self.assertTrue(
                        shells_used.issubset(install_shells),
                        "%s/%s runs the suite in %s but installs modules in %s"
                        % (name, job_id, sorted(shells_used), sorted(install_shells)),
                    )


class TestPythonUtf8Mode(unittest.TestCase):
    def test_one_job_forces_utf8_mode(self):
        # PEP 686 flips the interpreter default in Python 3.15. A job that forces
        # the mode on is the only thing between that change and a surprise, and a
        # job that is deleted in a refactor is invisible without this assertion.
        document = load("test.yml")
        candidates = [
            (job_id, job)
            for job_id, job in (document.get("jobs") or {}).items()
            if any((s.get("env") or {}).get("PYTHONUTF8") == "1" for s in job.get("steps") or [])
        ]
        self.assertEqual(len(candidates), 1, "exactly one job must force UTF-8 mode")
        job_id, job = candidates[0]
        runs = "\n".join(s.get("run") or "" for s in job["steps"])
        self.assertIn("tests/python", runs, job_id)
        self.assertIn("tests/integration", runs, job_id)

    def test_the_utf8_job_does_not_claim_to_run_python_315(self):
        # Honesty in the job name: forcing the mode is a preview, not a 3.15 run.
        document = load("test.yml")
        names = [job.get("name", "") for job in (document.get("jobs") or {}).values()]
        utf8_names = [n for n in names if "UTF-8" in n]
        self.assertEqual(len(utf8_names), 1, names)
        self.assertIn("preview", utf8_names[0].lower())


class TestReleaseWiring(unittest.TestCase):
    def test_release_runs_only_on_a_tag(self):
        document = load("release.yml")
        self.assertEqual(triggers_of(document), {"push": {"tags": ["v*"]}})

    def test_release_packages_with_the_shared_script(self):
        # Packaging logic lives in tests/package.ps1 so the code that runs on a
        # tag is the code that was exercised locally. Inlining it here would let
        # the two drift apart again.
        document = load("release.yml")
        runs = "\n".join(
            step.get("run", "") for _, step in steps_of(document)
        )
        self.assertIn("tests/package.ps1", runs)
        self.assertIn("gh", runs)
        self.assertIn("--notes-file", runs)

    def test_cp936_gate_fails_instead_of_skipping(self):
        document = load("cp936.yml")
        runs = "\n".join(
            step.get("run", "") for _, step in steps_of(document)
        )
        self.assertIn("ACP", runs)
        self.assertIn("throw", runs)
        self.assertIn("host ANSI code page is", runs)

    def test_cp936_gate_needs_the_self_hosted_labels(self):
        document = load("cp936.yml")
        job = document["jobs"]["gate"]
        self.assertEqual(job["runs-on"], ["self-hosted", "windows", "cp936"])

    def test_cp936_gate_is_gated_by_a_variable(self):
        # A job that asks for a label no runner has does not fail, it queues
        # indefinitely. The first `push: main` after the tag was pushed proved
        # it: the run sat in `queued` until it was cancelled by hand. The gate
        # now reports skipped until the repository variable says a runner
        # exists, so a missing runner is visible instead of silently pending.
        document = load("cp936.yml")
        job = document["jobs"]["gate"]
        self.assertIn("if", job, "the gate needs a variable switch")
        self.assertIn("vars.CP936_RUNNER", str(job["if"]))


    def test_release_step_does_not_poll_the_exit_code(self):
        # The packaging script throws on every failure path and leaves the
        # exit-code variable unset on success. A null-vs-zero comparison in the
        # workflow therefore failed a perfectly good package on the first
        # release attempt, one step before the archive was even uploaded.
        document = load("release.yml")
        offenders = []
        for _, step in steps_of(document):
            for line in (step.get("run") or "").splitlines():
                if "LASTEXITCODE" in line and "packaging failed" in line:
                    offenders.append(line.strip())
        self.assertEqual(offenders, [], "the release job fails a good package")


if __name__ == "__main__":
    unittest.main()
