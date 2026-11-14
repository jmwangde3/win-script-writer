# -*- coding: utf-8 -*-
"""Context-token benchmark for the win-script-writer skill (A/B, v1.0.4 vs v1.1.0).

Why this exists
---------------
v1.1.0 translates the skill to English and trims duplication. "Fewer bytes" is
not the claim that matters -- what matters is how many tokens the model actually
reads. Byte counts move the wrong way (English needs more bytes for the same
information), so the measurement has to be in tokens.

How tokens are counted
----------------------
With the **official DeepSeek tokenizer** that DeepSeek publishes for offline use
(https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/ ->
deepseek_v4_tokenizer.zip). Not tiktoken, not a bytes/3 or chars*0.6 estimate:
`tokenizers.Tokenizer.from_file(<tokenizer.json>).encode(text)` with
`add_special_tokens=False`.

Even so, these are **tokenizer estimates**, not API `usage` numbers. There is no
model call here, so `output_tokens`, `cached_input_tokens` and any provider-side
overhead are absent by design. Do not add them.

What is measured for each task
------------------------------
    skill_metadata_tokens   the frontmatter description (what the router reads)
    skill_body_tokens       SKILL.md minus frontmatter (what loads on invocation)
    reference_tokens        the references that task's routing selects
    prompt_tokens           the task prompt itself (identical for both groups)
    skill_context           metadata + body + reference
    call_estimate           skill_context + prompt

Both groups load the *same information* for a given task; only its packaging and
language differ. That is what makes the difference attributable to the translation.

One exception is recorded explicitly: v1.1.0 splits the PEP 263 material out of
`python.md` / `encoding-matrix.md` into `python-source-encoding.md` (plus a second-hop
`appendix-codec-evidence.md`). Group A has no such file, so those tasks carry a
`loads_baseline` override naming the v1.0.4 page that held the same content. Without
it the comparison would be A = nothing, which is not a saving, it is a bug.

Usage
-----
    python tests/benchmarks/compute.py --tokenizer /path/to/tokenizer.json

The tokenizer is not vendored: it is a 6 MB blob that must stay out of the
release package. Get it from the official zip, or point --tokenizer at any copy.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
TASKS = HERE / "tasks.json"
RESULTS = HERE / "results"


def load_tokenizer(path: str):
    try:
        from tokenizers import Tokenizer
    except ImportError:
        sys.exit("needs the 'tokenizers' package: python -m pip install tokenizers")
    return Tokenizer.from_file(path)


def find_tokenizer(explicit: str | None) -> str:
    candidates = [
        explicit,
        os.environ.get("DEEPSEEK_TOKENIZER"),
        str(HERE / "vendor" / "tokenizer.json"),
        r"H:/temp/ds-tok/dsv4/deepseek_v4_tokenizer/tokenizer.json",
    ]
    for c in candidates:
        if c and pathlib.Path(c).is_file():
            return c
    sys.exit(
        "no tokenizer.json found. Download deepseek_v4_tokenizer.zip from\n"
        "https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/\n"
        "and pass --tokenizer <path>, or set DEEPSEEK_TOKENIZER."
    )


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter block, body). Tolerates a missing block."""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end < 0:
        return "", text
    return text[3:end], text[end + 4 :]


def description_of(frontmatter: str) -> str:
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            return line[len("description:") :].strip()
    return ""


def count(tk, text: str) -> int:
    return len(tk.encode(text, add_special_tokens=False).ids)


def measure_group(
    tk, snapshot: pathlib.Path, tasks: list[dict], label: str, loads_key: str
) -> list[dict]:
    skill_path = snapshot / "SKILL.md"
    if not skill_path.is_file():
        sys.exit("missing snapshot: %s" % skill_path)
    skill_text = skill_path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(skill_text)
    desc = description_of(fm)

    meta_tok = count(tk, desc)
    body_tok = count(tk, body)

    rows = []
    for task in tasks:
        ref_tok = 0
        loaded = []
        for rel in task.get(loads_key) or task["loads"]:
            p = snapshot / rel
            if not p.is_file():
                sys.exit("missing reference in snapshot: %s" % p)
            ref_tok += count(tk, p.read_text(encoding="utf-8"))
            loaded.append(rel)
        prompt_tok = count(tk, task["prompt"])
        rows.append(
            {
                "group": label,
                "task_id": task["task_id"],
                "category": task["category"],
                "skill_metadata_tokens": meta_tok,
                "skill_body_tokens": body_tok,
                "reference_tokens": ref_tok,
                "prompt_tokens": prompt_tok,
                "skill_context": meta_tok + body_tok + ref_tok,
                "call_estimate": meta_tok + body_tok + ref_tok + prompt_tok,
                "files_loaded": loaded,
            }
        )
    return rows


def p90(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1)))))
    return ordered[idx]


def summarise(rows: list[dict], key: str) -> dict:
    vals = [r[key] for r in rows]
    return {
        "mean": round(statistics.mean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "p90": round(p90(vals), 2),
        "min": min(vals),
        "max": max(vals),
    }


def saving(a: float, b: float) -> float:
    if a == 0:
        return 0.0
    return round((a - b) / a * 100, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokenizer", default=None)
    ap.add_argument("--out", default=str(RESULTS))
    args = ap.parse_args()

    tk_path = find_tokenizer(args.tokenizer)
    tk = load_tokenizer(tk_path)

    spec = json.loads(TASKS.read_text(encoding="utf-8"))
    tasks = spec["tasks"]
    groups = spec["groups"]

    a_rows = measure_group(tk, HERE / groups["A"]["snapshot"], tasks, "A", "loads_baseline")
    b_rows = measure_group(tk, HERE / groups["B"]["snapshot"], tasks, "B", "loads")

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # raw.jsonl -- one line per (group, task), never edited by hand
    with (out / "raw.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for row in a_rows + b_rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    # comparison.csv -- per task, A vs B
    fieldnames = [
        "task_id",
        "category",
        "a_skill_context",
        "b_skill_context",
        "context_saving_pct",
        "a_call_estimate",
        "b_call_estimate",
        "call_saving_pct",
        "files_loaded",
    ]
    by_id_a = {r["task_id"]: r for r in a_rows}
    csv_lines = [",".join(fieldnames)]
    for rb in b_rows:
        ra = by_id_a[rb["task_id"]]
        csv_lines.append(
            ",".join(
                str(x)
                for x in (
                    rb["task_id"],
                    rb["category"],
                    ra["skill_context"],
                    rb["skill_context"],
                    saving(ra["skill_context"], rb["skill_context"]),
                    ra["call_estimate"],
                    rb["call_estimate"],
                    saving(ra["call_estimate"], rb["call_estimate"]),
                    "|".join(rb["files_loaded"]),
                )
            )
        )
    (out / "comparison.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    # summary.json
    summary = {
        "tokenizer": {
            "path": tk_path,
            "source": "official DeepSeek offline tokenizer (deepseek_v4_tokenizer.zip)",
            "method": "tokenizer estimate — not an API usage record",
            "add_special_tokens": False,
        },
        "tasks": len(tasks),
        "groups": {
            "A": {"label": groups["A"]["label"], "snapshot": groups["A"]["snapshot"]},
            "B": {"label": groups["B"]["label"], "snapshot": groups["B"]["snapshot"]},
        },
        "per_task_stats": {
            "A": {
                "skill_context": summarise(a_rows, "skill_context"),
                "call_estimate": summarise(a_rows, "call_estimate"),
            },
            "B": {
                "skill_context": summarise(b_rows, "skill_context"),
                "call_estimate": summarise(b_rows, "call_estimate"),
            },
        },
        "group_stats": {
            "A": {
                "skill_metadata_tokens": a_rows[0]["skill_metadata_tokens"],
                "skill_body_tokens": a_rows[0]["skill_body_tokens"],
                "skill_context": summarise(a_rows, "skill_context"),
                "call_estimate": summarise(a_rows, "call_estimate"),
            },
            "B": {
                "skill_metadata_tokens": b_rows[0]["skill_metadata_tokens"],
                "skill_body_tokens": b_rows[0]["skill_body_tokens"],
                "skill_context": summarise(b_rows, "skill_context"),
                "call_estimate": summarise(b_rows, "call_estimate"),
            },
        },
        "saving_pct": {
            "skill_metadata": saving(
                a_rows[0]["skill_metadata_tokens"], b_rows[0]["skill_metadata_tokens"]
            ),
            "skill_body": saving(
                a_rows[0]["skill_body_tokens"], b_rows[0]["skill_body_tokens"]
            ),
            "skill_context_mean": saving(
                summarise(a_rows, "skill_context")["mean"],
                summarise(b_rows, "skill_context")["mean"],
            ),
            "skill_context_median": saving(
                summarise(a_rows, "skill_context")["median"],
                summarise(b_rows, "skill_context")["median"],
            ),
            "call_estimate_mean": saving(
                summarise(a_rows, "call_estimate")["mean"],
                summarise(b_rows, "call_estimate")["mean"],
            ),
            "call_estimate_median": saving(
                summarise(a_rows, "call_estimate")["median"],
                summarise(b_rows, "call_estimate")["median"],
            ),
        },
    }

    # per-category savings, so a good average cannot hide a bad category
    cats = sorted({r["category"] for r in a_rows})
    cat_stats = {}
    for c in cats:
        av = [r["skill_context"] for r in a_rows if r["category"] == c]
        bv = [r["skill_context"] for r in b_rows if r["category"] == c]
        cat_stats[c] = {
            "a": round(statistics.mean(av), 2),
            "b": round(statistics.mean(bv), 2),
            "saving_pct": saving(statistics.mean(av), statistics.mean(bv)),
        }
    summary["per_category"] = cat_stats

    (out / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # console digest
    print("tokenizer:", tk_path)
    print("tasks:", len(tasks))
    print()
    print("%-28s %8s %8s %8s" % ("metric", "A", "B", "saving"))
    print("-" * 56)
    for key in ("skill_metadata_tokens", "skill_body_tokens"):
        a = a_rows[0][key]
        b = b_rows[0][key]
        print("%-28s %8d %8d %7.1f%%" % (key, a, b, saving(a, b)))
    for key in ("skill_context", "call_estimate"):
        a = summarise(a_rows, key)["mean"]
        b = summarise(b_rows, key)["mean"]
        print("%-28s %8.1f %8.1f %7.1f%%" % (key + " mean", a, b, saving(a, b)))
        a = summarise(a_rows, key)["median"]
        b = summarise(b_rows, key)["median"]
        print("%-28s %8.1f %8.1f %7.1f%%" % (key + " median", a, b, saving(a, b)))
        a = summarise(a_rows, key)["p90"]
        b = summarise(b_rows, key)["p90"]
        print("%-28s %8.1f %8.1f %7.1f%%" % (key + " p90", a, b, saving(a, b)))
    print()
    print("per category (skill_context mean):")
    for c, v in cat_stats.items():
        print("  %-14s A=%7.1f  B=%7.1f  %6.1f%%" % (c, v["a"], v["b"], v["saving_pct"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
