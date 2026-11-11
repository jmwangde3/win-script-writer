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
    all | pester | python | evals | integration | analyze

.PARAMETER PesterVersion
    Pester version to load. Defaults to 5.7.1, the version pinned in CI.
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'pester', 'python', 'evals', 'integration', 'analyze')]
    [string]$Suite = 'all',

    [string]$PesterVersion = '5.7.1'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$testsRoot = Join-Path $repoRoot 'tests'
$failures = New-Object System.Collections.ArrayList

# The host running this script, so every child suite is executed by the same
# edition. That is how "must pass under 5.1 and 7" gets verified rather than
# assumed.
$currentExe = (Get-Process -Id $PID).Path

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

# Import name -> distribution name, for the pairs that differ. `yaml` is the
# module; the distribution on PyPI is `PyYAML`, and `pip install yaml` reports
# "no matching distribution" rather than anything useful. The failure is silent
# on any machine that already has PyYAML installed, which is every machine
# except a fresh CI runner -- exactly where it was found.
$script:PipDistribution = @{
    'yaml' = 'PyYAML'
}

function Invoke-PythonQuiet {
    <#
        Runs the interpreter and reports whether it exited 0.

        Windows PowerShell turns a native program's stderr into a terminating
        error while $ErrorActionPreference is 'Stop', and both calls that use
        this helper write to stderr in the normal course of business: the probe
        fails loudly when the module is missing, and pip is chatty. Relaxing the
        preference has to be local to the call, not global to the script.
    #>
    param(
        [string]$Exe,
        [string[]]$ArgList
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @ArgList 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-PythonSuite {
    param(
        [string]$Directory,
        [string[]]$RequiresModule = @()
    )

    $python = Get-PythonCommand
    $exe = $python[0]
    $prefix = @()
    if ($python.Count -gt 1) { $prefix = $python[1..($python.Count - 1)] }

    # A missing test dependency used to be discovered in CI and nowhere else.
    # The two matrix jobs and the release job each had to remember to install
    # PyYAML, and the release job did not -- so a tag push failed one minute
    # after a green branch build. Resolving it here, from the one script every
    # entry point already calls, removes the place where it can be forgotten.
    foreach ($module in $RequiresModule) {
        $probeArgs = $prefix + @('-c', ('import ' + $module))
        if (Invoke-PythonQuiet -Exe $exe -ArgList $probeArgs) { continue }

        $distribution = $module
        if ($script:PipDistribution.ContainsKey($module)) {
            $distribution = $script:PipDistribution[$module]
        }

        Write-Output ('PYTHON_DEP_INSTALL={0} FROM={1}' -f $module, $distribution)
        $pipArgs = $prefix + @('-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', $distribution)
        if (-not (Invoke-PythonQuiet -Exe $exe -ArgList $pipArgs)) {
            throw ("cannot install the test dependency '{0}'. Install it by hand: {1} -m pip install {2}" -f $module, $exe, $distribution)
        }

        # Installing without verifying is how the wrong distribution name
        # survived a green run: pip returned 0 for a package that does not
        # provide the module. Prove the import works before moving on.
        $probeArgs = $prefix + @('-c', ('import ' + $module))
        if (-not (Invoke-PythonQuiet -Exe $exe -ArgList $probeArgs)) {
            throw ("'{0}' installed but 'import {1}' still fails" -f $distribution, $module)
        }
    }

    # Join-Path only gained -AdditionalChildPath in PowerShell 6. Nesting is the
    # only form that works in both 5.1 and 7.
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

function Invoke-AnalyzerSuite {
    <#
        Static analysis runs inside its own process so the rule set can never be
        relaxed by whatever the Pester host has already imported.
    #>
    $analyzer = Join-Path $testsRoot 'analyze.ps1'
    $argv = @('-NoProfile', '-NonInteractive', '-File', $analyzer)
    & $currentExe @argv
    if ($LASTEXITCODE -ne 0) {
        [void]$failures.Add('analyze')
        Write-Output 'ANALYZER_SUITE_FAILED'
    } else {
        Write-Output 'ANALYZER_SUITE_OK'
    }
}

if ($Suite -eq 'all' -or $Suite -eq 'pester') { Invoke-PesterSuite }
if ($Suite -eq 'all' -or $Suite -eq 'analyze') { Invoke-AnalyzerSuite }
if ($Suite -eq 'all' -or $Suite -eq 'python') { Invoke-PythonSuite -Directory 'python' }
if ($Suite -eq 'all' -or $Suite -eq 'evals') { Invoke-PythonSuite -Directory 'evals' -RequiresModule @('yaml') }
if ($Suite -eq 'all' -or $Suite -eq 'integration') { Invoke-PythonSuite -Directory 'integration' }

if ($failures.Count -gt 0) {
    Write-Output ("RESULT=FAILED suites=" + ($failures -join ','))
    exit 1
}
Write-Output 'RESULT=PASSED'
exit 0
