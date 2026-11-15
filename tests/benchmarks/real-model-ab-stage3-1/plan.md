# Plan: stage 3.1 closeout

## Scope

| Priority | Work |
| --- | --- |
| P0 | correct the `tool-02` loads metadata and add a metadata contract test |
| P0 | expand BAT to A3/B3 and PS51 to A3/B3 |
| P1 | investigate the PS51 75/100 gap and decide on a documentation change |
| P1 | regression tests and release assessment |

Out of scope: rewriting `SKILL.md`, the parser or the test framework; new features;
re-running SAFETY; installing a VM or Windows Sandbox.

## Sample design

| Task | Existing (stage 3) | New | Total |
| --- | ---: | ---: | ---: |
| BAT | A1 / B1 | A2 / B2 | A3 / B3 |
| PS51 | A1 / B1 | A2 / B2 | A3 / B3 |

The eight new answers use the same model, client, prompt and reasoning level, one fresh
`codex exec --ephemeral` session each, shuffled A/B order. The existing stage-3 answers are
kept because the skill has not changed.

## PS51 decision path

1. Read the prompt, the benchmark `expected_behavior`, the rubric and both answers.
2. Confirm the only lost 25 points is the programmatic write, not the script or the bytes.
3. Check whether `references/powershell-51.md` already contains the method.
4. Run the proposed code on 5.1 and 7.7 in a temp directory with a Chinese path.
5. Only change the skill if the document lacks the method **and** the task requires it.

Result: the method is present, the prompt's "新建" is not explicit enough to call the
documentation defective, and the models chose a manual save. No skill change. The write
test is kept as evidence.

## Execution rules

Same as stage 3: normal user, no `-ExecutionPolicy Bypass`, per-sample temp directory,
parser gate, dangerous-command scan, path rewriting, timeouts, stdout/stderr/exit capture,
file hashes. A temp directory is not an OS sandbox; that residual risk is recorded.

## Verdict rules

- **PASS**: route metadata correct, BAT/PS51 reach 3 samples per side, B not worse than A,
  no safety violation, all tests green.
- **CONDITIONAL**: a shared quality gap remains, the sample is still small, or a test is
  incomplete.
- **FAIL**: a B regression, a safety violation, or an unauthorised system change.
