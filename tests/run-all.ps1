#Requires -Version 5.1
<#
.SYNOPSIS
    Runs the whole local test matrix for win-script-writer.

.DESCRIPTION
    Works in both Windows PowerShell 5.1 and PowerShell 7. The Pester suite is
    always executed with the host that runs this script, which is exactly how
    the "must pass under both runtimes" requirement is verified:

        powershell -NoProfile -File tests/run-all.ps1 -Suite pester
        pwsh       -NoProfile -File tests/run-all.ps1 -Suite pester

.PARAMETER Suite
    all | pester | python | evals | integration

.PARAMETER PesterVersion
    Pester version to load. Defaults to 5.7.1, the version pinned in CI.
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'pester', 'python', 'evals', 'integration')]
    [string]$Suite = 'all',

    [string]$PesterVersion = '5.7.1'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$failures = New-Object System.Collections.ArrayList

function Get-PythonCommand {
    <#
        Returns the interpreter plus any launcher prefix, always as an array.
        The leading comma prevents PowerShell from unrolling a single element
        array into a scalar, which would make $result[0] return one character.
    #>
    foreach ($name in @('python', 'python3', 'py')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            if ($name -eq 'py') { return , @($cmd.Source, '-3') }
            return , @($cmd.Source)
        }
    }
    throw 'python interpreter not found on PATH'
}

function Invoke-PesterSuite {
    $module = Get-Module -ListAvailable Pester |
        Where-Object { $_.Version.ToString() -eq $PesterVersion } |
        Select-Object -First 1
    if (-not $module) {
        throw ("Pester {0} is not installed. Install it with: Install-Module Pester -RequiredVersion {0} -Scope CurrentUser" -f $PesterVersion)
    }
    Import-Module Pester -RequiredVersion $PesterVersion -Force

    $config = New-PesterConfiguration
    $testsRoot = Join-Path $repoRoot 'tests'
    $config.Run.Path = (Join-Path $testsRoot 'powershell')
    $config.Run.Exit = $false
    $config.Run.PassThru = $true
    $config.Output.Verbosity = 'Detailed'
    # Full Pester stack traces are hundreds of lines long and bury the assertion.
    $config.Output.StackTraceVerbosity = 'FirstLine'
    $result = Invoke-Pester -Configuration $config

    Write-Output ("PESTER runtime={0} total={1} passed={2} failed={3} skipped={4}" -f `
            $PSVersionTable.PSEdition, $result.TotalCount, $result.PassedCount, $result.FailedCount, $result.SkippedCount)
    if ($result.FailedCount -gt 0) { [void]$failures.Add('pester') }
}

function Invoke-PythonSuite {
    param([string]$Directory)

    $python = Get-PythonCommand
    $exe = $python[0]
    $prefix = @()
    if ($python.Count -gt 1) { $prefix = $python[1..($python.Count - 1)] }

    # Join-Path only gained -AdditionalChildPath in PowerShell 6. Nesting is the
    # only form that works in both 5.1 and 7.
    $testsRoot = Join-Path $repoRoot 'tests'
    $suitePath = Join-Path $testsRoot $Directory

    $argv = $prefix + @('-m', 'unittest', 'discover', '-s', $suitePath, '-v')
    & $exe @argv
    if ($LASTEXITCODE -ne 0) {
        [void]$failures.Add($Directory)
        Write-Output ("PYTHON_SUITE_FAILED=" + $Directory)
    } else {
        Write-Output ("PYTHON_SUITE_OK=" + $Directory)
    }
}

if ($Suite -eq 'all' -or $Suite -eq 'pester') { Invoke-PesterSuite }
if ($Suite -eq 'all' -or $Suite -eq 'python') { Invoke-PythonSuite -Directory 'python' }
if ($Suite -eq 'all' -or $Suite -eq 'evals') { Invoke-PythonSuite -Directory 'evals' }
if ($Suite -eq 'all' -or $Suite -eq 'integration') { Invoke-PythonSuite -Directory 'integration' }

if ($failures.Count -gt 0) {
    Write-Output ("RESULT=FAILED suites=" + ($failures -join ','))
    exit 1
}
Write-Output 'RESULT=PASSED'
exit 0
