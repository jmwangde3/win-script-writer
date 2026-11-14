# A/B context report: v1.0.4 → v1.1.0

Measured with the official DeepSeek offline tokenizer over 20 fixed tasks.
Method, task set and reproduction steps: `../README.md`.

> **These are tokenizer estimates, not API usage records.** No model was called. A
> character-count division dressed up as a token number would be exactly the kind of
> unverified figure this release exists to remove.

## 1. Headline

| Metric | A (v1.0.4) | B (v1.1.0) | Saving |
| --- | ---: | ---: | ---: |
| `skill_metadata_tokens` (description) | 136 | 75 | **44.9%** |
| `skill_body_tokens` (SKILL.md body) | 1502 | 1438 | 4.3% |
| `skill_context` mean | 4868.7 | 4114.1 | **15.5%** |
| `skill_context` median | 4073.0 | 3460.0 | **15.1%** |
| `skill_context` p90 | 6556 | 5857 | 10.7% |
| `call_estimate` mean | 4906.8 | 4152.2 | **15.4%** |
| `call_estimate` median | 4114.0 | 3504.5 | 14.8% |
| `call_estimate` p90 | 6602 | 5895 | 10.7% |
| `skill_context` min / max | 2865 / 9432 | 2733 / 6406 | — |

Gate reading:

- **Skill's own context ≥ 15% smaller — met on mean (15.5%) and median (15.1%), not on
  p90 (10.7%).** §4 explains the tail and what closing it would cost.
- **Average total input ≥ 10% smaller — met** (15.4%).
- **No task grew.** The smallest saving is 2.5% (`ps7-02`); every one of the 20 tasks is
  smaller or equal in both groups.

## 2. Per category (`skill_context` mean)

| Category | A | B | Saving |
| --- | ---: | ---: | ---: |
| python (4 tasks) | 7275.0 | 4566.2 | **37.2%** |
| powershell-7 (3) | 5915.3 | 5188.3 | 12.3% |
| powershell-51 (4) | 3632.0 | 3460.0 | 4.7% |
| git-bash (1) | 2865.0 | 2733.0 | 4.6% |
| cmd-bat (3) | 3874.7 | 3708.7 | 4.3% |
| dual-version (3) | 3855.7 | 3705.0 | 3.9% |
| tooling (1) | 4514.0 | 4374.0 | 3.1% |
| security (1) | 5430.0 | 5265.0 | 3.0% |

The spread is the whole story: one category carries the result because that is where the
restructure happened, and everything else carries translation only.

## 3. Root cause: where the saving came from, and where it did not

### 3.1 Translation is not a token saving

Per-file tokens, body and references only, frontmatter excluded:

| File | A tok | B tok | Δ |
| --- | ---: | ---: | ---: |
| `SKILL.md` body | 1502 | 1438 | −4.3% |
| `references/encoding-matrix.md` | 5000 | 3257 | −34.9% |
| `references/python.md` | 4918 | 1483 | −69.8% |
| `references/cmd-bat.md` | 1278 | 1242 | −2.8% |
| `references/dual-version-compatibility.md` | 1553 | 1543 | −0.6% |
| `references/execution.md` | 2876 | 2861 | −0.5% |
| `references/git-bash.md` | 1227 | 1220 | −0.6% |
| `references/powershell-51.md` | 1994 | 1947 | −2.4% |
| `references/powershell-7.md` | 1652 | 1636 | −1.0% |
| `references/security.md` | 1485 | 1449 | −2.4% |
| `references/troubleshooting.md` | 2307 | 2303 | −0.2% |
| `references/python-source-encoding.md` | — | 3193 | new |
| `references/appendix-codec-evidence.md` | — | 1706 | new |

Read the first group honestly. **The eight references that were only translated save
1.2% between them** (14372 → 14201). English needs more bytes for the same facts, and the
tokenizer's English advantage over Chinese (≈0.21 vs ≈0.67 token per character) is almost
entirely cancelled by the extra characters. The `SKILL.md` body does slightly better
(−4.3%) because its English version also dropped a redundant transition and merged two
conclusions; the description does far better (−44.9%) because it was rewritten, not
translated.

The only large deltas are `python.md` and `encoding-matrix.md` — the two files that were
**restructured**, not translated. Their combined content did not disappear: it reappears
as the two new pages at the bottom of the table.

So 5.7% — the figure before the restructure — was the honest ceiling of a pure
translation. Anything above it had to come from moving content, which is the next section.

### 3.2 The one structural defect worth fixing

`references/python.md` was 4466 tokens, of which **3244 (73%) sat in §7, Python source
encoding declarations** — a topic only two of the four Python tasks raise. The other two
paid 3244 tokens for material they never used.

Worse, that material was described **twice**: `encoding-matrix.md` §2.1 carried the
18-row verdict table and the reason-code table, `python.md` §7 carried the same verdicts
as evidence with the measurements behind them. Two files, ~5700 tokens combined, one set
of rules.

The fix is a re-cut, not a deletion:

| New page | Carries | Tokens |
| --- | --- | ---: |
| `references/python-source-encoding.md` | decision contract: measured declaration table, 8 reason codes, four `Support` states, the WARN/FAIL boundary | 3193 |
| `references/appendix-codec-evidence.md` | second hop: codec name table provenance, the 21791-cell GBK grid, the HZ state machine | 1706 |
| `python.md` §7 (now a pointer) | the two facts worth carrying without loading either page | 261 |

The three old sections became two new pages — 5700 tokens became 4900, because the
duplicated half was written once — and both pages are routed from `SKILL.md` (rows 6 and
12). What changed beyond the 14% dedupe is **who pays for them and when**: the decision
page is a first hop, the evidence is a second hop reached only when a verdict is disputed.

Effect on the five affected tasks:

| Task | A | B | Saving |
| --- | ---: | ---: | ---: |
| `py-01` (write a file, read it back) | 6556 | 2996 | **54.3%** |
| `py-02` (`# coding: gbk` → UTF-8) | 6556 | 4706 | **28.2%** |
| `py-03` (`gb2312` can't decode 0x81) | 6556 | 4706 | **28.2%** |
| `py-04` (subprocess + handoff) | 9432 | 5857 | **37.9%** |
| `ps7-03` (5.1 vs 7 bytes) | 8290 | 6406 | **22.7%** |

### 3.3 What was deliberately not cut

Every one of these was a candidate and every one was rejected, in the order they were
rejected:

- **`SKILL.md` body beyond the routing rows.** 1438 tokens and it grew by 36 (two routing
  rows for the new pages). Compressing it further means compressing the four mandatory
  rules, the routing table or the security boundaries — the three things a caller cannot
  afford to receive in paraphrase.
- **`references/execution.md`.** 2861 tokens, and it is a tool manual: every mode,
  parameter, exit code and boundary of `run_ps.py`. Trimming it would save tokens on five
  tasks and cost correctness on every one.
- **`references/powershell-51.md`.** The four broken links *are* the subject. A 4.7%
  saving is what translation gives; anything more is content removal.
- **The `python-only` blind-spot explanation.** It looks like duplication with the reason
  code table and is not: it is the only place that says the detector cannot see the hole,
  which is the difference between a `WARN` a reader trusts and one they do not.

## 4. The tail: why p90 is 10.7% and not 15%

`p90` picks the 18th of 20 values, which lands in the 3–5% band: two-reference tasks such
as `ps7-02` (`powershell-7.md` + `execution.md`) and `tool-02`
(`security.md` + `troubleshooting.md`). Those tasks load two pages that were neither
duplicated nor mistuned, so there is nothing to remove without deleting a rule.

Closing the tail would require one of these, and each is a trade this release declines:

1. **Merge or shorten a reference.** Splitting by *task* rather than by *topic* is what
   made §3.2 work; there is no equivalent seam in `execution.md` or `security.md`.
2. **Route two-reference tasks to one page.** That is not an optimisation, it is a bet
   that the second page is unnecessary. `ps7-02` asks how 7 writes bytes and how to
   launch it; both pages are required.
3. **Compress the mandatory rules.** Explicitly out of scope, and it would fail the
   quality gate that outranks this one.

So the honest summary: **mean and median clear 15%, p90 does not, and the distribution is
bimodal on purpose.**
**A number above 15% at p90 would have meant deleting a rule.**

## 5. Protocol deviations, stated

The plan called for 20 tasks × 2 groups × 3 repetitions = 120 runs, a metric table with
`cached_input_tokens` / `output_tokens`, and a 100-point blind quality review.

What was actually done, and why:

- **One pass per group, not three.** The measurement is a pure function of the text: the
  tokenizer is deterministic and no model is called, so runs 2 and 3 are byte-identical to
  run 1. Repeating them would produce three copies of one number and imply a variance
  that does not exist. If a real model call is ever added, repetitions become meaningful
  and this section is where that changes.
- **No `output_tokens` / `cached_input_tokens`.** Both require an API call. Reporting them
  from a local script would be fabrication; reporting a cache hit as an addition to input
  would double-count.
- **No 100-point blind review.** A blind review needs generated answers from a model, and
  there is no model in this loop. What was done instead is mechanical and checkable:
  every reference still answers the `required_checks` of the tasks routed to it (the
  facts were moved, not dropped), the routing contract tests (42) and the evaluation
  scenarios (16) pass, and the reference-coverage test fails if any page on disk is ever
  unreachable. **The quality gate is therefore `CONDITIONAL`, not `PASS`**: the structural
  evidence is there, the human quality score is not, and inventing one would be worse than
  leaving it open.

## 6. Reproduction

```bash
python -m pip install tokenizers
python tests/benchmarks/compute.py --tokenizer /path/to/tokenizer.json
```

`results/raw.jsonl` holds every per-task row, `comparison.csv` the pairwise table,
`summary.json` the aggregates above. The two snapshots under `baseline/` and `candidate/`
are frozen text; regenerate the candidate snapshot after any edit meant to change cost.
