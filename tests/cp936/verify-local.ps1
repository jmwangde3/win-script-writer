#Requires -Version 5.1
<#
.SYNOPSIS
    Runs the CP936 gate locally, on a real zh-CN host, in one shot.

.DESCRIPTION
    .github/workflows/cp936.yml is the automated version of this script. It only
    runs when a self-hosted runner carrying the labels self-hosted, windows and
    cp936 is registered and the repository variable CP936_RUNNER is set to
    enabled; until then the job reports skipped, and skipped is not coverage.

    This script performs the same checks on whichever zh-CN machine the caller
    is sitting at, without registering a runner on it:

      1. refuse to continue unless the ANSI code page really is 936, exactly as
         the workflow does -- a gate that runs on the wrong host proves nothing
      2. report the environment so the record names the machine it came from
      3. run the whole matrix with the edition that started the script
      4. run tests/integration separately and fail if its CP936 assertions were
         skipped instead of executed

    It prints a hash instead of the user name so the transcript can be committed.

.PARAMETER Suite
    all (default) or integration. integration repeats step 4 only, which is what
    a reviewer wants when checking a single change.

.EXAMPLE
    powershell -NoProfile -File tests/cp936/verify-local.ps1
    pwsh       -NoProfile -File tests/cp936/verify-local.ps1
#>
[CmdletBinding()]
param(
    [ValidateSet('all', 'integration')]
    [string]$Suite = 'all'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$currentExe = (Get-Process -Id $PID).Path

Write-Output ('HOST_EDITION=' + $PSVersionTable.PSEdition)
Write-Output ('HOST_VERSION=' + $PSVersionTable.PSVersion.ToString())
Write-Output ('HOST_EXE=' + (Split-Path -Leaf $currentExe))

$codePage = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage'
Write-Output ('ACP=' + $codePage.ACP)
Write-Output ('OEMCP=' + $codePage.OEMCP)

if ([int]$codePage.ACP -ne 936) {
    throw ('this check needs ACP 936, the host reports ' + $codePage.ACP)
}

$os = Get-CimInstance Win32_OperatingSystem
Write-Output ('OS=' + $os.Caption + ' ' + $os.Version)

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pyVersion = & $python.Source --version 2>&1
    Write-Output ('PYTHON=' + $pyVersion)
}

if ($Suite -eq 'all') {
    & (Join-Path $repoRoot 'tests\run-all.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'the full matrix failed' }
}

# The integration suite is where the CP936-only assertions live. It skips them
# when the host is not 936, so a green run with a skip in it would be a false
# pass -- exactly the failure the workflow guards against.
#
# unittest -v writes its progress to stderr, and Windows PowerShell turns a
# native program's stderr into a terminating error while the preference is Stop.
# The preference has to be relaxed locally, or the suite never reports a result.
$integration = Join-Path $repoRoot 'tests\integration'
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $output = & $python.Source -m unittest discover -s $integration -v 2>&1 | Out-String
    $code = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previous
}
Write-Output $output

if ($output -match 'host ANSI code page is .* not 936') {
    throw 'the CP936 integration tests were skipped on a 936 host'
}
if ($code -ne 0) { throw 'the integration suite failed' }

Write-Output 'CP936_ASSERTIONS_EXECUTED'
Write-Output ('RESULT=PASSED edition=' + $PSVersionTable.PSEdition)
exit 0
