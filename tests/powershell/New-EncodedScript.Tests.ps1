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

    Context 'default encoding by extension' {

        It 'writes a .ps1 as UTF-8 with BOM when no encoding is given' {
            # v1.0.0 defaulted every target to utf8-nobom, so the writer produced
            # exactly the file the detector rejects under -Profile ps51.
            $target = Join-Path $TestDrive 'default-script.ps1'
            $src = Join-Path $FixturesDir 'content-utf8.txt'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', $src)
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-bom'
            Get-Field $r.StdOut 'ENCODING_SOURCE' | Should -Be 'extension'
            $actual = Get-FileBytes $target
            (Test-StartsWithBytes -Bytes $actual -Prefix ([byte[]](0xEF, 0xBB, 0xBF))) | Should -BeTrue
        }

        It 'defaults .psm1 and .psd1 to UTF-8 with BOM too' {
            foreach ($name in @('module.psm1', 'manifest.psd1')) {
                $target = Join-Path $TestDrive $name
                $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'))
                $r.ExitCode | Should -Be 0
                Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-bom'
            }
        }

        It 'defaults a .bat to CP936 without BOM' {
            # A BOM in front of "@echo off" makes cmd.exe report that the command
            # does not exist, so the batch default must not carry one.
            $target = Join-Path $TestDrive 'default-batch.bat'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'))
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'gbk'
            Get-Field $r.StdOut 'BOM' | Should -Be 'NONE'
            $actual = Get-FileBytes $target
            (Test-StartsWithBytes -Bytes $actual -Prefix ([byte[]](0xEF, 0xBB, 0xBF))) | Should -BeFalse
        }

        It 'keeps UTF-8 without BOM for data files' {
            $target = Join-Path $TestDrive 'default-data.txt'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'))
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-nobom'
            Get-Field $r.StdOut 'BOM' | Should -Be 'NONE'
        }

        It 'lets an explicit encoding override the extension' {
            $target = Join-Path $TestDrive 'explicit.ps1'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'), '-Encoding', 'utf8-nobom')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'ENCODING' | Should -Be 'utf8-nobom'
            Get-Field $r.StdOut 'ENCODING_SOURCE' | Should -Be 'explicit'
            $actual = Get-FileBytes $target
            (Test-StartsWithBytes -Bytes $actual -Prefix ([byte[]](0xEF, 0xBB, 0xBF))) | Should -BeFalse
        }

        It 'reports the default it would use under -WhatIf without writing' {
            $target = Join-Path $TestDrive 'whatif-default.ps1'
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'), '-WhatIf')
            $r.ExitCode | Should -Be 0
            Get-Field $r.StdOut 'WOULD_ENCODING' | Should -Be 'utf8-bom'
            Get-Field $r.StdOut 'WOULD_ENCODING_SOURCE' | Should -Be 'extension'
            Test-Path -LiteralPath $target | Should -BeFalse
        }

        It 'produces a file the detector accepts' {
            # The two tools are a pair; a default that fails the detector is a
            # default that sends the caller round in circles.
            $target = Join-Path $TestDrive 'round-trip.ps1'
            $w = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-utf8.txt'))
            $w.ExitCode | Should -Be 0
            $t = Invoke-WsTool -Name 'Test-ScriptEncoding.ps1' -Arguments @('-Path', $target, '-Profile', 'ps51')
            $t.ExitCode | Should -Be 0
            $t.StdOut | Should -Match 'VERDICT=OK'
        }
    }

    Context 'backup and failure safety' {

        It 'never overwrites an earlier backup' {
            # The backup name is a one second timestamp, and File.Replace
            # overwrites an existing backup file, so two writes inside the same
            # second used to destroy the first one.
            $target = Join-Path $TestDrive 'twice.ps1'
            $src = Join-Path $FixturesDir 'content-utf8.txt'
            [System.IO.File]::WriteAllText($target, 'original', $Utf8NoBom)

            $first = Invoke-Tool @('-Path', $target, '-ContentFile', $src, '-Force', '-Backup')
            $first.ExitCode | Should -Be 0
            $second = Invoke-Tool @('-Path', $target, '-ContentFile', $src, '-Force', '-Backup')
            $second.ExitCode | Should -Be 0

            $backups = @(Get-ChildItem -LiteralPath $TestDrive -File | Where-Object { $_.Name -like 'twice.ps1.bak-*' })
            $backups.Count | Should -Be 2
            $texts = @($backups | ForEach-Object { [System.IO.File]::ReadAllText($_.FullName) })
            ($texts -contains 'original') | Should -BeTrue
        }

        It 'leaves the original untouched when the conversion fails' {
            $target = Join-Path $TestDrive 'untouched.ps1'
            [System.IO.File]::WriteAllText($target, 'original', $Utf8NoBom)
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $FixturesDir 'content-emoji.txt'), '-Encoding', 'gbk', '-Force', '-Backup')
            $r.ExitCode | Should -Be 2
            Get-Field $r.StdOut 'ERROR' | Should -Be 'UNREPRESENTABLE_CHARACTER'
            [System.IO.File]::ReadAllText($target) | Should -Be 'original'
            $backups = @(Get-ChildItem -LiteralPath $TestDrive -File | Where-Object { $_.Name -like 'untouched.ps1.bak-*' })
            $backups.Count | Should -Be 0
        }

        It 'leaves the original untouched when the content source is unreadable' {
            $target = Join-Path $TestDrive 'unreadable.ps1'
            [System.IO.File]::WriteAllText($target, 'original', $Utf8NoBom)
            $r = Invoke-Tool @('-Path', $target, '-ContentFile', (Join-Path $TestDrive 'missing-source.txt'), '-Force')
            $r.ExitCode | Should -Be 3
            [System.IO.File]::ReadAllText($target) | Should -Be 'original'
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
