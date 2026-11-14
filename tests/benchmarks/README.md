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

The saving is not uniform, and averaging it away would be dishonest:

- **Translation alone saves 3–5%.** English carries the same facts at the same
  information density. Anyone promising 30% from "translate to English" is measuring
  bytes, or deleted content.
- **Restructuring saved 22–54%** on the five tasks whose material was duplicated or
  routed too coarsely: one page that was 73% a topic the task did not need, and a verdict
  table described twice in two files.
- The 15% gate is met on the mean and median, **not on p90** — see `results/report.md`
  for the breakdown and for why the tail is the hard part.
