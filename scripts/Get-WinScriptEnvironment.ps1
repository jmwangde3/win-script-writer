#Requires -Version 5.1
<#
.SYNOPSIS
    Reports the code pages, encodings and runtime facts that decide whether a
    script will survive this machine.

.DESCRIPTION
    Read-only diagnostics. Prints one KEY=value line per fact, or a single JSON
    document with -Output Json. Never writes a file, never changes a code page,
    never requires administrator rights.

    Four different settings are reported separately, because they are routinely
    confused with each other:

      ACP             system ANSI code page. Windows PowerShell 5.1 decodes a
                      BOM-less script with this one.
      OEMCP           system OEM code page. cmd.exe parses batch files with it.
      CONSOLEOUTCP    code page the .NET console layer uses for stdout right
                      now. A window that ran chcp 65001 reports 65001 here while
                      ACP stays 936.
      OUTPUTENCODING  encoding PowerShell uses when it pipes strings into a
                      native program's stdin. On Windows PowerShell 5.1 this is
                      us-ascii, which is why Chinese text piped into git.exe
                      arrives as question marks. It does not affect arguments:
                      those travel through CreateProcessW as UTF-16 and never
                      touch this setting.

    Run this once per machine or per host, not once per task. The four values
    above are properties of the environment, not of the script you are about to
    write, and they only change when the window, the host edition or the machine
    changes.

    Sources are named rather than guessed: ACPSOURCE says whether ACP was read
    from HKLM\SYSTEM\CurrentControlSet\Control\Nls\CodePage or fell back to the
    .NET default. OEMCP is read from the same registry key.

    Code pages come from the registry and the .NET console layer on purpose.
    Getting the live values from Win32 would need Add-Type, which compiles C# at
    run time and is blocked by some security policies; a diagnostic tool that
    refuses to run exactly where policy is strict is not a diagnostic tool.

.PARAMETER Output
    text (default) or json.

.OUTPUTS
    Exit codes: 0 report produced, 3 the probe itself failed.

.EXAMPLE
    .\Get-WinScriptEnvironment.ps1

.EXAMPLE
    .\Get-WinScriptEnvironment.ps1 -Output Json | ConvertFrom-Json
#>
[CmdletBinding()]
param(
    [ValidateSet('text', 'json')]
    [string]$Output = 'text'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$codePageKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage'

function Get-RegistryCodePage {
    param([string]$Name)

    try {
        $item = Get-ItemProperty -LiteralPath $codePageKey -Name $Name -ErrorAction Stop
        $raw = $item.$Name
        if ($null -eq $raw) { return $null }
        return [int]$raw
    }
    catch {
        Write-Verbose ('registry value {0} was not readable: {1}' -f $Name, $_.Exception.Message)
        return $null
    }
}

function Enable-CodePageEncoding {
    <#
        Returns an Encoding for the code page, or $null when the runtime does not
        carry it. .NET Core ships no legacy code pages until a provider is
        registered; PowerShell 7.4 registers one at startup, a bare hosted
        runspace may not.
    #>
    param([int]$CodePage)

    try {
        return [System.Text.Encoding]::GetEncoding($CodePage)
    }
    catch {
        Write-Verbose ('code page {0} was not available directly: {1}' -f $CodePage, $_.Exception.Message)
    }

    try {
        $providerType = [System.Type]::GetType(
            'System.Text.CodePagesEncodingProvider, System.Text.Encoding.CodePages',
            $false)
        if ($providerType) {
            $instance = $providerType.GetProperty('Instance').GetValue($null, $null)
            [System.Text.Encoding]::RegisterProvider($instance)
            return [System.Text.Encoding]::GetEncoding($CodePage)
        }
    }
    catch {
        Write-Verbose ('code page provider could not be registered: ' + $_.Exception.Message)
    }

    return $null
}

function Test-GbkRoundTrip {
    <#
        Proves the code page is usable, not merely present: encode a two
        character probe and decode it back. The probe is built from code points
        so this file stays pure ASCII and its own encoding never matters.
    #>
    param($Encoding)

    if ($null -eq $Encoding) { return $false }

    try {
        $probe = [string]([char]0x4E2D) + [string]([char]0x6587)
        $bytes = $Encoding.GetBytes($probe)
        return ($Encoding.GetString($bytes) -ceq $probe)
    }
    catch {
        Write-Verbose ('GBK round trip probe failed: ' + $_.Exception.Message)
        return $false
    }
}

$notes = New-Object System.Collections.ArrayList
$info = [ordered]@{}

try {
    $registryAcp = Get-RegistryCodePage -Name 'ACP'
    $registryOem = Get-RegistryCodePage -Name 'OEMCP'

    $acp = $registryAcp
    $acpSource = 'registry:HKLM\SYSTEM\CurrentControlSet\Control\Nls\CodePage\ACP'
    if ($null -eq $acp) {
        if ($PSVersionTable.PSEdition -eq 'Desktop') {
            # .NET Framework Default is the ANSI code page; on .NET Core it is
            # always UTF-8 and tells us nothing about the host locale.
            $acp = [System.Text.Encoding]::Default.CodePage
            $acpSource = 'dotnet-default'
        }
        else {
            $acpSource = 'unavailable'
        }
    }

    $consoleIn = $null
    $consoleOut = $null
    try { $consoleIn = [Console]::InputEncoding }
    catch { Write-Verbose ('console input encoding unavailable: ' + $_.Exception.Message) }
    try { $consoleOut = [Console]::OutputEncoding }
    catch { Write-Verbose ('console output encoding unavailable: ' + $_.Exception.Message) }

    $pipelineEncoding = $null
    try { $pipelineEncoding = $OutputEncoding }
    catch { Write-Verbose ('pipeline output encoding unavailable: ' + $_.Exception.Message) }

    $outRedirected = $null
    try { $outRedirected = [Console]::IsOutputRedirected }
    catch { Write-Verbose ('stdout redirection state unavailable: ' + $_.Exception.Message) }

    $processArch = 'unknown'
    try { $processArch = [System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture.ToString() }
    catch { Write-Verbose ('process architecture unavailable: ' + $_.Exception.Message) }

    $effectivePolicy = 'unknown'
    try { $effectivePolicy = (Get-ExecutionPolicy).ToString() }
    catch { Write-Verbose ('execution policy unavailable: ' + $_.Exception.Message) }

    $gbk = Enable-CodePageEncoding -CodePage 936
    $gbkRoundTrip = Test-GbkRoundTrip -Encoding $gbk

    if ($PSVersionTable.PSEdition -eq 'Desktop' -and $acp -eq 936) {
        [void]$notes.Add('PS51_BOMLESS_UTF8: this host decodes a BOM-less script as CP936, so UTF-8 Chinese text arrives mangled. Save scripts as UTF-8 with BOM.')
    }
    if ($pipelineEncoding -and $pipelineEncoding.WebName -eq 'us-ascii') {
        [void]$notes.Add('PS51_PIPELINE_ASCII: $OutputEncoding is us-ascii, so non-ASCII text piped into a native program''s stdin becomes a question mark. Arguments are not affected.')
    }
    if ($consoleOut -and $acp -and $consoleOut.CodePage -ne $acp) {
        [void]$notes.Add(('CONSOLE_CP_DIFFERS: console output code page {0} differs from the system ANSI code page {1}, so the same file can look correct in one window and wrong in another.' -f $consoleOut.CodePage, $acp))
    }

    $info['PSVersion'] = $PSVersionTable.PSVersion.ToString()
    $info['PSEdition'] = $PSVersionTable.PSEdition
    $info['Runtime'] = $PSVersionTable.PSEdition
    $info['PSHome'] = $PSHOME
    $info['ProcessArch'] = $processArch
    $info['Is64BitProcess'] = [System.Environment]::Is64BitProcess
    $info['OSVersion'] = [System.Environment]::OSVersion.Version.ToString()
    $info['OSArch'] = $env:PROCESSOR_ARCHITECTURE
    $info['Locale'] = [System.Globalization.CultureInfo]::CurrentCulture.Name
    $info['UICulture'] = [System.Globalization.CultureInfo]::CurrentUICulture.Name
    $info['ExecutionPolicy'] = $effectivePolicy
    $info['OutputRedirected'] = $outRedirected
    $info['ACP'] = $acp
    $info['AcpSource'] = $acpSource
    $info['RegistryAcp'] = $registryAcp
    $info['OEMCP'] = $registryOem
    $info['ConsoleInCP'] = $(if ($null -eq $consoleIn) { $null } else { $consoleIn.CodePage })
    $info['ConsoleOutCP'] = $(if ($null -eq $consoleOut) { $null } else { $consoleOut.CodePage })
    $info['ConsoleInputEncoding'] = $(if ($null -eq $consoleIn) { $null } else { $consoleIn.WebName })
    $info['ConsoleOutputEncoding'] = $(if ($null -eq $consoleOut) { $null } else { $consoleOut.WebName })
    $info['OutputEncoding'] = $(if ($null -eq $pipelineEncoding) { $null } else { $pipelineEncoding.WebName })
    $info['DefaultEncoding'] = [System.Text.Encoding]::Default.WebName
    $info['GbkAvailable'] = ($null -ne $gbk)
    $info['GbkRoundTrip'] = $gbkRoundTrip
    $info['ExitCode'] = 0
}
catch {
    [Console]::Error.WriteLine('ERROR=ENVIRONMENT_PROBE_FAILED ' + $_.Exception.Message)
    exit 3
}

if ($Output -eq 'json') {
    $document = [ordered]@{}
    foreach ($key in $info.Keys) { $document[$key] = $info[$key] }
    $document['Notes'] = @($notes)
    $document | ConvertTo-Json -Depth 4
}
else {
    foreach ($key in $info.Keys) {
        $value = $info[$key]
        if ($null -eq $value) { $rendered = 'unknown' } else { $rendered = [string]$value }
        Write-Output ($key.ToUpperInvariant() + '=' + $rendered)
    }
    foreach ($note in $notes) {
        Write-Output ('WARNING=' + $note)
    }
}

exit 0
