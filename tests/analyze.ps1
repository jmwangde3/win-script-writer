#Requires -Version 5.1
<#
    Static analysis gate. Kept as a file so the escaping of the command line
    never becomes part of the result.
#>
param([string]$Root = 'scripts')

$settings = Join-Path (Split-Path -Parent $PSScriptRoot) 'PSScriptAnalyzerSettings.psd1'
Import-Module PSScriptAnalyzer -ErrorAction Stop

$findings = Invoke-ScriptAnalyzer -Path $Root -Settings $settings -Recurse
if (-not $findings) {
    Write-Output 'ANALYZER_CLEAN'
    exit 0
}
foreach ($f in $findings) {
    Write-Output ('{0} {1} {2}:{3} {4}' -f $f.Severity, $f.RuleName,
        [System.IO.Path]::GetFileName($f.ScriptName), $f.Line, $f.Message)
}
exit 1
