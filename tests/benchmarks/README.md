# Context benchmark (A/B)

What v1.1.0 claims to save is **tokens the model actually reads**, not bytes on disk.
Those two move in opposite directions when you translate Chinese to English: the same
information needs 20–40% more UTF-8 bytes in English, while a Chinese character costs
roughly three times the tokens of an English character. Byte counts cannot settle it, so
this directory measures tokens.

## Method

Tokens are counted with the **official DeepSeek offline tokenizer**
(<https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/> →
`deepseek_v4_tokenizer.zip`):

```python
from tokenizers import Tokenizer
tk = Tokenizer.from_file("tokenizer.json")
len(tk.encode(text, add_special_tokens=False).ids)
```

Three consequences, stated rather than hidden:

- These are **tokenizer estimates**, not API `usage` records. There is no model call here,
  so `output_tokens` and `cached_input_tokens` are absent by design and must not be
  invented by dividing character counts.
- The tokenizer is a 6 MB blob and is **not vendored** — it would land in the release
  archive. `compute.py` looks for it in `--tokenizer`, `$DEEPSEEK_TOKENIZER`,
  `tests/benchmarks/vendor/tokenizer.json`, then a local scratch path.
- Prefix caching is real, but a cache hit and a fresh input are not additive. Only the
  input side is reported.

## Measurement boundary

Read every number in `results/` against these six statements. They are the whole of what
the benchmark supports; anything outside them is not measured here.

1. **Tokenizer.** Tokens are counted with the official **DeepSeek V4** offline tokenizer
   (`deepseek_v4_tokenizer.zip`, published at
   <https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/>). No other tokenizer,
   and no character-count approximation, is used anywhere in `results/`.
2. **Estimate, not usage.** The figures are **tokenizer estimates**. They are not API
   `usage` objects, not billable tokens, and not a measurement of any served request.
3. **Routing is pre-declared.** The reference pages attributed to a task are exactly the
   `loads` list in `tasks.json` (with the single `loads_baseline` override described
   below). The benchmark does not decide routing at run time; it reads a plan.
4. **No agent was executed.** `compute.py` never calls a model or an agent, and it does
   **not** observe which files a real session would load. A real run may load fewer
   pages (an agent might answer from the entry file) or more (a second hop into
   `appendix-codec-evidence.md`). Neither direction is captured.
5. **What 15.5% means.** It is the mean `skill_context` saving — metadata + body + the
   routed reference — over these 20 tasks, under this tokenizer and this routing plan.
   It is a property of the documents and the plan, not of any particular runtime.
6. **No cross-model transfer.** Do not quote this figure as the saving a GPT, Codex,
   Claude or any other model would see. Tokenizers differ in how they split English and
   Chinese, so the percentage is tokenizer-specific. Re-measure with that model's own
   tokenizer before making any claim about it.

## What one task costs

```
skill_metadata_tokens   the frontmatter description — what the router reads
skill_body_tokens       SKILL.md minus frontmatter — what loads on invocation
reference_tokens        the reference(s) that task's routing selects
prompt_tokens           the task prompt itself (identical in both groups)

skill_context   = metadata + body + reference
call_estimate   = skill_context + prompt
```

`skill_context` is the number the acceptance gate is about: it is the context the skill
itself causes. `call_estimate` adds the user's request so the saving can be read against
a realistic denominator.

## Tasks

`tasks.json` holds 20 fixed tasks, three per category except git-bash, security and
tooling (one each). Each carries the prompt (Chinese, identical in both groups),
`expected_behavior`, `required_checks`, `forbidden_actions` and `loads`.

`loads` is the routing decision: **which single reference the entry table sends that task
to**. Tasks that genuinely need two pages list two.

One override exists and it is deliberate. v1.1.0 moved the PEP 263 material out of
`python.md` and `encoding-matrix.md` into `python-source-encoding.md`. Group A has no
such file, so `py-02` / `py-03` carry `loads_baseline` naming the v1.0.4 page that held
the same content. Without it the comparison would be "A reads nothing" — a bug, not a
saving.

## Reproduce

```bash
# once
python -m pip install tokenizers

# every run
python tests/benchmarks/compute.py --tokenizer /path/to/tokenizer.json
```

Outputs land in `results/`:

| File | Content |
| --- | --- |
| `raw.jsonl` | one line per (group, task); never edited by hand |
| `comparison.csv` | per task, A vs B, with the saving percentage |
| `summary.json` | mean / median / p90 / min / max, plus per-category savings |
| `report.md` | the written reading of the numbers, including what did not improve |

`baseline/v1.0.4/` and `candidate/v1.1.0/` are snapshots of `SKILL.md`, `README.md`,
`CHANGELOG.md` and `references/` for the two versions. They exist so a re-run years later
measures the same text; regenerate the candidate snapshot after any edit that is meant to
change context cost.

## Reading the result

The saving is not uniform, and averaging it away would be dishonest. Three statements,
each with its scope attached:

- **Translation, measured at file level: 1.2%.** The eight references that were
  translated and *not* restructured — `cmd-bat`, `dual-version-compatibility`,
  `execution`, `git-bash`, `powershell-51`, `powershell-7`, `security`,
  `troubleshooting` — total 14372 → 14201 tokens, i.e. **−1.2%**.
  This is the only figure that isolates translation. It is near zero because English
  needs 20–40% more bytes for the same facts, which cancels the tokenizer's English
  advantage (≈0.21 vs ≈0.67 token per character).
- **Translation, measured per call: 2.5–5.5% on the 15 tasks that were not
  restructured.** That band is *not* the value of translation alone — every call also
  carries the rewritten description (−44.9%) and the shortened `SKILL.md` body (−4.3%).
  Quote it as a per-call figure with that composition, never as "translation saves
  3–5%".
- **Restructuring saved 22–54%** on the five tasks whose material was duplicated or
  routed too coarsely: one page that was 73% a topic the task did not need, and a verdict
  table described twice in two files.
- The 15% gate is met on the mean and median, **not on p90** — see `results/report.md`
  for the breakdown and for why the tail is the hard part.

## Quality, which this directory does not measure

Token cost is not answer quality, and nothing above says the English documents are better.
`quality-ab/` holds the plan for that: 10 tasks, one pinned model, isolated sessions,
anonymised samples with a sealed mapping, and a 100-point rubric (correctness 30, encoding
25, host compatibility 20, safety 15, completeness 10). `quality-ab/STATUS.md` reads
**PENDING** — no model was called, so no answer and no score exists.
