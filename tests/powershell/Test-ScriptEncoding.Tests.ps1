#Requires -Version 5.1
<#
    Contract tests for scripts/Test-ScriptEncoding.ps1.

    Every assertion goes through the process boundary so that the `exit` codes
    the tool produces are the ones being verified, in both runtimes.
#>

BeforeAll {
    . ([System.IO.Path]::Combine($PSScriptRoot, '..', 'Common', 'TestHelpers.ps1'))

    $Tool = 'Test-ScriptEncoding.ps1'

    function Invoke-Tool {
        param([string[]]$Arguments)
        Invoke-WsTool -Name $Tool -Arguments $Arguments
    }

    function Get-Field {
        param([string]$Text, [string]$Key)
        $m = [regex]::Match($Text, ('(?m)^' + [regex]::Escape($Key) + '=(.*)$'))
        if (-not $m.Success) { return $null }
        return $m.Groups[1].Value.Trim()
    }
}

Describe 'Test-ScriptEncoding.ps1' {

    Context 'BOM detection' {

        It 'accepts UTF-8 with BOM' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8bom.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-bom'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
        }

        It 'warns on UTF-16LE with BOM instead of claiming it cannot run' {
            # Both runtimes do parse and run it; verified on 5.1.26100 and
            # 7.6.9. The old assertion demanded FAIL for a file that executes
            # correctly, which is a verdict nobody could act on.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf16le-bom.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16le-bom'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            $r.StdOut | Should -Match 'UTF16LE_RUNNABLE_NOT_PREFERRED'
        }

        It 'warns on UTF-16BE with BOM for the same reason' {
            # Same measurement: the FE FF mark is honoured and the script runs.
            # Not preferred is a portability statement, not a parse failure.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf16be-bom.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16be-bom'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            $r.StdOut | Should -Match 'UTF16BE_RUNNABLE_NOT_PREFERRED'
        }

        It 'fails UTF-16LE without a BOM, which really does not run' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf16le-nobom.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16le-no-bom-suspected'
            $r.StdOut | Should -Match 'UTF16_NO_BOM'
        }

        It 'fails UTF-16BE without a BOM too' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf16be-nobom.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16be-no-bom-suspected'
            $r.StdOut | Should -Match 'UTF16_NO_BOM'
        }
    }

    Context 'BOM payload validation' {

        It 'accepts a BOM with an empty payload' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf8bom-empty.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-bom'
            Get-Field $r.StdOut 'PAYLOAD_VALID' | Should -Be 'True'
        }

        It 'accepts a BOM followed by ASCII' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf8bom-ascii.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-bom'
        }

        It 'fails a BOM followed by FF' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf8bom-invalid-ff.bin'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-bom-invalid'
            Get-Field $r.StdOut 'PAYLOAD_VALID' | Should -Be 'False'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
            $r.StdOut | Should -Match 'INVALID_ENCODING_PAYLOAD'
            $r.StdOut | Should -Match 'byte 3'
        }

        It 'fails a BOM followed by C3 28' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf8bom-invalid-continuation.bin'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-bom-invalid'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
        }

        It 'fails a BOM followed by an incomplete multi-byte sequence' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf8bom-incomplete-sequence.bin'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-bom-invalid'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
        }

        It 'fails a UTF-16LE BOM with an odd byte count' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf16le-bom-truncated.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16le-bom-invalid'
            $r.StdOut | Should -Match 'truncated'
        }

        It 'fails a UTF-16LE BOM with an unpaired surrogate' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf16le-bom-lone-surrogate.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16le-bom-invalid'
            $r.StdOut | Should -Match 'INVALID_ENCODING_PAYLOAD'
        }

        It 'reports the same verdict for a damaged payload under every profile' {
            $path = Join-Path $FixturesDir 'utf8bom-invalid-ff.bin'
            foreach ($profileName in @('ps51', 'ps7', 'cmd', 'python', 'bash', 'data')) {
                $r = Invoke-Tool @('-Path', $path, '-Profile', $profileName)
                $r.ExitCode | Should -Be 2 -Because ("profile $profileName must not rate a corrupt payload as readable")
            }
        }
    }

    Context 'BOM-less classification' {

        It 'accepts an ascii-only script' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-ascii.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
        }

        It 'fails BOM-less UTF-8 with CJK under the ps51 profile' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8nobom-cn.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-nobom'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
            $r.StdOut | Should -Match 'BOMLESS_UTF8_PS51'
        }

        It 'accepts the same file under the ps7 profile' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8nobom-cn.ps1'), '-Profile', 'ps7')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
        }

        It 'identifies CP936 and warns instead of claiming it is fine' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-gbk-cn.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'gbk'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'CONFIDENCE' | Should -Not -BeNullOrEmpty
        }

        It 'reports UNKNOWN rather than guessing GBK' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'invalid-bytes.bin'), '-Profile', 'data')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'unknown'
            Get-Field $r.StdOut 'CONFIDENCE' | Should -Be 'low'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
        }

        It 'detects UTF-16LE without a BOM by NUL pattern' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf16le-nobom.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16le-no-bom-suspected'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
        }
    }

    Context 'profile rules' {

        It 'accepts a CP936 batch file for the cmd profile' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'bat-gbk-cn.bat'), '-Profile', 'cmd')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
        }

        It 'fails a UTF-8 BOM batch file' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'bat-utf8bom-cn.bat'), '-Profile', 'cmd')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
            $r.StdOut | Should -Match 'CMD_UTF8_BOM'
        }

        It 'warns on a BOM-less UTF-8 batch file with CJK' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'bat-utf8nobom-cn.bat'), '-Profile', 'cmd')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
        }

        It 'accepts ascii batch files' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'bat-ascii.bat'), '-Profile', 'cmd')
            $r.ExitCode | Should -Be 0
        }

        It 'accepts UTF-8 no BOM python and fails CP936 python' {
            $ok = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-utf8nobom.py'), '-Profile', 'python')
            $ok.ExitCode | Should -Be 0
            $bad = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-gbk.py'), '-Profile', 'python')
            $bad.ExitCode | Should -Be 2
            Get-Field $bad.StdOut 'VERDICT' | Should -Be 'FAIL'
        }

        It 'accepts UTF-8 no BOM bash and json' {
            (Invoke-Tool @('-Path', (Join-Path $FixturesDir 'sh-utf8nobom.sh'), '-Profile', 'bash')).ExitCode | Should -Be 0
            (Invoke-Tool @('-Path', (Join-Path $FixturesDir 'data-utf8nobom.json'), '-Profile', 'data')).ExitCode | Should -Be 0
        }

        It 'derives the profile from the extension when auto is used' {
            $ps = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8nobom-cn.ps1'))
            Get-Field $ps.StdOut 'PROFILE' | Should -Be 'ps51'
            $bat = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'bat-utf8bom-cn.bat'))
            Get-Field $bat.StdOut 'PROFILE' | Should -Be 'cmd'
            $py = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-gbk.py'))
            Get-Field $py.StdOut 'PROFILE' | Should -Be 'python'
        }
    }

    Context 'Python source encoding declarations' {

        It 'warns on declared CP936 source instead of failing it' {
            # PEP 263 makes this legal Python. It is still not the storage this
            # project wants, so it warns rather than passing silently.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gbk.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING' | Should -Be 'gbk'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_DECLARED'
        }

        It 'reads the coding=name spelling too' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-equals.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'SOURCE_CODING' | Should -Be 'cp936'
        }

        It 'reports which line carries the declaration' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gbk.py'), '-Profile', 'python')
            Get-Field $r.StdOut 'SOURCE_CODING_LINE' | Should -Be '1'
        }

        It 'still fails CP936 source that declares nothing' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-nocoding-gbk.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'SOURCE_CODING' | Should -BeNullOrEmpty
            $r.StdOut | Should -Match 'CP936_PYTHON'
        }

        It 'fails when the declaration contradicts the BOM' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-conflict-bom.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_BOM_CONFLICT'
        }

        It 'fails a declaration naming a codec that does not exist' {
            # ASCII body, so a detector that only looked at the bytes would call
            # it OK. Python raises SyntaxError for the declaration alone.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-unknown.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNKNOWN'
        }

        It 'does not read a declaration out of another profile' {
            # A .txt that happens to start with "# coding: gbk" is not Python.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gbk.py'), '-Profile', 'data')
            Get-Field $r.StdOut 'SOURCE_CODING' | Should -BeNullOrEmpty
        }
    }

    Context 'Python codec families' {

        It 'resolves <Declaration> to <Canonical> and warns' -ForEach @(
            @{ File = 'py-coding-gbk.py'; Declaration = 'gbk'; Canonical = 'gbk' }
            @{ File = 'py-coding-equals.py'; Declaration = 'cp936'; Canonical = 'gbk' }
            @{ File = 'py-coding-gb2312.py'; Declaration = 'gb2312'; Canonical = 'gb2312' }
            @{ File = 'py-coding-euc-cn.py'; Declaration = 'euc-cn'; Canonical = 'gb2312' }
            @{ File = 'py-coding-hz.py'; Declaration = 'hz'; Canonical = 'hz' }
            @{ File = 'py-coding-gb18030.py'; Declaration = 'gb18030'; Canonical = 'gb18030' }
        ) {
            # A real interpreter runs every one of these to exit 0, so the only
            # acceptable answer here is WARN. v1.0.2 folded gb2312 and hz into
            # gbk, called the HZ file plain ASCII and refused the GB18030 one.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING' | Should -Be $Declaration
            Get-Field $r.StdOut 'SOURCE_CODING_NAME' | Should -Be $Canonical
        }

        It 'rejects GBK only bytes under a gb2312 declaration' {
            # 81 40 is assigned in GBK and nowhere in GB2312. Validating the
            # declaration with CP936 accepted it; Python raises SyntaxError.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gbk-as-gb2312.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_INVALID_BYTES'
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'bytes-mismatch'
        }

        It 'accepts GB2312 bytes under the wider gbk declaration' {
            # The subset direction must keep working: every GB2312 body is a
            # legal GBK body, so this is not a conflict and not an ambiguity.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gb2312.py'), '-Profile', 'python')
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'gbk'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_AMBIGUOUS'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_INVALID_BYTES'
            $r.ExitCode | Should -Be 1
        }

        It 'rejects the codec name <Name>, which CPython does not resolve' -ForEach @(
            @{ File = 'py-coding-windows936.py'; Name = 'windows-936' }
            @{ File = 'py-coding-cp54936.py'; Name = 'cp54936' }
        ) {
            # 936 and 54936 are code pages. A codec name has to be looked up in
            # Python, and neither of these resolves, so the file never compiles.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNKNOWN'
            $r.StdOut | Should -Match ([regex]::Escape($Name))
        }

        It 'warns that an HZ body is escape text rather than CJK' {
            # The file is seven bit, so the byte detector calls it ASCII and the
            # generic ASCII case would pass it silently.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'ascii'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_HZ'
        }

        It 'fails HZ that never leaves the GB run' {
            # A decoder left inside GB mode at end of file has a truncated
            # character. All the bytes are still ASCII, so nothing but the state
            # machine can see it.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz-truncated.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_INVALID_BYTES'
        }

        It 'leaves an ordinary UTF-8 source file alone' {
            # The regression guard for this whole change: none of it may move a
            # plain UTF-8 file off OK.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-utf8nobom.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-nobom'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
        }
    }

    Context 'HZ state machine' {

        It 'accepts a GB pair whose second byte is 0x7E' {
            # 56 7E shifts up to D6 FE, a real GB2312 cell. A machine that tests
            # for the tilde before it looks at the mode refuses this file, and
            # the interpreter runs it (exit 0).
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz-tilde-in-gb.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_INVALID_BYTES'
        }

        It 'accepts a line continuation in ASCII mode' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz-continuation.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_INVALID_BYTES'
        }

        It 'refuses <Case>, which the interpreter refuses too' -ForEach @(
            # CPython 3.13 raises UnicodeDecodeError for all three. The escapes
            # are legal in ASCII mode only, and a single byte with no partner is
            # not a cell.
            @{ File = 'py-coding-hz-escape-in-gb.py'; Case = '~~ inside GB mode' }
            @{ File = 'py-coding-hz-close-in-ascii.py'; Case = '~} outside GB mode' }
            @{ File = 'py-coding-hz-truncated.py'; Case = 'a dangling byte after a GB run' }
        ) {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_INVALID_BYTES'
        }

        It 'notes a run left open instead of failing it' {
            # The interpreter decodes a file that ends inside GB mode as long as
            # the last pair is complete, so failing it would be a false alarm.
            # The open state is still worth saying out loud.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz-open.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            $r.StdOut | Should -Match 'ends inside GB mode'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_INVALID_BYTES'
        }

        It 'still reports the escape text of a well formed HZ file' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_HZ'
        }

        It 'leaves plain ASCII alone' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-ascii.ps1'), '-Profile', 'python')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
        }
    }

    Context 'overlapping encodings' {

        It 'marks <Declaration> bytes that are also UTF-8 as ambiguous, not as a conflict' -ForEach @(
            # C3 A9 is U+8305 in all three Chinese codecs and U+00E9 in UTF-8. The
            # interpreter decodes with the declaration and exits 0, so a FAIL
            # here is a false alarm about a file that runs.
            @{ File = 'py-coding-gb2312-overlap.py'; Declaration = 'gb2312' }
            @{ File = 'py-coding-gbk-overlap.py'; Declaration = 'gbk' }
            @{ File = 'py-coding-gb18030-overlap.py'; Declaration = 'gb18030' }
        ) {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING' | Should -Be $Declaration
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_AMBIGUOUS'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_CONFLICT'
        }

        It 'still fails bytes the declared codec cannot decode' {
            # UTF-8 CJK is not GBK at all: CP936 stops at 0xAD, which is a legal
            # CP936 lead and an unassigned GBK cell. The interpreter exits 1.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-utf8-as-gbk.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_INVALID_BYTES'
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'bytes-mismatch'
        }

        It 'still fails a gb2312 declaration over GBK only bytes' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gbk-as-gb2312.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_INVALID_BYTES'
        }

        It 'keeps the subset direction quiet' {
            # A GB2312 body is a legal GBK body, so the detector's own gbk label
            # sits inside the declared repertoire and nothing is ambiguous.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gb2312.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_DECLARED'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_AMBIGUOUS'
        }
    }

    Context 'Latin-1 declarations' {

        It 'accepts a non-ASCII Latin-1 file the interpreter runs' {
            # ISO-8859-1 has no invalid byte sequence, and 0xE9 is not valid
            # UTF-8, so nothing but the declaration can explain these bytes.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-latin1.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING_NAME' | Should -Be 'latin-1'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_DECLARED'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_CONFLICT'
        }

        It 'leaves an ASCII file declared as Latin-1 alone' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-latin1-ascii.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
        }

        It 'marks UTF-8 bytes declared as Latin-1 as ambiguous' {
            # The file runs (exit 0) and prints mojibake, so neither FAIL nor a
            # silent OK is right.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-latin1-utf8.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_AMBIGUOUS'
        }

        It 'fails a BOM under a Latin-1 declaration' {
            # CPython: SyntaxError: encoding problem: iso-8859-1 with BOM.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-latin1-bom.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_BOM_CONFLICT'
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'bom-conflict'
        }
    }

    Context 'codec name classification' {

        It 'warns instead of failing on <Name>, which CPython resolves and this tool cannot verify' -ForEach @(
            @{ File = 'py-coding-cp1252.py'; Name = 'cp1252' }
            @{ File = 'py-coding-shift-jis.py'; Name = 'shift_jis' }
            @{ File = 'py-coding-big5.py'; Name = 'big5' }
        ) {
            # The interpreter runs every one of these files (exit 0). Calling the
            # name unknown was a false alarm of the worst kind: it told the user
            # Python would refuse a file Python executes.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING' | Should -Be $Name
            Get-Field $r.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'python-only'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNVERIFIED'
        }

        It 'fails <Name>, which no CPython 3 release resolves' -ForEach @(
            @{ File = 'py-coding-54936.py'; Name = '54936' }
            @{ File = 'py-coding-hzgb2312.py'; Name = 'hzgb2312' }
            @{ File = 'py-coding-cn-gb.py'; Name = 'cn-gb' }
        ) {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNKNOWN'
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'unknown-name'
            $r.StdOut | Should -Match ([regex]::Escape($Name))
        }

        It 'treats utf-8-sig as UTF-8, which is what it is' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-utf8-sig.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
            Get-Field $r.StdOut 'SOURCE_CODING_NAME' | Should -Be 'utf-8'
        }

        It 'fails the utf8 spelling of utf-8 when a BOM is present' {
            # CPython normalises the name before comparing it with "utf-8", and
            # "utf8" does not survive that comparison: the file raises
            # "encoding problem: utf8 with BOM". The spelling decides.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-utf8-spelling-bom.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_BOM_CONFLICT'
        }

        It 'reports a BOM conflict for a name CPython does not resolve either' {
            # The BOM is checked before the codec is looked up, so the
            # interpreter says "encoding problem: windows-936 with BOM" and not
            # "unknown codec". Both fail; naming the right one is the point.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-unknown-bom.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'bom-conflict'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_BOM_CONFLICT'
            $r.StdOut | Should -Match 'with BOM'
        }
    }

    Context 'codec name table' {

        BeforeAll {
            # A declaration on its own is enough: the interpreter decides whether
            # the name resolves before it reads any body, and so does the tool.
            function New-CodecNameProbe {
                param([string]$Codec)
                $safe = ($Codec -replace '[^A-Za-z0-9]', '_')
                $path = Join-Path $TestDrive ('probe-' + $safe + '.py')
                $body = '# -*- coding: ' + $Codec + ' -*-' + "`n" + 's = "A"' + "`n"
                [System.IO.File]::WriteAllText($path, $body, (New-Object System.Text.UTF8Encoding($false)))
                return $path
            }
        }

        It 'fails <Codec>, which no CPython 3 release resolves' -ForEach @(
            @{ Codec = 'mac-bogus' }
            @{ Codec = 'shift_jis_typo' }
            @{ Codec = 'big5-nope' }
            @{ Codec = 'ibm99999' }
        ) {
            # These four are the reason the family patterns are gone. '^mac[a-z]*$'
            # and '^ibm[0-9]{3,5}$' matched all of them, so v1.0.3 called a file
            # the interpreter refuses merely unverified.
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec $Codec), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'unknown-name'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNKNOWN'
        }

        It 'fails <Codec>, which looks like an alias and is not one' -ForEach @(
            @{ Codec = 'mac' }
            @{ Codec = 'macos' }
            @{ Codec = 'macx' }
            @{ Codec = 'iso_646_us' }
            @{ Codec = 'jisx0208' }
            @{ Codec = 'x_mac_cyrillic' }
            @{ Codec = 'pt_154' }
            @{ Codec = 'cshproman8' }
            @{ Codec = 'utf-8.unix' }
        ) {
            # utf-8.unix is the one that used to be wrong in the other direction:
            # the normaliser cut the name at the first '.', so it read as a plain
            # utf-8 declaration and passed. The interpreter looks up the whole
            # spelling and finds nothing.
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec $Codec), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'unknown-name'
        }

        It 'accepts <Codec>, which CPython resolves and cannot verify' -ForEach @(
            @{ Codec = 'cp1252' }
            @{ Codec = 'shift_jis' }
            @{ Codec = 'big5' }
            @{ Codec = 'mac-roman' }
            @{ Codec = 'latin2' }
            @{ Codec = 'euc-jp' }
            @{ Codec = 'ansi' }
        ) {
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec $Codec), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'python-only'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNVERIFIED'
        }

        It 'carries the aliases a newer patch of the same minor added' -ForEach @(
            @{ Codec = 'cp858' }
            @{ Codec = 'cp00858' }
            @{ Codec = 'csibm00858' }
            @{ Codec = 'ibm00858' }
            @{ Codec = 'pc_multilingual_850_euro' }
        ) {
            # gh-149801 added these four spellings for cp858 and they ship from
            # 3.13.14 on, so 3.13.9 has none of them. A table built by copying
            # one host's stdlib rejects a file written on the newer patch --
            # that is how CI found this, on a runner whose 3.13.17 reported 479
            # aliases against this host's 471. Accepting a spelling the local
            # interpreter cannot resolve costs a WARN and an unverified
            # payload, which is the honest answer.
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec $Codec), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'python-only'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNVERIFIED'
            $r.StdOut | Should -Match 'SOURCE_CODING_PAYLOAD=unverified'
        }

        It 'does not claim the running interpreter resolves <Codec>' -ForEach @(
            @{ Codec = 'cp00858' }
            @{ Codec = 'csibm00858' }
            @{ Codec = 'shift_jis' }
            @{ Codec = 'cp1252' }
        ) {
            # The table is a union over the releases in the matrix, so a hit
            # means "some verified CPython resolves this", not "this host does":
            # 3.14.6 gave cp858 the spelling cp00858 (gh-149801) and 3.11/3.13.9
            # reject it with "unknown encoding". The old sentence said "CPython
            # recognizes this codec" -- true of the set, false of the
            # interpreter in front of the user. The verdict stays WARN and the
            # payload stays unverified; only the claim gets narrower.
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec $Codec), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING_PAYLOAD' | Should -Be 'unverified'
            $r.StdOut | Should -Match 'compatibility set'
            $r.StdOut | Should -Match 'may not resolve it'
            $r.StdOut | Should -Match 'may still fail during decoding'
            $r.StdOut | Should -Not -Match 'CPython recognizes this codec'
        }

        It 'calls <Codec> a transform and not an unknown name' -ForEach @(
            @{ Codec = 'base64' }
            @{ Codec = 'base64_codec' }
            @{ Codec = 'rot13' }
            @{ Codec = 'rot_13' }
            @{ Codec = 'hex' }
            @{ Codec = 'zlib' }
            @{ Codec = 'uu' }
            @{ Codec = 'bz2' }
            @{ Codec = 'quopri' }
        ) {
            # codecs.lookup() resolves every one of these, so "unknown encoding"
            # sends the reader hunting for a typo that does not exist. What the
            # interpreter actually says is "'base64' is not a text encoding; use
            # codecs.decode() to handle arbitrary codecs". The verdict stays
            # FAIL: this is a diagnosis fix, not a relaxation.
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec $Codec), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'unusable-codec'
            Get-Field $r.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'unusable'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNUSABLE'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_UNKNOWN'
            $r.StdOut | Should -Match 'is not a text encoding'
        }

        It 'keeps a genuinely unknown name on the other code' {
            # The two reasons must not collapse into one: unknown-name says the
            # interpreter never found the codec, unusable-codec says it found it
            # and refused it. Same FAIL, different advice.
            $unknown = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec 'ghost-codec'), '-Profile', 'python')
            $unknown.ExitCode | Should -Be 2
            Get-Field $unknown.StdOut 'SOURCE_CODING_KIND' | Should -Be 'unknown-name'
            $unknown.StdOut | Should -Match 'PY_SOURCE_CODING_UNKNOWN'
            $unknown.StdOut | Should -Not -Match 'PY_SOURCE_CODING_UNUSABLE'

            $transform = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec 'base64'), '-Profile', 'python')
            Get-Field $transform.StdOut 'SOURCE_CODING_KIND' | Should -Be 'unusable-codec'
        }

        It 'keeps a text codec that merely looks like a transform on the warn path' {
            # idna is in deep-freeze aliases and resolves as a text codec, so it
            # is not a transform: an ASCII source really does compile under it.
            # Sweeping every codecs.lookup() result into unusable-codec would
            # mislabel it as "not a text encoding".
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec 'idna'), '-Profile', 'python')
            Get-Field $r.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'python-only'
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -BeNullOrEmpty
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_UNUSABLE'
        }

        It 'resolves a name longer than the twelve characters the tokenizer inspects' {
            # ansi-x3.4-1968 is 14 characters, and its first twelve are not a
            # codec. It resolves anyway, because get_normal_name only truncates
            # to decide the utf-8 and latin-1 families; every other spelling goes
            # to lookup as written. A table built from truncated keys would call
            # this unknown and fail a file the interpreter runs.
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec 'ansi-x3.4-1968'), '-Profile', 'python')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'OK'
            Get-Field $r.StdOut 'SOURCE_CODING_NAME' | Should -Be 'ascii'
            Get-Field $r.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'supported'
        }

        It 'separates latin2 from latin-2, which differ by more than punctuation' {
            # The separator is the whole difference: lookup normalises latin-2 to
            # latin_2, which has no module, while latin2 is an alias for
            # iso-8859-2. One runs, the other does not.
            $ok = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec 'latin2'), '-Profile', 'python')
            $ok.ExitCode | Should -Be 1
            Get-Field $ok.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'python-only'

            $bad = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec 'latin-2'), '-Profile', 'python')
            $bad.ExitCode | Should -Be 2
            Get-Field $bad.StdOut 'SOURCE_CODING_KIND' | Should -Be 'unknown-name'
        }

        It 'keeps the four Chinese families apart' -ForEach @(
            @{ Codec = 'gbk'; Name = 'gbk' }
            @{ Codec = 'gb2312'; Name = 'gb2312' }
            @{ Codec = 'hz'; Name = 'hz' }
            @{ Codec = 'gb18030'; Name = 'gb18030' }
            @{ Codec = 'cp936'; Name = 'gbk' }
            @{ Codec = 'euc-cn'; Name = 'gb2312' }
        ) {
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec $Codec), '-Profile', 'python')
            Get-Field $r.StdOut 'SOURCE_CODING_NAME' | Should -Be $Name
            Get-Field $r.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'supported'
        }

        It 'still refuses utf-16 and utf-32 as source encodings' -ForEach @(
            @{ Codec = 'utf-16' }
            @{ Codec = 'utf-16-le' }
            @{ Codec = 'utf-32' }
            @{ Codec = 'unicodebigunmarked' }
        ) {
            $r = Invoke-Tool @('-Path', (New-CodecNameProbe -Codec $Codec), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'unusable-codec'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_UNUSABLE'
        }
    }

    Context 'python-only payload state' {

        It 'marks <File> unverified instead of passing or failing it' -ForEach @(
            @{ File = 'py-coding-shift-jis-bytes.py'; Codec = 'shift_jis' }
            @{ File = 'py-coding-shift-jis-truncated.py'; Codec = 'shift_jis' }
            @{ File = 'py-coding-big5-bytes.py'; Codec = 'big5' }
            @{ File = 'py-coding-big5-truncated.py'; Codec = 'big5' }
            @{ File = 'py-coding-cp1252-bytes.py'; Codec = 'cp1252' }
            @{ File = 'py-coding-cp1252-undefined.py'; Codec = 'cp1252' }
        ) {
            # The same answer for a complete character and a truncated one, on
            # purpose. The detector has no table for these codecs, so it cannot
            # tell them apart -- and inventing a pass or a failure from a name it
            # resolved would be worse than saying so.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING_SUPPORT' | Should -Be 'python-only'
            Get-Field $r.StdOut 'SOURCE_CODING_PAYLOAD' | Should -Be 'unverified'
            $r.StdOut | Should -Match 'may still fail during decoding'
            # The old wording promised something the tool cannot know.
            $r.StdOut | Should -Not -Match 'the file runs'
        }

        It 'reports the same payload state in json as in text' {
            $path = Join-Path $FixturesDir 'py-coding-big5-truncated.py'
            $text = Invoke-Tool @('-Path', $path, '-Profile', 'python')
            $json = Invoke-Tool @('-Path', $path, '-Profile', 'python', '-Output', 'json')

            Get-Field $text.StdOut 'SOURCE_CODING_PAYLOAD' | Should -Be 'unverified'
            $document = $json.StdOut | ConvertFrom-Json
            $document.Files[0].SourceCodingPayload | Should -Be 'unverified'
            $document.Files[0].SourceCodingSupport | Should -Be 'python-only'
        }

        It 'leaves the payload key out when the question does not apply' {
            # Absent, not empty: a consumer that tests truthiness would read an
            # empty string two ways, and one of them is "verified".
            $json = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gbk.py'), '-Profile', 'python', '-Output', 'json')
            $document = $json.StdOut | ConvertFrom-Json
            ($document.Files[0].PSObject.Properties.Name -contains 'SourceCodingPayload') | Should -BeFalse

            $text = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-gbk.py'), '-Profile', 'python')
            Get-Field $text.StdOut 'SOURCE_CODING_PAYLOAD' | Should -BeNullOrEmpty
        }
    }

    Context 'HZ state machine boundaries' {

        It 'fails a line continuation inside GB mode, which the interpreter rejects' -ForEach @(
            @{ File = 'py-coding-hz-gb-newline.py'; Label = 'LF' }
            @{ File = 'py-coding-hz-gb-crlf.py'; Label = 'CRLF' }
        ) {
            # RFC 1843 allows ~LF in both modes. CPython does not: inside GB mode
            # the tilde starts a cell whose second byte is 0x0A, and 0x0A is not
            # in 0x21-0x7E. The interpreter wins, which is why both line endings
            # are pinned instead of one.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'python')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'SOURCE_CODING_KIND' | Should -Be 'bytes-mismatch'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_INVALID_BYTES'
        }

        It 'still accepts a line continuation in ASCII mode' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz-continuation.py'), '-Profile', 'python')
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING_NAME' | Should -Be 'hz'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_HZ'
        }

        It 'keeps warning about a run that ends inside GB mode' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz-open.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            $r.StdOut | Should -Match 'ends inside GB mode'
        }

        It 'keeps accepting 0x7E as the trail byte of a GB2312 cell' {
            # 56 7E shifts to D6 FE, a real cell. A machine that looks for the
            # tilde before it looks at the mode refuses this file.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'py-coding-hz-tilde-in-gb.py'), '-Profile', 'python')
            $r.ExitCode | Should -Be 1
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'WARN'
            Get-Field $r.StdOut 'SOURCE_CODING_NAME' | Should -Be 'hz'
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_HZ'
            $r.StdOut | Should -Not -Match 'PY_SOURCE_CODING_INVALID_BYTES'
        }
    }

    Context 'UTF-32 with a BOM' {

        It 'names <Encoding> and refuses it' -ForEach @(
            @{ File = 'utf32le-bom.ps1'; Encoding = 'utf32le-bom'; Bom = 'FFFE0000' }
            @{ File = 'utf32be-bom.ps1'; Encoding = 'utf32be-bom'; Bom = '0000FEFF' }
        ) {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $File), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be $Encoding
            Get-Field $r.StdOut 'BOM' | Should -Be $Bom
            $r.StdOut | Should -Match 'UTF32_UNSUPPORTED'
        }

        It 'never calls a four byte mark UTF-16' {
            # The defect: FF FE 00 00 matched the UTF-16LE branch first, so a
            # UTF-32LE file was reported as a broken UTF-16LE file.
            foreach ($file in 'utf32le-bom.ps1', 'utf32be-bom.ps1') {
                $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir $file), '-Profile', 'ps51')
                $r.StdOut | Should -Not -Match 'ENCODING=utf16'
            }
        }

        It 'still classifies a two byte mark as UTF-16' {
            # The control case: without it, "handles UTF-32" could have been
            # implemented by refusing every FF FE file.
            $le = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf16le-bom.ps1'), '-Profile', 'ps51')
            Get-Field $le.StdOut 'ENCODING' | Should -Be 'utf16le-bom'
            $be = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf16be-bom.ps1'), '-Profile', 'ps51')
            Get-Field $be.StdOut 'ENCODING' | Should -Be 'utf16be-bom'
            $le.StdOut + $be.StdOut | Should -Not -Match 'utf32'
        }

        It 'does not modify the UTF-32 file while inspecting it' {
            $path = Join-Path $FixturesDir 'utf32le-bom.ps1'
            $before = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
            [void](Invoke-Tool @('-Path', $path, '-Profile', 'ps51'))
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash | Should -Be $before
        }
    }

    Context 'ExpectedEncoding' {

        It 'fails when the declared encoding does not match' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8bom.ps1'), '-Profile', 'ps51', '-ExpectedEncoding', 'utf8-nobom')
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'EXPECTED_MISMATCH'
        }

        It 'passes when the declared encoding matches' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8bom.ps1'), '-Profile', 'ps51', '-ExpectedEncoding', 'utf8-bom')
            $r.ExitCode | Should -Be 0
        }

        It 'treats ascii as compatible with utf8-nobom' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-ascii.ps1'), '-Profile', 'ps51', '-ExpectedEncoding', 'utf8-nobom')
            $r.ExitCode | Should -Be 0
        }

        It 'fails the ascii expectation on BOM-less UTF-8 with CJK' {
            # Under ps7 the profile alone would answer OK, so a failure here can
            # only come from the expectation. The v1.0.0 detector had a
            # symmetric exception that answered "match" for exactly this pair.
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8nobom-cn.ps1'), '-Profile', 'ps7', '-ExpectedEncoding', 'ascii')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'EXPECTED_MATCH' | Should -Be 'False'
            $r.StdOut | Should -Match 'EXPECTED_MISMATCH'
            $r.StdOut | Should -Match 'non-ASCII bytes'
        }

        It 'fails the ascii expectation on a Latin-1 range character' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'utf8nobom-latin1.txt'), '-Profile', 'data', '-ExpectedEncoding', 'ascii')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-nobom'
            Get-Field $r.StdOut 'EXPECTED_MATCH' | Should -Be 'False'
        }

        It 'fails the ascii expectation on a file that carries a BOM' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8bom.ps1'), '-Profile', 'ps51', '-ExpectedEncoding', 'ascii')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'EXPECTED_MATCH' | Should -Be 'False'
            $r.StdOut | Should -Match 'BOM=EFBBBF'
        }

        It 'passes the ascii expectation on a pure ASCII file' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-ascii.ps1'), '-Profile', 'ps51', '-ExpectedEncoding', 'ascii')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'EXPECTED_MATCH' | Should -Be 'True'
        }

        It 'passes the ascii expectation on an empty file' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'empty.txt'), '-Profile', 'data', '-ExpectedEncoding', 'ascii')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'EXPECTED_MATCH' | Should -Be 'True'
        }

        It 'never reports a match together with a failed expectation' {
            # The v1.0.0 output could print EXPECTED_MATCH=True next to
            # VERDICT=FAIL. Both fields describe the same comparison, so they
            # have to agree, whichever way it goes.
            $ok = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-ascii.ps1'), '-Profile', 'ps51', '-ExpectedEncoding', 'utf8-bom')
            Get-Field $ok.StdOut 'EXPECTED_MATCH' | Should -Be 'False'
            $ok.StdOut | Should -Match 'EXPECTED_MISMATCH'
        }
    }

    Context 'output formats' {

        It 'emits machine readable json' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf8bom.ps1'), '-Profile', 'ps51', '-Output', 'Json')
            $r.ExitCode | Should -Be 0
            $doc = $r.StdOut | ConvertFrom-Json
            $doc.Files.Count | Should -Be 1
            $doc.Files[0].Encoding | Should -Be 'utf8-bom'
            $doc.Files[0].Verdict | Should -Be 'OK'
            $doc.Summary.ExitCode | Should -Be 0
            $doc.Verdict | Should -Be 'OK'
        }

        It 'reports the runtime that produced the result' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-ascii.ps1'))
            Get-Field $r.StdOut 'RUNTIME' | Should -Be $PSVersionTable.PSEdition
        }
    }

    Context 'exit codes and arguments' {

        It 'returns 3 for a missing file' {
            $r = Invoke-Tool @('-Path', (Join-Path $TestDrive 'does-not-exist.ps1'))
            $r.ExitCode | Should -Be 3
            $r.StdErr | Should -Match 'not found|NOT_FOUND'
        }

        It 'accepts an empty file as ascii' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'empty.txt'), '-Profile', 'data')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'BYTES' | Should -Be '0'
        }

        It 'promotes warnings to a failure with -FailOnWarning' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'invalid-bytes.bin'), '-Profile', 'data', '-FailOnWarning')
            $r.ExitCode | Should -Be 2
        }

        It 'aggregates multiple paths using the worst verdict' {
            $tool = Join-Path $ScriptsDir 'Test-ScriptEncoding.ps1'
            $a = Join-Path $FixturesDir 'ps51-utf8bom.ps1'
            $b = Join-Path $FixturesDir 'ps51-utf8nobom-cn.ps1'
            $snippet = "& '$tool' -Path @('$a', '$b') -Profile ps51"
            $r = Invoke-PsSnippet -Snippet $snippet
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'SUMMARY files=2'
        }

        It 'handles a directory containing CJK characters' {
            $dir = Join-Path $TestDrive ([string]([char]0x4E2D) + [char]0x6587)
            $copy = New-FixtureCopy -Name 'ps51-utf8bom.ps1' -Directory $dir
            $r = Invoke-Tool @('-Path', $copy, '-Profile', 'ps51')
            $r.ExitCode | Should -Be 0
            $r.StdOut | Should -Match 'FILE='
        }
    }

    Context 'read-only guarantee' {

        It 'does not modify the inspected file' {
            $copy = New-FixtureCopy -Name 'ps51-gbk-cn.ps1'
            $before = (Get-FileBytes $copy)
            Invoke-Tool @('-Path', $copy, '-Profile', 'ps51') | Out-Null
            $after = (Get-FileBytes $copy)
            $before.Length | Should -Be $after.Length
            for ($i = 0; $i -lt $before.Length; $i++) {
                $before[$i] | Should -Be $after[$i]
            }
        }
    }
}
