#Requires -Version 5.1
<#
    Shared helpers for the Pester suites.

    Design constraints:
      * ASCII only. Test output must never depend on the active code page.
      * Never call the tools in-process: every tool under test calls `exit`,
        which would terminate the Pester host.
      * Child output is captured as raw bytes and decoded defensively, because
        Windows PowerShell writes non-ASCII text using the console code page.
#>

$HelperDir = $PSScriptRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $HelperDir)
$ScriptsDir = Join-Path $RepoRoot 'scripts'
$FixturesDir = [System.IO.Path]::Combine($RepoRoot, 'tests', 'fixtures', 'data')

function Get-CurrentPowerShellExe {
    <#
        Returns the executable that is running this test session, so the same
        suite runs under both Windows PowerShell 5.1 and PowerShell 7.
    #>
    return (Get-Process -Id $PID).Path
}

function Get-PythonExe {
    foreach ($candidate in @('python', 'python3', 'py')) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            if ($candidate -eq 'py') { return @($cmd.Source, '-3') }
            return @($cmd.Source)
        }
    }
    throw 'python interpreter not found on PATH'
}

function ConvertTo-ArgString {
    param([string[]]$Arguments)
    $parts = @()
    foreach ($a in $Arguments) {
        if ($null -eq $a) { continue }
        if ($a.Length -eq 0) { $parts += '""'; continue }
        if ($a -match '[\s"]') {
            $parts += '"' + ($a -replace '(\\*)"', '$1$1\"') + '"'
        } else {
            $parts += $a
        }
    }
    return ($parts -join ' ')
}

function ConvertFrom-RawOutput {
    param([byte[]]$Bytes)
    if ($null -eq $Bytes -or $Bytes.Length -eq 0) { return '' }
    $strict = New-Object System.Text.UTF8Encoding($false, $true)
    try { return $strict.GetString($Bytes) }
    catch { return [System.Text.Encoding]::GetEncoding(936).GetString($Bytes) }
}

function Invoke-Process {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 180
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = ConvertTo-ArgString $Arguments
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true

    $proc = [System.Diagnostics.Process]::Start($psi)
    $outStream = $proc.StandardOutput.BaseStream
    $errStream = $proc.StandardError.BaseStream

    # Read both streams concurrently through the async APIs, then drain them.
    $outBuf = New-Object System.IO.MemoryStream
    $errBuf = New-Object System.IO.MemoryStream

    $outTask = $outStream.CopyToAsync($outBuf)
    $errTask = $errStream.CopyToAsync($errBuf)

    if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
        try { $proc.Kill() }
        catch { Write-Verbose ('the timed out child could not be killed: ' + $_.Exception.Message) }
        throw ("process timed out after {0}s: {1}" -f $TimeoutSeconds, $FilePath)
    }
    [void]$outTask.Wait(5000)
    [void]$errTask.Wait(5000)

    $proc.WaitForExit()

    [pscustomobject]@{
        ExitCode = $proc.ExitCode
        StdOut   = ConvertFrom-RawOutput $outBuf.ToArray()
        StdErr   = ConvertFrom-RawOutput $errBuf.ToArray()
        OutBytes = $outBuf.ToArray()
    }
}

function Invoke-WsTool {
    <#
        Runs scripts/<name> in the current PowerShell edition.
        Returns ExitCode / StdOut / StdErr.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string[]]$Arguments = @(),
        [int]$TimeoutSeconds = 180
    )
    $scriptPath = Join-Path $ScriptsDir $Name
    $argv = @('-NoProfile', '-NonInteractive', '-File', $scriptPath) + $Arguments
    return Invoke-Process -FilePath (Get-CurrentPowerShellExe) -Arguments $argv -TimeoutSeconds $TimeoutSeconds
}

function Invoke-PsSnippet {
    <#
        Runs an arbitrary ASCII snippet in the current PowerShell edition.

        Needed because a string array cannot cross a process boundary through
        -File: "-Path a b" binds only "a" to $Path and makes "b" a stray
        positional argument. Tests that need a real array build a snippet.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Snippet,
        [int]$TimeoutSeconds = 180
    )
    $tempRoot = [System.IO.Path]::GetTempPath()
    $path = Join-Path $tempRoot ('ws-snippet-' + [guid]::NewGuid().ToString('N') + '.ps1')
    try {
        # "exit" inside a nested script only sets $LASTEXITCODE, it does not end
        # the process. Re-exit so the caller observes the tool's real code.
        $body = $Snippet.TrimEnd() + "`r`n" + 'exit $LASTEXITCODE' + "`r`n"
        # UTF-8 with BOM: snippets carry real paths, which may contain non-ASCII
        # characters that Windows PowerShell would otherwise read as the ANSI
        # code page.
        [System.IO.File]::WriteAllText($path, $body, (New-Object System.Text.UTF8Encoding($true)))
        return Invoke-Process -FilePath (Get-CurrentPowerShellExe) -Arguments @('-NoProfile', '-NonInteractive', '-File', $path) -TimeoutSeconds $TimeoutSeconds
    }
    finally {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

function New-FixtureCopy {
    <#
        Copies a fixture into $TestDrive and returns the new full path.
        Tests mutate files, so the fixtures themselves stay pristine.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [string]$Directory
    )
    if (-not $Directory) { $Directory = $TestDrive }
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    $src = Join-Path $FixturesDir $Name
    $dst = Join-Path $Directory $Name
    Copy-Item -LiteralPath $src -Destination $dst -Force
    return $dst
}

function Get-FileBytes {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.File]::ReadAllBytes($Path)
}

function Test-StartsWithBytes {
    param([byte[]]$Bytes, [byte[]]$Prefix)
    if ($Bytes.Length -lt $Prefix.Length) { return $false }
    for ($i = 0; $i -lt $Prefix.Length; $i++) {
        if ($Bytes[$i] -ne $Prefix[$i]) { return $false }
    }
    return $true
}
