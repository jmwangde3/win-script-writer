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
            $r.StdOut | Should -Match 'PY_SOURCE_CODING_CONFLICT'
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
