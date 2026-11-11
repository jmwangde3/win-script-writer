#Requires -Version 5.1
<#
    Static analysis gate. Kept as a file so the escaping of the command line never
    becomes part of the result.

    Two expectations, because there are two trees:

      * scripts/ is shipped code. Every rule applies.
      * tests/ is analysed too, minus one rule. Pester 5 runs BeforeAll in its own
        scope, so "$Utf8NoBom assigned in BeforeAll, read inside It" is reported as
        unused when it is not. Excluding that rule for the test tree only keeps it
        active where it still has signal.

    tests/fixtures/data is never passed to the analyzer: those files are the test
    payload, some deliberately GBK and deliberately BOM-less. Analysing them would
    flag a fixture for being exactly what it was created to be.

    Invoke-ScriptAnalyzer accepts a directory or one file, not a list, and a bad
    argument surfaces as a non-terminating error. Every call below runs with
    -ErrorAction Stop inside a catch that fails the gate, and the analysed file
    count is printed, so this script cannot report ANALYZER_CLEAN after analysing
    nothing.
#>
[CmdletBinding()]
param(
    [string[]]$Root
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$settings = Join-Path $repoRoot 'PSScriptAnalyzerSettings.psd1'

Import-Module PSScriptAnalyzer -ErrorAction Stop

#: Rules that cannot be judged in the test tree, and only there.
$testOnlyExclusions = @('PSUseDeclaredVarsMoreThanAssignments')

function Resolve-Target {
    param([string]$Item)
    if ([System.IO.Path]::IsPathRooted($Item)) { return $Item }
    return (Join-Path $repoRoot $Item)
}

$targets = @()
if ($Root) {
    foreach ($item in $Root) { $targets += (Resolve-Target $item) }
}
else {
    $targets += (Resolve-Target 'scripts')
    $targets += (Resolve-Target 'tests')
}

$findings = New-Object System.Collections.ArrayList
$analysed = 0

try {
    foreach ($target in $targets) {
        if (-not (Test-Path -LiteralPath $target)) {
            Write-Output ('ANALYZER_MISSING_PATH=' + $target)
            exit 1
        }

        $isTestTree = $target -match '[\\/]tests([\\/]|$)'
        $files = @(
            Get-ChildItem -LiteralPath $target -Recurse -File -Filter '*.ps1' |
                Where-Object { $_.FullName -notmatch '[\\/]fixtures[\\/]data[\\/]' } |
                ForEach-Object { $_.FullName }
        )
        if ($files.Count -eq 0) { continue }
        $analysed += $files.Count

        foreach ($file in $files) {
            $options = @{
                Path        = $file
                Settings    = $settings
                ErrorAction = 'Stop'
            }
            if ($isTestTree) { $options['ExcludeRule'] = $testOnlyExclusions }

            foreach ($item in @(Invoke-ScriptAnalyzer @options)) {
                if ($null -ne $item) { [void]$findings.Add($item) }
            }
        }
    }
}
catch {
    Write-Output ('ANALYZER_FAILED ' + $_.Exception.Message)
    exit 1
}

if ($analysed -eq 0) {
    Write-Output 'ANALYZER_FAILED no script files were found to analyse'
    exit 1
}

Write-Output ('ANALYZED_FILES=' + $analysed)

if ($findings.Count -eq 0) {
    Write-Output 'ANALYZER_CLEAN'
    exit 0
}

foreach ($f in $findings) {
    $relative = $f.ScriptPath
    if ($relative -and $relative.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        $relative = $relative.Substring($repoRoot.Length).TrimStart('\', '/')
    }
    Write-Output ('{0} {1} {2}:{3} {4}' -f $f.Severity, $f.RuleName, $relative, $f.Line, $f.Message)
}
exit 1
