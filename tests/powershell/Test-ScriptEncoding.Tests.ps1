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

        It 'rejects UTF-16LE with BOM' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf16le-bom.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16le-bom'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
        }

        It 'rejects UTF-16BE with BOM' {
            $r = Invoke-Tool @('-Path', (Join-Path $FixturesDir 'ps51-utf16be-bom.ps1'), '-Profile', 'ps51')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf16be-bom'
            Get-Field $r.StdOut 'VERDICT' | Should -Be 'FAIL'
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
            $r = Invoke-Tool @(
                '-Path', (Join-Path $FixturesDir 'ps51-utf8bom.ps1'),
                (Join-Path $FixturesDir 'ps51-utf8nobom-cn.ps1'),
                '-Profile', 'ps51'
            )
            $r.ExitCode | Should -Be 2
            $r.StdOut | Should -Match 'SUMMARY .*files=2'
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
