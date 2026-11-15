# Python source encoding declarations (PEP 263)

`# coding: <name>` is not a comment; it is the interpreter's input contract. Python 3
reads source as UTF-8 by default, but a comment in the first two lines changes that:
`# -*- coding: gbk -*-` or `# coding=cp936`.

This file is the **decision contract** — what each declaration actually does, and which
verdict `Test-ScriptEncoding.ps1` must emit. The measurements behind every row (codec
name table, GBK grid, HZ state machine) are in
`references/appendix-codec-evidence.md`; nothing here rests on an unmeasured claim.

## 1. Declaration → behaviour

| Actual bytes | Declaration | Python 3 behaviour | Detector verdict |
| --- | --- | --- | --- |
| GBK | `gbk` / `cp936` / `ms936` / `936` | runs | `WARN` (`DECLARED`) |
| GB2312 | `gb2312` / `euc-cn` / `euccn` | runs | `WARN` (`DECLARED`, name reported as `gb2312`) |
| 7-bit HZ | `hz` / `hzgb` / `hz-gb-2312` | runs | `WARN` (`HZ`) |
| GB18030 (including 4-byte) | `gb18030` / `gb18030-2000` | runs | `WARN` (`DECLARED`) |
| GBK extension (e.g. `81 40`) | `gb2312` | `SyntaxError: 'gb2312' codec can't decode byte 0x81` | `FAIL` (`INVALID_BYTES`) |
| non-UTF-8 | none | `SyntaxError: Non-UTF-8 code ...` | `FAIL` (`CP936_PYTHON`) |
| UTF-8 + BOM | `gbk` / `latin-1` / `cp1252` | `SyntaxError: … with BOM` | `FAIL` (`BOM_CONFLICT`) |
| UTF-8 + BOM | `utf8` (non-canonical spelling) | `SyntaxError: encoding problem: utf8 with BOM` | `FAIL` (`BOM_CONFLICT`) |
| UTF-8 + BOM | `utf-8` / `utf-8-sig` | runs | `OK` |
| UTF-8 | `gbk` (bytes do not decode) | `SyntaxError: 'gbk' codec can't decode byte 0xff` | `FAIL` (`INVALID_BYTES`) |
| UTF-8 | `gbk` (bytes happen to decode) | runs, reads mojibake | `WARN` (`AMBIGUOUS`) |
| non-ASCII | `latin-1` | runs | `WARN` (`DECLARED`, `ENCODING=unknown`) |
| any | `cp1252` / `shift_jis` / `big5` … | runs | `WARN` (`UNVERIFIED`, `PAYLOAD=unverified`) |
| bytes with no mapping in that codec | `cp1252` (body contains `0x81`) | `SyntaxError: 'charmap' codec can't decode byte 0x81` | `WARN` (`UNVERIFIED`, **the tool cannot see this hole**) |
| truncated multibyte character | `shift_jis` (`93` with no trail byte) | `SyntaxError: … can't decode byte` | `WARN` (`UNVERIFIED`, same) |
| any | `utf-9` / `windows-936` / `cp54936` / `54936` / `hzgb2312` / `cn-gb` | `SyntaxError: unknown encoding: <name>` | `FAIL` (`UNKNOWN`; `BOM_CONFLICT` when a BOM is present) |
| any | `base64` / `rot13` / `hex` / `zlib` / `uu` / `bz2` / `quopri` | `SyntaxError: 'base64' is not a text encoding` | `FAIL` (`UNUSABLE`: the name is right, the codec is not a text codec) |
| UTF-8 | `utf-8` | runs | `OK` / `WARN` (with BOM) |

## 2. When `WARN`, when `FAIL`

One line: **`FAIL` is reserved for "the interpreter refuses it" or "the bytes contradict
the declaration". Anything the interpreter runs never enters `FAIL`.**

| Reason code | Tier | Trigger | Exit |
| --- | --- | --- | --- |
| `PY_SOURCE_CODING_DECLARED` | `WARN` | declaration holds, single match | 1 |
| `PY_SOURCE_CODING_AMBIGUOUS` | `WARN` | declaration holds, another family also decodes | 1 |
| `PY_SOURCE_CODING_HZ` | `WARN` | HZ declaration holds (7-bit bytes, no high bytes) | 1 |
| `PY_SOURCE_CODING_UNVERIFIED` | `WARN` | the name is in the CPython compatibility set this project verified, but the current interpreter may not resolve it, and the detector has no byte table for it (adds `SOURCE_CODING_PAYLOAD=unverified`) | 1 |
| `PY_SOURCE_CODING_UNKNOWN` | `FAIL` | `codecs.lookup` does not resolve the name | 2 |
| `PY_SOURCE_CODING_INVALID_BYTES` | `FAIL` | the declared codec cannot decode the whole payload | 2 |
| `PY_SOURCE_CODING_BOM_CONFLICT` | `FAIL` | the declaration contradicts the BOM (decided before the name lookup, even when the name is also wrong) | 2 |
| `PY_SOURCE_CODING_UNUSABLE` | `FAIL` | the name resolves but the codec cannot encode source: the `utf-16` / `utf-32` families, and transform codecs such as `base64` / `rot13` | 2 |

Three cases deliberately avoid `FAIL`. Each one was wrong before the fix, and each is a
different mistake:

1. Python runs it (`rc=0`) yet the verdict was `FAIL` — that declares a runnable file
   unusable.
2. "Another codec also decodes it" was `FAIL` — that is ambiguity, not error (§3 below).
3. "The detector does not know this codec" was `FAIL` — that is a gap in the tool, not a
   fault in the file (§4 below).

## 3. Unique, ambiguous and undecodable are three outcomes, not two

The original rule asked one question — "do the declaration and the bytes agree" — and
judged `# coding: gb2312` plus `茅` (`C3 A9`) as a conflict. Those bytes are `茅` in
GB2312 and `é` in UTF-8; Python decodes per the declaration, yields `茅`, exits 0.
"Another codec also decodes it" only means it is not unique.

| Case | Test | Verdict |
| --- | --- | --- |
| unique match | declaration decodes, the detected family covers it | `WARN` + `DECLARED` |
| ambiguous | declaration decodes, another family also decodes and is the detected one | `WARN` + `AMBIGUOUS` |
| undecodable | the whole payload violates the declared codec | `FAIL` + `INVALID_BYTES` |

**Only a declaration that cannot decode its own bytes is an error.** `gb2312` over valid
UTF-8 is `AMBIGUOUS` (Python really runs it; a hard `FAIL` would overrule the interpreter
out of caution), while `E4 B8 AD` declared `gbk` must be `FAIL` — genuinely undecodable,
because CPython's `gbk` grid has 2149 holes that CP936 fills.

## 4. Four states of a codec name

`Resolve-PythonCodingName` returns a `Support` field. Collapsing "Python does not know
it" and "the detector does not implement it" into one answer is the bug this prevents:
`cp1252` and `54936` would both come back `UNKNOWN`, though the former exits 0.

| `Support` | Meaning | Examples | Verdict |
| --- | --- | --- | --- |
| `supported` | valid name, the detector can verify it | `utf-8`, `gbk`, `gb2312`, `hz`, `gb18030`, `latin-1` | per §3 |
| `python-only` | valid name, no byte table here | `cp1252`, `shift_jis`, `big5`, `euc-jp`, `koi8-r` | `WARN` + `UNVERIFIED` |
| `unusable` | resolves, but it is a transform codec, not a text codec | `base64`, `rot13`, `hex`, `zlib`, `uu`, `bz2`, `quopri`; `utf-16` / `utf-32` too | `FAIL` + `UNUSABLE` |
| `unknown` | `codecs.lookup` does not resolve it | `windows-936`, `cp54936`, `54936`, `hzgb2312`, `cn-gb` | `FAIL` + `UNKNOWN` |
| `bom-conflict` | declaration contradicts the BOM | `gbk` + BOM, `utf8` + BOM, `windows-936` + BOM | `FAIL` + `BOM_CONFLICT` |

The BOM test comes **before** the name lookup: `windows-936` reports
`unknown encoding: windows-936`, and with a BOM reports
`encoding problem: windows-936 with BOM`. Both are refused but for different reasons, and
the detector follows the interpreter's order (`py-coding-unknown-bom.py` pins it).

**"The name resolves" is not "the file runs".** `python-only` therefore also emits
`SOURCE_CODING_PAYLOAD=unverified` (JSON `"SourceCodingPayload": "unverified"`), and no
other tier emits that key — not an empty string, which would read as "verified". With
`0x81` in a `cp1252` body, or a lone `93` under `shift_jis`, the interpreter raises
`SyntaxError` while the detector cannot see either hole: `WARN` every time, never `OK`.

The name table is a union across sampled CPython versions, so `python-only` means only
"some CPython this project verified knows the name", not that the current one does:
`cp00858` compiles on 3.14.8 / 3.15.0rc3 and is `unknown encoding` on 3.11.17 / 3.13.9.
The wording therefore never claims "CPython recognizes this codec";
`SOURCE_CODING_PAYLOAD=unverified` stays and `WARN` is not promoted. How the table is
built, and its coverage numbers, are in `references/appendix-codec-evidence.md` §1.

Transform codecs are their own tier: `base64` / `rot13` and the rest (7 families, 18
spellings) resolve in `codecs.lookup()` yet the interpreter refuses them **by name**
(`SyntaxError: 'base64' is not a text encoding`). They live in `PythonCodecUnusable` and
yield `FAIL` + `PY_SOURCE_CODING_UNUSABLE`, apart from `UNKNOWN` — there is no spelling
to fix. `idna` / `punycode` are not in the table: the former is a text codec (ASCII
source compiles), the latter fails at the byte level.

## 5. Latin-1 is counted cell by cell, not waved through

ISO-8859-1 maps all of 0x00–0xFF, so "can latin-1 decode this" is always true. A
detector that returns `$true` for `latin-1` while its repertoire table says
`latin-1 = @('ascii')` flags every non-ASCII latin-1 file as a conflict. Both must agree:
latin-1 describes any bytes, but as a single-byte set it says nothing about **whether
those bytes are also GBK or UTF-8**, so its repertoire counts only itself:

- pure ASCII, declared `latin-1`: holds, unambiguous, `OK`
- non-ASCII, declared `latin-1`: decodes (always true) → `WARN` + `DECLARED`, not
  `CONFLICT`
- detected as UTF-8: `WARN` + `AMBIGUOUS` (both families decode; do not decide)
- with a BOM: `FAIL` + `BOM_CONFLICT` (Python reports
  `encoding problem: iso-8859-1 with BOM`)

`WARN` means "Python runs it", not "this is a good idea"; this project's own `.py` stay
UTF-8.

## 6. Which family the bytes really are

A declaration only means something once the bytes are identified, and GB2312 / HZ /
GB18030 / GBK are not four spellings of 936: GB2312 is a 7445-cell subset, HZ is 7-bit
with no high bytes at all, GB18030 adds 4-byte sequences and has no holes, and GBK
differs from CP936 in 2149 cells. A GBK stream declared `gb18030` always holds, which can
only be expressed through the ambiguity tier in §3. The family table is in
`references/encoding-matrix.md` §2.2; the GBK grid is in
`references/appendix-codec-evidence.md` §2.

The rule is that **the declaration must match the bytes**, not that "it decodes" — a
UTF-8 file declaring `coding: gbk` also decodes, as mojibake. Both steps
(`Test-CodingDecodes` + `Test-PythonCodingAgrees`) must pass before `WARN`.
