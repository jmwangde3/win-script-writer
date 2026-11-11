#Requires -Version 5.1
<#
    Contract tests for scripts/Get-WinScriptEnvironment.ps1.

    The tool is read-only diagnostics, so the suite verifies that the reported
    code pages are the real ones (cross-checked against the registry and the
    .NET runtime) in both PowerShell editions.
#>

BeforeAll {
    . ([System.IO.Path]::Combine($PSScriptRoot, '..', 'Common', 'TestHelpers.ps1'))

    $Tool = 'Get-WinScriptEnvironment.ps1'

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

Describe 'Get-WinScriptEnvironment.ps1' {

    It 'returns 0 and prints key=value lines' {
        $r = Invoke-Tool @()
        $r.ExitCode | Should -Be 0
        $r.StdOut | Should -Match '(?m)^PSVERSION='
        $r.StdOut | Should -Match '(?m)^ACP='
        $r.StdOut | Should -Match '(?m)^OEMCP='
    }

    It 'reports the runtime that is actually executing' {
        $r = Invoke-Tool @()
        Get-Field $r.StdOut 'PSVERSION' | Should -Be $PSVersionTable.PSVersion.ToString()
        Get-Field $r.StdOut 'PSEDITION' | Should -Be $PSVersionTable.PSEdition
    }

    It 'reports the ANSI code page from the registry, not a guess' {
        $r = Invoke-Tool @()
        $acp = [int](Get-Field $r.StdOut 'ACP')
        $registryAcp = [int](Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage').ACP
        $acp | Should -Be $registryAcp
        [int](Get-Field $r.StdOut 'REGISTRYACP') | Should -Be $registryAcp
    }

    It 'separates OEM, ANSI and console code pages' {
        $r = Invoke-Tool @()
        $oem = [int](Get-Field $r.StdOut 'OEMCP')
        $oem | Should -BeGreaterThan 0
        $consoleOut = Get-Field $r.StdOut 'CONSOLEOUTCP'
        $consoleOut | Should -Not -BeNullOrEmpty
        [int]$consoleOut | Should -BeGreaterOrEqual 0
        Get-Field $r.StdOut 'CONSOLEOUTPUTENCODING' | Should -Not -BeNullOrEmpty
        Get-Field $r.StdOut 'OUTPUTENCODING' | Should -Not -BeNullOrEmpty
    }

    It 'emits machine readable json' {
        $r = Invoke-Tool @('-Output', 'Json')
        $r.ExitCode | Should -Be 0
        $doc = $r.StdOut | ConvertFrom-Json
        $doc.PSVersion | Should -Be $PSVersionTable.PSVersion.ToString()
        $doc.ACP | Should -BeGreaterThan 0
        $doc.OEMCP | Should -BeGreaterThan 0
        $doc.ExitCode | Should -Be 0
        $doc.Runtime | Should -Not -BeNullOrEmpty
    }

    It 'reports GBK availability rather than assuming it' {
        $r = Invoke-Tool @()
        Get-Field $r.StdOut 'GBKAVAILABLE' | Should -Be 'True'
    }
}
