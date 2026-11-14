# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); version
numbers follow [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-11-14

Documentation-only release: the skill is translated to English and its progressive
disclosure is re-cut. No runtime behaviour changes — every exit code, JSON field,
parameter and write semantic is identical to v1.0.4.

### Changed

- **Every document is now English.** `SKILL.md`, all of `references/`, `README.md` and
  this file. Script names, parameter names, JSON field names, error codes and the
  Chinese content inside test fixtures stay as they were, because they are part of the
  contract, not prose.
- **`SKILL.md` description shortened from 190 to 135 characters.** The old one repeated
  the same trigger four ways (`ps1` / `PowerShell script` / `write a script` / `generate
  a script`), duplicated the tool section, and named `run_ps.py`, which is an
  implementation detail rather than a routing signal. The entry file stays under
  5.3 KB and still carries all four mandatory rules, the full routing table and the
  security boundaries.
- **PEP 263 material split out of `python.md` and `encoding-matrix.md`** into
  `references/python-source-encoding.md` (the decision contract: the measured
  declaration table, the eight reason codes, the four `Support` states) and
  `references/appendix-codec-evidence.md` (the second hop: codec name table
  provenance, the 21791-cell GBK grid, the HZ state machine).
  The two old files described the same verdict rules twice; `python.md` §7 now points
  at the new page and `encoding-matrix.md` §2.1 keeps only the two BOM rows that belong
  to its own frame.

### Added

- `tests/benchmarks/`: a reproducible A/B context benchmark. 20 fixed tasks across
  seven categories, an official-tokenizer measurement script, and both snapshots
  (`baseline/v1.0.4`, `candidate/v1.1.0`). Results are token estimates, not API usage
  records — the distinction is stated in the report rather than glossed over.
- Two routing-table rows and two evaluation scenarios (P11, P12) so the new pages are
  reachable and exercised.

### Measured

- Skill context per call, 20 tasks: mean 4868.7 → 4114.1 tokens (**−15.5%**), median
  4073.0 → 3460.0 (**−15.1%**), p90 6556.0 → 5857.0 (−10.7%). Description alone
  136 → 75 (−44.9%). No task regressed; the smallest saving is 2.5%.
- The distribution is bimodal by design: 14 tasks that only gained a translation save
  3–5%, the five tasks that gained the restructure save 22–54%.

### Known limits

- The 15% mean is carried by the five restructured tasks. Translation alone does not
  save tokens on English-vs-Chinese prose at equal information density, and claiming
  otherwise would be the kind of unverified number this project exists to remove.

## [1.0.4] - 2026-11-14

Second accuracy pass on encoding verdicts. v1.0.3 was right to split codec names into
tiers, but classified them by prefix regex, so "looks like an alias but is not" landed
in `python-only`; and the `python-only` wording implied "name resolves = file runs"
while the detector knows nothing about those bytes. This release replaces the name table
with an exact one and makes the unverified state explicit in the output.

### Changed (behaviour change, read this)

- **The codec name table goes from loose prefix regex to an exact table.** The old
  implementation classified with patterns such as `^mac[-_.]?[a-z0-9]*$`,
  `^(shift|s)[-_.]?jis[a-z0-9_]*$`, `^(big5|csbig5|hkscs)[-_.a-z0-9]*$` and
  `^ibm[0-9]{3,5}$`, so `mac-bogus`, `shift_jis_typo`, `big5-nope` and `ibm99999` were
  all reported as "Python knows it, this tool did not verify it" — the interpreter
  raises `SyntaxError` for all four. Names are now normalised per the tokenizer
  (lowercase, `_`→`-`, `utf-8-*` folds to `utf-8`, the `latin-1` family folds to
  `latin-1`, everything else kept verbatim with `.` truncated only in the utf-8 and
  latin-1 families), then looked up in a family-organised exact table: 105 families,
  411 spellings, each one run against the interpreter or covered by CI on a newer
  patch. The table is the union across the matrix; 7 families / 18 spellings in it are
  transform codecs (next point). `utf-16` / `utf-32` get their own tier meaning
  "parses, but cannot be source".
  **Impact:** the four fake names above, plus `mac` / `macos` / `macx` /
  `iso_646_us` / `jisx0208` / `x_mac_cyrillic` / `pt_154` / `cshproman8` /
  `utf-8.unix`, move from `WARN` to `FAIL` + `PY_SOURCE_CODING_UNKNOWN`. Nothing got
  looser: `cp1252` / `shift_jis` / `big5` / `mac-roman` / `latin2` / `euc-jp` / `ansi` /
  `ansi-x3.4-1968` stay `python-only`; `utf-16` stays `FAIL` + `UNUSABLE`.
- **`python-only` no longer claims the file runs; `SOURCE_CODING_PAYLOAD=unverified`
  is added.** The wording changes from "CPython resolves that name and the file runs" to
  "resolves that name and accepts this spelling, but this detector has no byte-level
  verifier for it, so the payload was not checked; the file may still fail to decode".
  Text output gains one line, JSON gains `"SourceCodingPayload": "unverified"`, and
  **only** in the `python-only` case — in other tiers the key is absent, not empty
  (consumers testing truthiness would read an empty string as verified).
  **Impact:** `WARN` now means "the name holds", not "this is runnable". A file with
  `# coding: cp1252` and `0x81` in the body raises
  `SyntaxError: 'charmap' codec can't decode byte 0x81 … character maps to <undefined>`
  in the interpreter and still gets `WARN` + `unverified` from the detector. That blind
  spot is written into the output; it is not `OK`.
- **The `python-only` message is reworded as a compatibility set.** The table is the
  union of the sampled versions, so a hit only means "some CPython this project verified
  knows it", not that the **current** interpreter does: `cp00858` / `csibm00858` /
  `ibm00858` / `pc_multilingual_850_euro` are leading-zero aliases of `cp858` from
  CPython gh-149801, shipping from 3.13.14, 3.14.6 and 3.15.0b2 respectively (neither
  3.11.17 nor 3.13.9 has them). Measured: 3.11.17 and 3.13.9 report
  `unknown encoding: cp00858`; 3.14.8 and 3.15.0rc3 compile it. The old text "CPython
  recognizes this codec" is true of the set and false of the interpreter on the user's
  machine. It now reads "the name is in the CPython compatibility set this project
  verified, but the interpreter running this file may not support it, and the detector
  did not verify the bytes"; `SOURCE_CODING_PAYLOAD=unverified` stays, `WARN` is not
  promoted to `OK`, and the width of the verdict is unchanged.
- **Transform codecs get their own `unusable` tier, separate from "unknown name".**
  `base64` / `rot13` / `hex` / `zlib` / `uu` / `bz2` / `quopri` — 7 families, 18
  spellings — all resolve in `codecs.lookup()` but none is a text codec; the
  interpreter's own words are `SyntaxError: 'base64' is not a text encoding; use
  codecs.decode() to handle arbitrary codecs`. v1.0.3 filed them with `mac-bogus` under
  `unknown-name`, which sent people to fix a spelling that was not misspelled.
  **Impact:** these move from `PY_SOURCE_CODING_UNKNOWN` to
  `PY_SOURCE_CODING_UNUSABLE`, `SOURCE_CODING_SUPPORT` gains the value `unusable`,
  `VERDICT` stays `FAIL` and the exit code stays 2 — diagnosis only, nothing relaxed.
  True text codecs such as `idna` / `punycode` are not in the table (the former really
  does compile ASCII source; the latter fails on bytes, not on the name).

### Added

- 8 fixtures: `py-coding-hz-gb-newline.py` / `-gb-crlf.py` (GB-mode line continuation,
  LF and CRLF), `py-coding-shift-jis-bytes.py` / `-truncated.py`,
  `py-coding-big5-bytes.py` / `-truncated.py`, `py-coding-cp1252-bytes.py` /
  `-undefined.py` (complete character and truncated bytes in each pair). Fixtures
  69 → 77; the byte SHA256 of all 69 existing ones is unchanged.
- Pester: 3 new Contexts, 46 cases — `codec name table`, `python-only payload state`,
  `HZ state machine boundaries`. 15 more were added to `codec name table` at the end:
  4 for the compatibility-set wording (`cp00858` / `csibm00858` / `shift_jis` /
  `cp1252`), 9 for transform-codec classification, 1 for the unknown-vs-transform fork,
  1 for the `idna` boundary. Pester total 200, 200/200 on both 5.1 and 7.
- Integration `TestCodecAliasCoverage`: walks `encodings.aliases` and the module names
  under `encodings/`, writes each spelling into a real source file, `compile()`s it,
  then asks the detector — comparing only whether the two agree, with no hard-coded
  answer for any name. On 3.13.9: 471 spellings, 380 usable as source, 91 rejected,
  **0 disagreements**. The 471 dedupe from 327 alias keys, 98 canonical names (none of
  which are keys), 121 module names (22 of them new) and 24 fake spellings. Same class
  adds `TestPythonOnlyPayload`: three "complete character / truncated bytes" pairs must
  all get `WARN + unverified` from the detector while the interpreter measurably gives
  `rc=0` on the first half and `rc=1` on the second; plus an `ansi` regression — `ansi`
  is `mbcs` (CP936 here), `ansi_x3.4-1968` / `ansi-x3.4-1968` are `ascii`, so over the
  same GBK payload the interpreter runs the former and rejects the latter two, and the
  detector must fork the same way.
- Integration `TestUnusableCodecReason` and `TestCodecCompatibilitySet`. The first
  `compile()`s all 18 transform spellings, confirms the interpreter refuses them by
  **name** (`is not a text encoding`), then requires `unusable-codec` from the detector
  for each. The second asserts both hosts for `cp00858` — a host that knows it and a
  host that does not both yield `WARN` + `unverified`, with no skipping on either side.

### Fixed

- **HZ's GB-mode line continuation is pinned by measurement.** RFC 1843 allows `~\n` to
  continue a line in either mode; CPython allows ASCII mode only. In GB mode `~` starts a
  double-byte cell whose second byte must fall in `0x21–0x7E`, and neither `0x0A` nor
  `0x0D` qualifies, so both `"~{VP~\nXX~}"` and `"~{VP~\r\nXX~}"` raise
  `UnicodeDecodeError`. The detector's state machine already followed this; what was
  missing was evidence, so two fixtures now pin LF and CRLF — an implementation handling
  only LF would let the CRLF one through.
- **Quoted interpreter messages in diagnostics are now measured ones.** The `utf-16` /
  `utf-32` reason used to say "CPython raises SyntaxError: encoding problem: utf-16";
  measured on 3.11.17 / 3.13.9 / 3.14.8 / 3.15.0rc3, all four print
  `'utf-16-le' codec can't decode byte 0x0a in position 22: truncated data` instead. The
  reason now just says "not an ASCII-compatible source encoding; the whole file has to
  decode with it" and quotes no error that does not exist. Stale quotes of the same kind
  were corrected in the docs: an unknown name is `unknown encoding: <name>` (not
  `encoding problem:`), and undecodable bytes are `'gb2312' codec can't decode byte
  0x81 …`. The real `encoding problem: <name> with BOM` form is kept.
- Docs: `references/python.md` §7.3 rewritten as "exact table + normalisation rules +
  full regression", with the payload table and the negative list of fake names; §7.5
  gained the GB-mode `~\r\n` row and the cause of the RFC divergence.
  `references/encoding-matrix.md` gained two "holes in a declaration" rows and a
  paragraph on what `WARN` actually means. `README.md` gained a design note ("`WARN`
  does not mean the file runs") and the alias regression numbers in the verified scope.
  `SKILL.md`'s detector entry gained one sentence on the payload meaning; the entry file
  still holds routing and hard rules only.
- **Version claims unified across the repository.** The origin of `cp858`'s aliases was
  stated three different ways: script comments and Pester said "new in 3.13.17",
  integration said "introduced in 3.14", the reference page said "added by 3.13.17".
  Upstream fact: introduced by gh-149801, shipping from 3.13.14 on the 3.13 line,
  3.14.6 on the 3.14 line and 3.15.0b2 on 3.15; `ccsid00858` is a 3.15-only follow-up
  alias. `README.md`'s verified scope is split into three tiers (official CI matrix /
  additional measurements / not in the matrix), `python.md` §7 and `encoding-matrix.md`
  follow the same wording, and 3.14 / 3.15 are stated to be outside the matrix. The
  decision logic and the table are untouched.

### Known gaps (left for v1.0.5)

**The supported boundary first:** the official matrix is Python 3.11 and 3.13, each
against Windows PowerShell 5.1 and PowerShell 7 — four jobs — plus the UTF-8-mode
preview job and docs contract. This machine additionally has one-off measurements on
3.11.17 / 3.13.9 / 3.13.16 / 3.14.8 / 3.15.0rc3. **3.14 and 3.15 are not in the
matrix**; the UTF-8-mode job simulates 3.15's default behaviour, it is not a 3.15
compatibility test.

The table is the union of 3.11 / 3.13, and later patches and previews added aliases the
detector has not caught up with. `TestCodecAliasCoverage` over five interpreters
(`compile()` against the detector both ways), disagreements: 3.11.17 **0** / 3.13.9
**0** / 3.13.16 **0** (479 names) / 3.14.8 **6** / 3.15.0rc3 **58**.
The six on 3.14.8 are the new `cp874` family (`874` / `ms874` / `windows_874`) plus
`cseuckr` / `iso_8859_8_e` / `iso_8859_8_i`; the 52 extra on 3.15.0rc3 are a whole batch
of `cs*` spellings (`cswindows1252`, `cswindows31j`…), `latin_2`…`latin_10`, `mac`,
`utf8-sig`, `windows-936`, `cshproman8`, `ccsid00858` and the like, all resolvable on
3.15.

Those names really do report `unknown encoding` on 3.11 / 3.13, so `FAIL` today is not a
misjudgement; what needs updating is the table, not the logic — re-sample when 3.15
ships, using the same procedure. Until then a file some interpreter can compile gets
`FAIL` on 3.14 / 3.15; the error is on the side of saying one more thing, not of
letting something through.

## [1.0.3] - 2026-11-14

Accuracy fix for encoding aliases. The detector treated GBK, GB2312, HZ-GB-2312 and
GB18030 as one CP936, and got three cases wrong as a result: files Python rejects were
passed, files Python runs were failed, and one case was not checked at all. This release
verifies each family against its own byte rules.

### Changed (behaviour change, read this)

- **The GBK grid ships with the detector instead of being proxied by CP936.** The two
  differ in 2149 cells: CPython's `gbk` decodes 21791 of 23940 candidate cells, while
  CP936 maps every one of the remaining holes into the private use area with a
  successful round trip, and additionally decodes `0x80` as € and `0xFF` as U+F8F5.
  `Test-GbkCell` decides cell by cell against a measured-enumerated grid (including
  `A8`'s low range stopping at `95` and `A9`'s low range missing
  `58/5B/5D-5F/89-95/97-A0`), and `Test-GbkPayload` consults only that table.
  **Impact:** UTF-8 bytes declared `gbk` move from `PY_SOURCE_CODING_CONFLICT` to
  `PY_SOURCE_CODING_INVALID_BYTES` — it genuinely does not decode (Python reports
  `encoding problem: gbk`); cells legal in CP936 but unassigned in GBK are no longer
  passed.
- **"Another codec also decodes it" becomes ambiguity, not conflict.** `# coding: gb2312`
  plus one `茅` (`C3 A9`, which is `é` in UTF-8) was `FAIL`, yet Python decodes per the
  declaration, yields `茅` and exits 0. Three tiers now: unique match / ambiguous /
  undecodable by the declaration, with ambiguity on `PY_SOURCE_CODING_AMBIGUOUS`
  (`WARN`).
  **Impact:** `gb2312` / `gbk` / `gb18030` declarations over bytes that also happen to be
  valid UTF-8 move from `FAIL` to `WARN`. Genuinely undecodable stays `FAIL`; nothing
  was downgraded.
- **Latin-1's two judgements agree.** `Test-CodingDecodes` returned `$true` outright while
  the repertoire table listed only `ascii`, so every non-ASCII latin-1 file collided into
  `CONFLICT`. Both now say "latin-1 describes all 256 single-byte values".
  **Impact:** non-ASCII latin-1 declarations move from `FAIL` to `WARN` (`DECLARED`, or
  `AMBIGUOUS` when the detection says UTF-8); pure ASCII stays `OK`; a BOM still
  `FAIL`s.
- **Codec names get four tiers and a new `SOURCE_CODING_SUPPORT=`.** `$null` used to mean
  both "Python does not know it" and "the detector does not support it", so `cp1252`,
  `shift_jis` and `big5` (measured `rc=0`) were `FAIL UNKNOWN`. It now returns
  `supported` / `python-only` / `unknown`, plus a separate BOM-conflict branch. The name
  table was rewritten per family: 327 alias keys plus 121 `encodings/` module names, 448
  spellings checked one by one against the interpreter, 0 disagreements.
  **Impact:** `cp1252` / `shift_jis` / `big5` / `euc-jp` / `mac-roman` / `csisolatin2` /
  `latin2` / `1252` / `ansi` move from `FAIL` to `WARN`
  (`PY_SOURCE_CODING_UNVERIFIED`, stating plainly that the detector has no table for
  them); `utf-8-sig` moves from `FAIL UNKNOWN` to `OK`; tokenizer-only spellings such as
  `utf-8-unix` and `utf-8-bogus` move from `FAIL` to `WARN`; a name other than `utf-8` /
  `utf-8-sig` together with a BOM now reports `PY_SOURCE_CODING_BOM_CONFLICT` (was
  `PY_SOURCE_CODING_CONFLICT`), and the spelling `utf8` with a BOM joins that class
  (Python really does report `encoding problem: utf8 with BOM`). Nothing relaxed in the
  other direction: `latin-2` (the whole hyphenated family), `cp424`, `gb-2312` and
  `base64` still `FAIL`. The detector does not invoke a Python runtime.
- **The HZ state machine is rewritten against CPython's actual behaviour.** CPython's `hz`
  is stricter than RFC 1843: `~~` and `~\n` are legal in ASCII mode only (`~` inside GB
  mode raises `UnicodeDecodeError`), `~}` is illegal in ASCII mode, `0x7E` may be a
  second byte inside GB mode (`56 7E` = 筑), and a file ending inside GB mode with its
  last pair complete is **accepted**.
  **Impact:** files like `py-coding-hz-open.py` — unclosed but runnable — move from
  `FAIL INVALID_BYTES` to `WARN` with «ends inside GB mode» in the reason; illegal
  in-mode escapes and dangling half-characters still `FAIL`.
- **`gb2312` / `euc-cn` are no longer folded into GBK.** They are aliases of GB2312, a
  proper subset of GBK. Windows has no GB2312 code page, so CP936 was proxying it, and
  CP936 allocates far more than GB2312 (`81 40`, `AA A1`, `F8 A1` are all legal CP936
  cells and empty in GB2312). A per-cell table enumerated from CPython 3.13 is used now
  (7445 cells).
  **Impact:** a file declaring `gb2312` whose bytes contain GBK extension characters
  moves from `WARN` to `FAIL` (`PY_SOURCE_CODING_INVALID_BYTES`) — Python reports
  `SyntaxError: encoding problem: gb2312` for these, and the old verdict was a false
  positive. `SourceCodingName` also changes from `gbk` to `gb2312`.
- **`hz` is its own family, no longer GBK.** HZ-GB-2312 is the 7-bit escaped form of
  GB2312 and contains no high bytes at all, so it used to be classified `ascii` and then
  `OK` — effectively unchecked. A 7-bit state machine now runs: `~{` / `~}` / `~~` /
  `~\n` pairing, whether every byte pair inside GB mode falls in the GB2312 table, and
  whether the file ends inside GB mode.
  **Impact:** valid HZ source moves from `OK` to `WARN` (`PY_SOURCE_CODING_HZ` — Python
  runs it, but editors and git see escaped text); unclosed HZ or HZ with illegal cells
  moves from `OK` to `FAIL`.
- **`gb18030` is no longer an unconditional conflict.** Four-byte sequences such as
  `90 30 81 30` do not decode in CP936, so byte detection says `unknown`, and the old
  code treated "detection result not in the known set" as a declaration/bytes conflict —
  failing legal GB18030 source.
  **Impact:** GB18030 source containing four-byte sequences moves from `FAIL` to `WARN`.
- **`windows-936` and `cp54936` are no longer accepted.** They are code page numbers, not
  CPython codec names — `codecs.lookup()` raises `LookupError` for both, and Python
  reports `SyntaxError: encoding problem: <name>` before reading the file.
  **Impact:** these two declarations move from `WARN` to `FAIL`
  (`PY_SOURCE_CODING_UNKNOWN`). The real aliases are `cp936` / `ms936` / `936` and
  `gb18030` / `gb18030-2000`.
- **`Test-ScriptEncoding.ps1` text mode gains `SOURCE_CODING_KIND=`.** Values
  `unknown-name` / `unusable-codec` / `bytes-mismatch`, emitted only when
  `SOURCE_CODING_PROBLEM` is present, to separate "the name does not resolve" from "the
  bytes do not comply". JSON exposes `SourceCodingKind` directly.
- **`gb18030` aliases tightened.** Only `gb18030` and `gb18030-2000` survive measurement;
  `cp54936` / `54936` are covered by the previous point.

### Added

- 8 fixtures: `py-coding-gb2312.py`, `py-coding-euc-cn.py`, `py-coding-hz.py`,
  `py-coding-hz-truncated.py`, `py-coding-gb18030.py`, `py-coding-gbk-as-gb2312.py`,
  `py-coding-windows936.py`, `py-coding-cp54936.py`.
- 22 fixtures across the four fixed surfaces: HZ escapes and truncation
  (`py-coding-hz-tilde-in-gb` / `-escape-in-gb` / `-close-in-ascii` / `-continuation` /
  `-open`), encoding overlap (`py-coding-{gb2312,gbk,gb18030}-overlap`,
  `py-coding-utf8-as-{gbk,gb2312}`), Latin-1 (`py-coding-latin1` / `-ascii` / `-utf8` /
  `-bom`), codec names (`py-coding-{cp1252,shift-jis,big5,54936,hzgb2312,cn-gb,utf8-sig,
  utf8-spelling-bom}`). Fixtures 46 → 68; the byte SHA256 of all 46 existing ones is
  unchanged.
- Pester: 4 new Contexts, 26 cases — `HZ state machine`, `overlapping encodings`,
  `Latin-1 declarations`, `codec name classification`. Pester total 108 → 134.
- Integration `TestGb2312Grid`: builds all 7445 assigned cells plus several GBK-only
  cells with CPython's own codec, requiring `WARN` for the first group and `FAIL` for the
  second. A hand-maintained table drifts; this is the only check that finds a missing
  row.
- Integration `TestGbkGrid`: concatenates all 21791 decodable cells into one source file
  and requires acceptance, then takes one cell per holed lead byte and requires
  rejection, with `0x80` / `0xFF` verified separately. On its first run it caught 153
  falsely rejected cells in the `A8` / `A9` low ranges.
- Integration `TestHzStateMachine`: generates seven byte shapes with the `hz` codec, runs
  Python first and the detector second, comparing only whether the two agree — no
  hard-coded behaviour for any version.
- Integration `TestEncodingOverlap`: three cases (overlapping, decodable, undecodable);
  `TestPythonSourceCoding`'s case table grows from 13 to 28.
- Integration `TestCodingNameAgreement`: writes 28 codec names into real source files,
  asks the interpreter whether the name is usable, asks the detector, and compares the
  two answers. A missing spelling or a stdlib alias change turns this red without needing
  any version's verdict as the standard answer.

### Fixed

- Docs: `references/encoding-matrix.md` gained §2.1.1 (unique / ambiguous / undecodable),
  §2.1.2 (latin-1 single-byte semantics), §2.1.3 (four codec-name tiers), §2.2.1 (GBK's
  21791 cells against CP936's 2149-cell difference), §2.2.2 (the measured HZ state
  machine, row by row) and §2.3 (the `WARN` / `FAIL` reason-code table). The old
  "equivalent to CP936" claim was replaced by the specific differences.
- Docs: `New-EncodedScript.ps1`'s `-Encoding` help no longer claims UTF-8 BOM is "the
  only form 5.1 and 7 both parse" (UTF-16 with a BOM parses in both as well). It is now
  "the recommended cross-version storage format", with the reason stated: other tools
  read it too. The same sentence in `run_ps.py` was rewritten to match.

## [1.0.2] - 2026-11-13

Verdict precision and test credibility fix. The detector had two blind spots where it
confidently gave a wrong answer, the writer collapsed "preview" and "cancel" into one
exit code, and the two jobs in the test matrix were actually running the same shell.
All four are fixed here, each reproduced by a test first.

### Changed (behaviour change, read this)

- **`New-EncodedScript.ps1` gains exit code `4`: confirmation declined.** `ShouldProcess`
  returning `$false` has two meanings — `-WhatIf` (nothing should be written; exit code
  `0`, usage unchanged) and the user pressing "no" (the caller wanted a write and did not
  get one). The latter now exits `4`, and results gain
  `Status=Previewed|Written|Cancelled|Failed`; text mode prints `STATE=`, `-Output json`
  carries `Status`.
  **Impact:** automation that treated "confirmation declined" as success now sees a
  non-zero exit code, which is the point of the change. `-WhatIf` also no longer goes
  through `ShouldProcess`, because that prints a "What if:" banner onto stdout and
  pollutes `-Output json`.
- **`Test-ScriptEncoding.ps1` classifies UTF-32 as `utf32le-bom` / `utf32be-bom` + `FAIL`
  instead of "UTF-16LE".** `FF FE 00 00` was matched by the two-byte signature first and
  reported as UTF-16LE with a NUL as its second character. Four-byte signatures are now
  compared first and the payload is validated as four-byte code points (above U+10FFFF, in
  the surrogate range, or a length not a multiple of four all count as invalid). The
  detector stays read-only: no transcoding, no repair.
  **Impact:** the `Encoding` / `Bom` fields and the exit code change for these files;
  `utf16le-bom` conclusions in old logs will not reproduce.
- **`Test-ScriptEncoding.ps1` recognises Python source encoding declarations (PEP 263).**
  A GBK file with `coding: gbk` runs fine yet was failed alongside declaration-less GBK
  files. Now a valid declaration matching the bytes gives `WARN` (runs here, other tools
  cannot read it); a declaration contradicting the bytes, or naming an unknown encoding,
  gives `FAIL`; GBK with no declaration stays `FAIL`. JSON gains `SourceCoding` /
  `SourceCodingName` / `SourceCodingLine` / `SourceCodingProblem`.
  **Impact:** under `-Profile python` these files' exit code may move from `2` to `1`
  (still `2` with `-FailOnWarning`).
- **`tests/run-all.ps1` no longer installs missing test dependencies silently.** Without
  PyYAML it prints `PYTHON_DEP_MISSING=` and `INSTALL_WITH=`, or you pass
  `-InstallTestDeps` explicitly. CI now runs `pip install -r tests/requirements-test.txt`
  itself.
  **Impact:** a first local run of `-Suite evals` needs one install; no test run will
  silently reach the network again.
- **Integration tests take their child host from the caller.** `tests/run-all.ps1` exports
  `WSW_PS_HOST` / `WSW_PS_EDITION` and prints them at the start of every run;
  `test_pipeline.py` picks `powershell.exe` or `pwsh.exe` accordingly.
  **Impact:** integration run on 7 used to test 5.1; the two jobs are no longer
  interchangeable and the log says which binary produced the result.

### Added

- Detector text output gains `SOURCE_CODING=` / `SOURCE_CODING_LINE=` /
  `SOURCE_CODING_NAME=` / `SOURCE_CODING_PROBLEM=`.
- `tests/requirements-test.txt`: the single list of test dependencies. The four tools
  themselves still have no third-party runtime dependency.
- 7 new fixtures: UTF-32LE and UTF-32BE, the four PEP 263 declaration shapes, and GBK
  with no declaration. Bytes are fixed, so `tests/fixtures/data/**` stays under `-text`.

### Fixed

- `run_ps.py` no longer cleans a temp directory silently on failure: it warns with the
  directory name only, never the script text, and leaves the child's exit code alone.
- Four documentation corrections: `$OutputEncoding` only governs stdin piped into a
  native program, not command-line arguments; file, console, pipeline and argv are four
  independent encoding layers; "UTF-8 BOM is the only form both sides accept" became
  "the recommended form" (UTF-16 with a BOM runs on both versions but other tools cannot
  read it); `Get-WinScriptEnvironment.ps1` is marked as once per machine, not a
  per-task diagnostic.

## [1.0.1] - 2026-11-12

Stability fix. Three encoding verdict errors from 1.0.0, `run_ps.py`'s ambiguous file
semantics, and the writer's default contradicting its own specification — all fixed
here, each replaced with a measure-then-decide implementation.

### Changed (behaviour change, read this)

- **`Test-ScriptEncoding.ps1` moves UTF-16 scripts from `FAIL` to `WARN`.** The 1.0.0
  reason was "Windows PowerShell 5.1 cannot reliably parse UTF-16 scripts", which was
  never verified and is false: measured, 5.1.26100 and 7.7.0 both parse and run UTF-16LE
  and UTF-16BE scripts with a BOM, Chinese included. `WARN` expresses "runs, not
  recommended" — `cmd.exe`, `git diff` and most editors read single bytes. What is really
  impossible is UTF-16 **without** a BOM, which still `FAIL`s.
  **Impact:** exit code `2` → `1` when checking UTF-16LE/BE files with `-Profile ps51` /
  `ps7`; callers using `-FailOnWarning` still see `2`.
- **`New-EncodedScript.ps1` derives its default encoding from the extension.** 1.0.0
  defaulted to `utf8-nobom` for every target, so writing a `.ps1` with Chinese produced
  exactly the file the detector (`-Profile ps51`) fails — two tools contradicting each
  other. Now `.ps1` / `.psm1` / `.psd1` → `utf8-bom`, `.bat` / `.cmd` → `gbk`,
  everything else → `utf8-nobom`; an explicit `-Encoding` always wins. Results gain
  `ENCODING_SOURCE=explicit|extension`.
- **`run_ps.py` usage errors exit `3` instead of `2`.** argparse defaults to 2, which
  collides with "the child exited 2".

### Added

- **`run_ps.py --invoke-file <path>`: an execution mode that keeps the real file
  context.** The path goes to the child's `-File` untouched — the file is not read,
  decoded, copied or rewritten — so `$PSScriptRoot`, `$PSCommandPath`,
  `$MyInvocation.MyCommand.Path`, `param()`, `[CmdletBinding()]` and relative
  dot-sourcing all behave natively. Everything after `--script-args` is forwarded as
  given (argv list, no shell). Mutually exclusive with `--console-encoding` /
  `--input-encoding` / `--command` / `--file` / `--stdin` / positional arguments; a
  conflict exits `3` and says why.
- Detector output gains `PAYLOAD_VALID` and `PAYLOAD_PROBLEM`; encoding names gain
  `utf8-bom-invalid` / `utf16le-bom-invalid` / `utf16be-bom-invalid`.
- `tests/cp936/verify-local.ps1`: runs every CP936 gate check on a real zh-CN machine in
  one pass, with no self-hosted runner to register.
- `tests/integration/test_package.py`: unpacks the release archive and actually runs the
  tools inside it.
- `test.yml` gains a `python-utf8-mode` job: `PYTHONUTF8=1` simulates Python 3.15's
  default UTF-8 mode (PEP 686) to confirm behaviour does not regress when the defaults
  change.

### Fixed

- **A UTF-8 BOM was treated as proof the file is UTF-8, with the bytes after it never
  checked.** `EF BB BF FF`, `EF BB BF C3 28` and `EF BB BF E4 B8` all returned
  `ENCODING=utf8-bom`, `STRICT_UTF8=True`, `VERDICT=OK`, exit 0. A BOM is a declaration,
  not proof that the content is valid; everything after it is now strictly decoded, and
  a failure gives `FAIL` with the offset of the first bad byte. The same applies to
  UTF-16 BOMs, plus separate checks for odd byte counts and lone surrogates.
- **`-ExpectedEncoding ascii` and `utf8-nobom` were treated as mutually compatible.** A
  file with 18 non-ASCII bytes passed `-ExpectedEncoding ascii` under `-Profile ps7`, and
  the output contained the self-contradicting pair `EXPECTED_MATCH=True` with
  `VERDICT=FAIL`. ascii now means "every byte is in 0x00–0x7F", and the relation is
  asymmetric: pure ASCII satisfies `utf8-nobom`, not the other way round; a BOM is not
  ASCII.
- **`run_ps.py --file`'s file context changed with script length.** Short scripts go
  through `-EncodedCommand` with an empty `$PSScriptRoot`; long ones are written to a temp
  file and run with `-File`, so `$PSScriptRoot` becomes the temp directory. The same
  script changed semantics by length, with no warning. The fallback now prints three
  `run_ps.py: note:` lines on stderr naming `--invoke-file`.
- **The writer's backup file could be overwritten.** Backup names were second-resolution
  timestamps and `File.Replace` overwrites an existing file, so two writes in the same
  second destroyed the first backup. A collision now appends a sequence number.
- **A failed write still printed `WROTE=<path>`.** On the failure path "written" is the
  line most likely to be believed; the field is now omitted when the exit code is
  non-zero.
- `run_ps.py` no longer throws when creating or cleaning its temp directory: the former
  returns 3, the latter preserves the child's exit code.

### Verified

- Full matrix run once each on Windows PowerShell 5.1.26100 (Desktop) and PowerShell
  7.7.0 (Core): Pester 77, Python 47, docs contract 38, integration 22,
  PSScriptAnalyzer 12 files 0 warnings.
- CP936: this machine has ACP=936, `CP936_ASSERTIONS_EXECUTED`. **The `cp936` workflow on
  GitHub still has not run** — the repository has no self-hosted runner registered and no
  `CP936_RUNNER` variable set, so every push reports `skipped`. Skipped is not passed;
  see `tests/cp936/README.md`.
- Python 3.13.9 in default mode and under `PYTHONUTF8=1`
  (`sys.flags.utf8_mode=1`): Python 47 and integration 22, all passing. **No 3.15
  interpreter is available and Python 3.15 itself is unverified**; the
  `python-utf8-mode` job only simulates its defaults.
- Release archive: 18 entries, all forward slashes, no `.pyc` and no test material, every
  entry byte-identical to the checkout; unpacked into a clean directory, all four tools
  ran, and `--invoke-file`'s `$PSScriptRoot` pointed at the script's own directory.
  (The archive size is deliberately not written here: it changes with this document, so
  quoting it would be self-referential.)
- `git diff --check origin/main..HEAD` reports nothing.

## [1.0.0] - 2026-11-11

The first version rewritten against a contract. 0.1.0 was a rule document for humans plus
two scripts; 1.0.0 splits it into four layers — entry, references, tools, tests — with
every claim backed by a measurement or a test.

### Added

- `scripts/Get-WinScriptEnvironment.ps1`: read-only self-check reporting ACP / OEMCP /
  console input and output code pages / `$OutputEncoding` / `[Encoding]::Default` /
  CP936 availability / runtime version / `EXECUTIONPOLICY`. `-Output Json` gives a
  machine-readable report; a `WARNING=` line appears only when its condition holds.
- 10 references under `references/`, organised for progressive disclosure:
  `encoding-matrix`, `powershell-51`, `powershell-7`, `dual-version-compatibility`,
  `cmd-bat`, `python`, `git-bash`, `execution`, `security`, `troubleshooting`.
- `tests/analyze.ps1` and `tests/run-all.ps1 -Suite analyze`: static analysis becomes a
  member of the test matrix instead of a command you remember to run. Scope grows from
  `scripts/` to `scripts/` + `tests/`, with the test tree excluding
  `PSUseDeclaredVarsMoreThanAssignments` (Pester 5's `BeforeAll` scope makes genuinely
  used variables look unused) and `tests/fixtures/data` skipped wholesale as test
  payload.
- `tests/package.ps1`: release packaging and release-note generation, rerunnable
  locally. CI's release job calls it instead of encoding logic in YAML.
- Three workflows: `test.yml` (5.1 / 7 × Python 3.11 / 3.13 matrix + docs contract),
  `cp936.yml` (self-hosted 936 runner; fails instead of skipping when the host is not
  936), `release.yml` (only on a `v*` tag).
- `CONTRIBUTING.md` and this `CHANGELOG.md`.

### Changed

- `SKILL.md` goes from an 8.5 KB monolith to a 5.3 KB entry file: routing table, four
  hard rules, tool list and boundary statement only. Every detail moves down into
  `references/`.
- `README.md` rewritten: quick start, the four tools' exit-code contract, installation,
  verified scope.
- `tests/integration/test_pipeline.py` no longer assumes the child always encodes stdout
  as CP936. Asserting raw GBK bytes produced false failures as soon as a host switched
  its console to UTF-8; it now reads the real code page via `GetConsoleOutputCP()` and
  asserts characters.

### Fixed

- **`run_ps.py --console-encoding` made `param()` fail silently.** The prelude was
  prefixed to the user's script, but `param(...)` and `[CmdletBinding()]` are only legal
  as the first statement, so PowerShell reported
  `param : The term 'param' is not recognized`, **finished the remaining statements and
  exited 0**. A real script with a parameter block lost all its parameters silently when
  run through `--file`. The body is now wrapped in `& { … }` only when a prelude must be
  injected; the default path is byte-identical. Three cases were added: `param()` is not
  displaced, the prelude still works inside the wrapper, and a trailing comment does not
  swallow the closing `}`.
- **The detector silently returned `files=0` when `-File` came with redirected stdin.**
  Windows PowerShell skips the `process` block while binding parameters successfully, so
  the script never opened a file yet exited 0. Per-file work is now extracted into
  `Add-Inspection` and re-run from `end` while `$script:pipelineRan` is still false.
- **The packager wrote release notes as mojibake.** `Get-Content` without `-Encoding`
  has 5.1 decode this UTF-8 `CHANGELOG.md` as CP936, corrupting all the Chinese. This was
  the first broken link recorded in this repository, and it was in the repository's own
  build script.
- **`Compress-Archive` on 5.1 writes zip entry names with backslashes**
  (`win-script-writer\SKILL.md`), which violates APPNOTE and turns into a single file
  whose name contains a backslash on spec-conforming extractors. Packaging now calls
  `ZipFileExtensions::CreateEntryFromFile` per entry with the separator normalised to `/`,
  reopens the archive to verify, and fails with a non-zero exit code if a backslash
  appears.
- **Static analysis only warned on a parameter-binding failure and still reported
  `ANALYZER_CLEAN`.** `Invoke-ScriptAnalyzer -Path` does not accept a file array, the
  binding failure is non-terminating, and it was being swallowed. Every call now uses
  `-ErrorAction Stop` and prints `ANALYZED_FILES=`; analysing 0 files counts as failure.
- `New-EncodedScript.ps1` failed with "The path is not of a legal form" when overwriting,
  because `File.Replace` received `$null` and bound it as an empty string. It now uses a
  one-shot backup path cleaned up in `finally`.
- The `invalid-bytes.bin` fixture used `0xFF` as its invalid byte, but CP936 in .NET has
  no undefined bytes (`0xFF` → `U+F8F5`), so it was correctly judged gbk. It now uses
  `0x81 0x20` (lead byte plus illegal trail byte).
- Every use of three-argument `Join-Path`, unavailable on 5.1, was removed from tests and
  tools.
- Two dead variables in `tests/Common/TestHelpers.ps1` (`RepoRootPath`, `buffer`) and one
  empty `catch` block.
- **The CI workflow fed a matrix expression to the `shell` key.** GitHub resolves
  `jobs.<id>.steps[*].shell` before expanding the matrix, so `shell: ${{ matrix.shell }}`
  was rejected as `Unrecognized named-value: 'matrix'` — the first push failed in 0
  seconds with no job started. Each host now gets its own job and `shell` is always a
  literal. The same place fixed 7 installing modules into `Documents/PowerShell/Modules`
  while 5.1 only looks in `Documents/WindowsPowerShell/Modules`: sharing one install step
  meant the 5.1 path silently fell back to the bundled Pester 3.4.
- **Test dependency resolution was scattered across every entry point; missing one turned
  the build red.** The docs contract parses workflow files and needs PyYAML; the matrix
  job installed it and the release job did not, so a green branch failed 1m40s after
  tagging. It is now probed and installed in the test entry script, with every entry point
  sharing one path. Two traps along the way: `$ErrorActionPreference = 'Stop'` turns a
  native program's stderr into a terminating error, so an "expected to fail" probe aborted
  the script; and `pip install yaml` finds no distribution — the module is `yaml`, the
  distribution is `PyYAML` — and a successful install still has to be re-probed, because
  pip returning 0 never proves `import` will work.
- **`scripts/__pycache__/*.pyc` got into the release archive.** Packaging copied the
  directory and the local checkout was clean, so ten manual runs all produced 18 entries;
  CI ran tests in the same checkout first, left bytecode caches behind and shipped 19.
  Caches are now cleared before archiving and entries are checked against an extension
  allowlist — a denylist only stops what you already thought of. The same release exposed
  `if ($LASTEXITCODE -ne 0)` judging a successful packaging as failed: a successful script
  does not set `$LASTEXITCODE`, `$null -ne 0` is true, and the message printed as
  "packaging failed with " followed by nothing.

### Security

- Six default-immutable behaviours are stated and documented: no injected
  `-ExecutionPolicy Bypass`, no overwriting files by default, no automatic `ACP` change,
  no self-elevation, `run_ps.py` is not a sandbox, and no silent character substitution.
  See `references/security.md`.

### Verified

Every number in this release was measured in this environment: Windows 11 Simplified
Chinese, ACP=936, OEMCP=936, Windows PowerShell 5.1.26100 (Desktop), PowerShell 7.6.9
(Core), Pester 5.7.1, PSScriptAnalyzer 1.24.0, Python 3.13.

- Pester: 50, once on 5.1 and once on 7, all passing.
- Python: 29, all passing.
- Integration: 7, all passing (3 CP936-specific ones skipped on a non-936 host).
- Docs contract: 28, all passing.
- PSScriptAnalyzer: `scripts/` fully clean on both hosts.
- GitHub Actions: 5.1 and 7 each with Python 3.11 / 3.13 on `windows-latest`, all four
  combinations `RESULT=PASSED`; docs contract on `ubuntu-latest`. The CP936 gate needs a
  runner labelled `self-hosted, windows, cp936`; when none is configured the job shows
  skipped rather than queueing forever.

## [0.1.0] - 2026-11-09

First public version.

### Added

- A Chinese-Windows encoding rule document (`SKILL.md`).
- `scripts/Test-ScriptEncoding.ps1`: BOM / non-ASCII / strict UTF-8 detection.
- `scripts/New-EncodedScript.ps1`: write to disk in a chosen encoding.
- `scripts/run_ps.py`: UTF-16LE base64 transport that sidesteps the command-line code
  page.
- The measured comparison table of four ways to save a `.bat` / `.cmd`.
