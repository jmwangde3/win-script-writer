# Codec evidence appendix

Measurements behind `references/python-source-encoding.md`. Nothing here is needed to
decide a verdict; load it when a verdict is disputed, when extending the detector, or
when a codec name behaves differently on another CPython build.

## 1. The codec name table

v1.0.3 classified names by prefix regex (`^mac[-_.]?[a-z0-9]*$`, `^ibm[0-9]{3,5}$`…), so
`mac-bogus`, `shift_jis_typo`, `big5-nope` and `ibm99999` counted as known — the
interpreter rejects all four. v1.0.4 uses an **exact table**: normalise per the tokenizer
(lowercase, `_`→`-`, `utf-8-*` folds to `utf-8`, the `latin-1` family folds to `latin-1`,
else verbatim), then look up 105 families / 411 spellings.

The table is the **union** across sampled versions: `cp858`'s four leading-zero aliases
(`cp00858` / `csibm00858` / `ibm00858` / `pc_multilingual_850_euro`) come from gh-149801
and exist only from 3.13.14 / 3.14.6 / 3.15.0b2, so a single-machine table rejects files
written for a newer patch — which is what CI reported.

`TestCodecAliasCoverage` walks `encodings.aliases` plus module names, `compile()`s each
and asks the detector: on 3.13.9, 471 spellings, 380 usable, 91 refused, **0
disagreements**. `ansi` maps to `mbcs` (CP936 here) and `ansi_x3.4-1968` to `ascii`: over
the same GBK bytes the interpreter runs the former and rejects the latter.

Three boundaries, measured:

- the `utf-8-*` prefix always counts as UTF-8 (`codecs.lookup('utf-8-unix')` raises
  `LookupError`, the file still runs);
- `latin-2` through `latin-16` hyphenated are all rejected (`latin2` runs, `latin-2` /
  `latin_2` report `unknown encoding`; `latin-1` is the sole exception);
- a bare code page number is a valid alias (`1252`, `936` hold; `54936` does not).

## 2. The GBK grid: 21791 cells, 2149 short of CP936

CPython's `gbk` is 126 lead × 190 trail (`40–7E`, `80–FE`, skipping `7F`) = 23940
candidate cells, of which **21791** decode with a clean round trip. The other 2149 are
holes, distributed regularly:

| Lead | Trail `40–A0` (low) | Trail `A1–FE` (high) |
| --- | --- | --- |
| `81–A0` | all present | all present |
| `A1–A7` | none | present, but each symbol block is missing its tail |
| `A8` | `40–95` present, `96–A0` not | `BC`, `BF`, `C1–C4`, `EA–FF` missing |
| `A9` | `58`, `5B`, `5D–5F`, `89–95`, `97–A0` missing | only `A4–EF` |
| `AA–AF` | all present | none |
| `B0–D6`, `D8–F7` | all present | all present |
| `D7` | all present | present up to `F9` |
| `F8–FD` | none | none |
| `FE` | present up to `4F` | none |

Two single-byte holes as well: **Python rejects both `0x80` and `0xFF`**.

This table has to be carried locally. CP936 maps **all** 2149 holes into the private use
area with a successful round trip (0 refused) and additionally reads `0x80` as € and
`0xFF` as U+F8F5. So UTF-8 `E4 B8 AD` (中) looks to CP936 like "`E4B8` as one character
plus `AD` as a valid lead byte" — the original reason a UTF-8 file was once judged "valid
GBK". `Test-GbkCell` now decides cell by cell, and the integration suite concatenates
all 21791 valid cells into one file requiring acceptance, then takes one cell per holed
lead byte requiring rejection.

## 3. HZ's state machine is stricter than RFC 1843

CPython 3.13's `hz` codec does not match the RFC's permissive reading. Measured:

| Bytes | Position | CPython | Note |
| --- | --- | --- | --- |
| `~{` | ASCII mode | enters GB mode | |
| `~}` | GB mode | exits back to ASCII | must be paired |
| `~}` | ASCII mode | **`SyntaxError`** | the RFC's "redundant `~}`" is refused |
| `~~` | ASCII mode | one literal `~` | |
| `~~` | GB mode | **`SyntaxError`** | escapes exist only in ASCII mode |
| `~\n` | ASCII mode | line continuation, two lines joined | LF only; `~\r\n` errors |
| `~\n` | GB mode | **`SyntaxError`** | opposite of RFC 1843, see below |
| `~\r\n` | GB mode | **`SyntaxError`** | same outcome as LF, measured not inferred |
| `0x21–0x7E` | GB mode | first/second byte of a double-byte cell | space, TAB, LF, `0x7F` all illegal |
| `0x7E` | GB mode, second byte | legal | `56 7E` = `D6 FE` = 筑 |
| end of file | still in GB mode, last pair complete | **accepted** | measured `rc=0`, content 中文 |
| end of file | still in GB mode, one byte dangling | `SyntaxError` | `can't decode byte` |

RFC 1843 allows continuation in both modes; CPython allows ASCII only. In GB mode `~`
starts a double-byte cell whose second byte must fall in `0x21–0x7E`, and neither `0x0A`
nor `0x0D` qualifies, so both `"~{VP~\nXX~}"` and `"~{VP~\r\nXX~}"` fail (measured
`rc=1`). v1.0.4 added `py-coding-hz-gb-newline.py` / `-gb-crlf.py` to pin both endings —
a detector handling only LF lets the CRLF fixture through.

The last two rows are different situations and the detector says so: it returns `$true`
with `Detail='unterminated'` and appends "ends inside GB mode" to the `WARN`. A `FAIL`
there would reject a file Python runs: `py-coding-hz-open.py` exits 0 without a trailing
newline, 1 with one.

HZ's GB-mode double bytes use the GB2312 table (`Test-Gb2312Cell`), not GBK: HZ is
defined over GB2312, so a GBK extension cell such as `81 40` is equally illegal there.
