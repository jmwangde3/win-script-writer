#Requires -Version 5.1
<#
    Contract tests for scripts/New-EncodedScript.ps1.

    The writer is the only tool in this repo that touches the filesystem, so the
    suite focuses on: byte-exact output, overwrite protection, backup, WhatIf,
    strict conversion, and temp-file hygiene.
#>

BeforeAll {
    . ([System.IO.Path]::Combine($PSScriptRoot, '..', 'Common', 'TestHelpers.ps1'))

    $Tool = 'New-EncodedScript.ps1'

    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $Utf8Strict = New-Object System.Text.UTF8Encoding($true)
    $Gbk = [System.Text.Encoding]::GetEncoding(936)

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

    function Get-SourceText {
        param([string]$Name)
        $bytes = [System.IO.File]::ReadAllBytes((Join-Path $FixturesDir $Name))
        return $Utf8Strict.GetString($bytes).TrimStart([char]0xFEFF)
    }

    function Get-TempLeftovers {
        param([string]$Directory)
        @(Get-ChildItem -LiteralPath $Directory -File -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '\.(tmp|tmp-[A-Za-z0-9]+)$' })
    }
}

Describe 'New-EncodedScript.ps1' {

    Context 'encoding output' {

        It 'writes UTF-8 without BOM byte-exactly' {
            $target = Join-Path $TestDrive 'out-utf8.ps1'
            $src = Join-Path $FixturesDir 'content-utf8.txt'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', $src, '-Encoding', 'utf8-nobom')
            $r.ExitCode | Should -Be 0
            $expected = $Utf8NoBom.GetBytes((Get-SourceText 'content-utf8.txt'))
            $actual = Get-FileBytes $target
            $actual.Length | Should -Be $expected.Length
            for ($i = 0; $i -lt $expected.Length; $i++) { $actual[$i] | Should -Be $expected[$i] }
            Get-Field $r.StdOut 'VERIFIED' | Should -Be 'True'
        }

        It 'writes UTF-8 with BOM' {
            $target = Join-Path $TestDrive 'out-utf8bom.ps1'
            $src = Join-Path $FixturesDir 'content-utf8.txt'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', $src, '-Encoding', 'utf8-bom')
            $r.ExitCode | Should -Be 0
            $actual = Get-FileBytes $target
            (Test-StartsWithBytes -Bytes $actual -Prefix ([byte[]](0xEF, 0xBB, 0xBF))) | Should -BeTrue
            $expected = $Utf8NoBom.GetBytes((Get-SourceText 'content-utf8.txt'))
            ($actual.Length - 3) | Should -Be $expected.Length
        }

        It 'writes CP936 byte-exactly' {
            $target = Join-Path $TestDrive 'out-gbk.ps1'
            $src = Join-Path $FixturesDir 'content-utf8.txt'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', $src, '-Encoding', 'gbk')
            $r.ExitCode | Should -Be 0
            $expected = $Gbk.GetBytes((Get-SourceText 'content-utf8.txt'))
            $actual = Get-FileBytes $target
            $actual.Length | Should -Be $expected.Length
            for ($i = 0; $i -lt $expected.Length; $i++) { $actual[$i] | Should -Be $expected[$i] }
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'gbk'
        }

        It 'strips a BOM from the UTF-8 source instead of doubling it' {
            $target = Join-Path $TestDrive 'out-from-bom-source.ps1'
            $src = Join-Path $FixturesDir 'content-utf8-bom.txt'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', $src, '-Encoding', 'utf8-bom')
            $r.ExitCode | Should -Be 0
            $actual = Get-FileBytes $target
            (Test-StartsWithBytes -Bytes $actual -Prefix ([byte[]](0xEF, 0xBB, 0xBF))) | Should -BeTrue
            $actual[3] | Should -Not -Be 0xEF
        }
    }

    Context 'overwrite protection' {

        It 'refuses to overwrite without -Force' {
            $target = Join-Path $TestDrive 'protected.ps1'
            [System.IO.File]::WriteAllText($target, 'original', $Utf8NoBom)
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'))
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ERROR' | Should -Be 'EXISTS'
            [System.IO.File]::ReadAllText($target) | Should -Be 'original'
        }

        It 'overwrites with -Force' {
            $target = Join-Path $TestDrive 'forced.ps1'
            [System.IO.File]::WriteAllText($target, 'original', $Utf8NoBom)
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'), '-Force')
            $r.ExitCode | Should -Be 0
            [System.IO.File]::ReadAllText($target) | Should -Not -Be 'original'
        }

        It 'keeps a backup with -Backup' {
            $target = Join-Path $TestDrive 'backed.ps1'
            [System.IO.File]::WriteAllText($target, 'original', $Utf8NoBom)
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'), '-Force', '-Backup')
            $r.ExitCode | Should -Be 0
            $backup = Get-Field $r.StdOut 'BACKUP'
            $backup | Should -Not -BeNullOrEmpty
            Test-Path -LiteralPath $backup | Should -BeTrue
            [System.IO.File]::ReadAllText($backup) | Should -Be 'original'
        }

        It 'does nothing at all with -WhatIf' {
            $target = Join-Path $TestDrive 'whatif.ps1'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'), '-WhatIf')
            $r.ExitCode | Should -Be 0
            Test-Path -LiteralPath $target | Should -BeFalse
        }
    }

    Context 'strict conversion' {

        It 'rejects a source that is not strict UTF-8' {
            $target = Join-Path $TestDrive 'never.ps1'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-gbk.txt'))
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ERROR' | Should -Be 'INPUT_NOT_STRICT_UTF8'
            Test-Path -LiteralPath $target | Should -BeFalse
        }

        It 'refuses characters outside the CP936 repertoire instead of substituting' {
            $target = Join-Path $TestDrive 'emoji.ps1'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-emoji.txt'), '-Encoding', 'gbk')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ERROR' | Should -Be 'UNREPRESENTABLE_CHARACTER'
            Test-Path -LiteralPath $target | Should -BeFalse
        }

        It 'still accepts the same content as UTF-8' {
            $target = Join-Path $TestDrive 'emoji-utf8.ps1'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-emoji.txt'), '-Encoding', 'utf8-bom')
            $r.ExitCode | Should -Be 0
        }
    }

    Context 'filesystem behaviour' {

        It 'creates missing parent directories' {
            $target = Join-Path (Join-Path $TestDrive 'nested') 'deeper\out.ps1'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'))
            $r.ExitCode | Should -Be 0
            Test-Path -LiteralPath $target | Should -BeTrue
        }

        It 'leaves no temporary files behind' {
            $dir = Join-Path $TestDrive 'clean'
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $target = Join-Path $dir 'out.ps1'
            Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt')) | Out-Null
            (Get-TempLeftovers $dir).Count | Should -Be 0
        }

        It 'leaves no temporary files behind after a failure' {
            $dir = Join-Path $TestDrive 'clean-fail'
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $target = Join-Path $dir 'out.ps1'
            Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-gbk.txt')) | Out-Null
            (Get-TempLeftovers $dir).Count | Should -Be 0
            Test-Path -LiteralPath $target | Should -BeFalse
        }

        It 'fails cleanly when the target is a directory' {
            $dir = Join-Path $TestDrive 'iam-a-dir'
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
            $r = Invoke-Tool @('-Path', $dir, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'), '-Force')
            $r.ExitCode | Should -Be 2
            Test-Path -LiteralPath $dir -PathType Container | Should -BeTrue
        }
    }

    Context 'output formats' {

        It 'emits machine readable json' {
            $target = Join-Path $TestDrive 'json-out.ps1'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'), '-Encoding', 'utf8-bom', '-Output', 'Json')
            $r.ExitCode | Should -Be 0
            $doc = $r.StdOut | ConvertFrom-Json
            $doc.Written | Should -Be $target
            $doc.Encoding | Should -Be 'utf8-bom'
            $doc.Verified | Should -BeTrue
            $doc.ExitCode | Should -Be 0
        }

        It 'accepts literal content for ascii payloads' {
            $target = Join-Path $TestDrive 'literal.ps1'
            $r = Invoke-Tool @('-Path', $target, '-Content', 'Write-Output "hello"')
            $r.ExitCode | Should -Be 0
            [System.IO.File]::ReadAllText($target) | Should -Be 'Write-Output "hello"'
        }
    }
}
