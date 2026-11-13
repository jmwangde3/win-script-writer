#Requires -Version 5.1
<#
.SYNOPSIS
    Writes a text file in a chosen encoding without ever corrupting the original.

.DESCRIPTION
    The writer takes strictly valid UTF-8 as input, converts it with a strict
    encoder, writes to a temporary file in the target directory, verifies the
    bytes by reading them back, and only then publishes the result:

      * new file          -> File.Move (same volume, same directory)
      * existing file     -> File.Replace (atomic on NTFS)

    If anything fails the original file is left untouched and the temporary file
    is removed.

    Safety defaults:
      * refuses to overwrite unless -Force is given
      * never substitutes characters that the target encoding cannot represent
      * -WhatIf and -Confirm are supported through ShouldProcess

.PARAMETER Path
    Destination file.

.PARAMETER ContentFile
    Source file. Must be valid UTF-8 (a leading BOM is stripped).

.PARAMETER Content
    Literal text. Only safe for ASCII payloads: a non-ASCII literal travels
    through the command line, which is code page dependent. Prefer -ContentFile.

.PARAMETER Encoding
    utf8-bom, utf8-nobom, or gbk. When omitted, the target extension decides:

      .ps1 .psm1 .psd1   utf8-bom   the recommended cross-version storage
                                    format, especially for scripts containing
                                    non-ASCII text. Both 5.1 and 7 also parse
                                    UTF-16 with a BOM, but nothing else on the
                                    machine does
      .bat .cmd          gbk        what a CP936 cmd.exe expects; pass
                                    -Encoding explicitly on another code page
      anything else      utf8-nobom the safe default for data files

    The chosen name and its source (explicit or extension) are reported, so a
    caller never has to guess which one it got.

.PARAMETER Force
    Allow replacing an existing file.

.PARAMETER Backup
    With -Force on an existing file, keep the previous content next to the
    target as <name>.bak-<timestamp>.

.PARAMETER Output
    text (default) or json.

.OUTPUTS
    Exit codes: 0 written, 2 content or write failure, 3 parameter or I/O error,
    4 cancelled at the confirmation prompt (nothing was written).

    -WhatIf previews and exits 0, as it always has. A declined -Confirm is not a
    preview: it exits 4 so a caller that only inspects the exit code cannot
    record a write that never happened. Both report STATE= in text output and
    Status in json, in addition to the exit code.

.EXAMPLE
    .\New-EncodedScript.ps1 -Path .\build.ps1 -ContentFile .\build.txt -Encoding utf8-bom

.EXAMPLE
    .\New-EncodedScript.ps1 -Path .\legacy.cmd -ContentFile .\legacy.txt -Encoding gbk -Force -Backup
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium', DefaultParameterSetName = 'File')]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Path,

    [Parameter(Position = 1, ParameterSetName = 'File')]
    [string]$ContentFile,

    [Parameter(Mandatory = $true, ParameterSetName = 'Text')]
    [string]$Content,

    [ValidateSet('utf8-bom', 'utf8-nobom', 'gbk')]
    [string]$Encoding,

    [switch]$Force,

    [switch]$Backup,

    [ValidateSet('text', 'json')]
    [string]$Output = 'text'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$result = [ordered]@{
    Tool           = 'New-EncodedScript.ps1'
    Version        = '1.0.2'
    Runtime        = $PSVersionTable.PSEdition
    Target         = $null
    Status         = $null
    Written        = $null
    Encoding       = $null
    EncodingSource = $null
    Bytes          = 0
    Bom            = 'NONE'
    Verified       = $false
    Backup         = $null
    Replaced       = $false
    Error          = $null
    ExitCode       = 3
}

function Resolve-TargetEncoding {
    <#
        Explicit wins. Otherwise the extension decides, because the extension is
        the consumer's only hint about what the bytes should be:

          * a .ps1 that contains non-ASCII characters has to carry a BOM, or
            Windows PowerShell 5.1 decodes it with the ANSI code page. The old
            default was utf8-nobom for every target, which wrote exactly the file
            the detector rejects.
          * a .bat / .cmd is read by cmd.exe with the OEM code page, so CP936 is
            the only form a zh-CN console shows correctly.

        Anything else keeps the previous default.
    #>
    param([string]$Requested, [string]$TargetPath)

    if ($Requested) {
        return [pscustomobject]@{ Name = $Requested; Source = 'explicit' }
    }

    $extension = [System.IO.Path]::GetExtension($TargetPath).ToLowerInvariant()
    switch ($extension) {
        '.ps1' { return [pscustomobject]@{ Name = 'utf8-bom'; Source = 'extension' } }
        '.psm1' { return [pscustomobject]@{ Name = 'utf8-bom'; Source = 'extension' } }
        '.psd1' { return [pscustomobject]@{ Name = 'utf8-bom'; Source = 'extension' } }
        '.bat' { return [pscustomobject]@{ Name = 'gbk'; Source = 'extension' } }
        '.cmd' { return [pscustomobject]@{ Name = 'gbk'; Source = 'extension' } }
        default { return [pscustomobject]@{ Name = 'utf8-nobom'; Source = 'extension' } }
    }
}

function Get-UniqueBackupPath {
    <#
        A backup name is a second-resolution timestamp, so two writes inside the
        same second used to produce the same name -- and File.Replace overwrites
        an existing backup file, which silently destroyed the first one.
    #>
    param([string]$TargetPath)

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $candidate = $TargetPath + '.bak-' + $stamp
    $counter = 0
    while (Test-Path -LiteralPath $candidate) {
        $counter++
        $candidate = $TargetPath + '.bak-' + $stamp + '-' + $counter
    }
    return $candidate
}

function Complete-Write {
    param(
        [int]$Code,
        [string]$ErrorCode,
        [string]$Detail
    )

    if ($ErrorCode) { $result.Error = $ErrorCode }
    if ($Detail) { $result.Detail = $Detail }
    # This helper is the failure door only: every successful path reports itself
    # with Status = 'Written' further down.
    $result.Status = 'Failed'
    $result.ExitCode = $Code

    if ($Output -eq 'json') {
        $result | ConvertTo-Json -Depth 4
    }
    else {
        foreach ($key in @('Target', 'Status', 'Written', 'Encoding', 'EncodingSource', 'Bytes', 'Bom', 'Verified', 'Backup', 'Replaced', 'Error', 'Detail')) {
            # A failed run never wrote anything, and "WROTE=<path>" next to
            # "ERROR=REPLACE_FAILED" is the kind of line an operator believes.
            if ($key -eq 'Written' -and $Code -ne 0) { continue }
            $value = $result[$key]
            if ($null -eq $value) { continue }
            $label = $key.ToUpperInvariant()
            if ($label -eq 'STATUS') { $label = 'STATE' }
            if ($label -eq 'WRITTEN') { $label = 'WROTE' }
            Write-Output ($label + '=' + $value)
        }
        Write-Output ('EXITCODE=' + $Code)
    }

    exit $Code
}

function Get-CodePageEncoding {
    param([int]$CodePage)

    try {
        return [System.Text.Encoding]::GetEncoding($CodePage)
    }
    catch {
        # .NET Core does not carry the code page encodings by default. PowerShell 7
        # registers them at startup; a hosted runspace may not, so register here.
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
}

function Get-StrictEncoder {
    param([string]$Name)

    switch ($Name) {
        'utf8-bom' {
            # Second argument: throw on invalid bytes instead of substituting.
            return New-Object System.Text.UTF8Encoding($true, $true)
        }
        'utf8-nobom' {
            return New-Object System.Text.UTF8Encoding($false, $true)
        }
        'gbk' {
            $base = Get-CodePageEncoding -CodePage 936
            if (-not $base) { return $null }
            return [System.Text.Encoding]::GetEncoding(
                936,
                [System.Text.EncoderFallback]::ExceptionFallback,
                [System.Text.DecoderFallback]::ExceptionFallback)
        }
        default { return $null }
    }
}

# --- 1. resolve the destination -----------------------------------------
try {
    $target = [System.IO.Path]::GetFullPath($Path)
}
catch {
    Complete-Write -Code 3 -ErrorCode 'INVALID_PATH' -Detail $_.Exception.Message
}
$result.Target = $target
$result.Written = $target

# Resolved before anything is written, and reported, so the caller can see which
# encoding it ended up with even when it never asked for one.
$encodingChoice = Resolve-TargetEncoding -Requested $Encoding -TargetPath $target
# From here on $Encoding is the resolved name, not the raw parameter.
$Encoding = $encodingChoice.Name
$result.Encoding = $encodingChoice.Name
$result.EncodingSource = $encodingChoice.Source

if (Test-Path -LiteralPath $target -PathType Container) {
    Complete-Write -Code 2 -ErrorCode 'TARGET_IS_DIRECTORY' -Detail $target
}

$targetExists = Test-Path -LiteralPath $target -PathType Leaf
if ($targetExists -and -not $Force) {
    Complete-Write -Code 2 -ErrorCode 'EXISTS' -Detail 'refusing to overwrite without -Force'
}

# --- 2. read the source text --------------------------------------------
if ($PSCmdlet.ParameterSetName -eq 'File') {
    if (-not $ContentFile) {
        Complete-Write -Code 3 -ErrorCode 'CONTENT_FILE_REQUIRED' -Detail 'supply -ContentFile or -Content'
    }
    $sourcePath = $null
    try {
        $sourcePath = (Resolve-Path -LiteralPath $ContentFile -ErrorAction Stop).ProviderPath
    }
    catch {
        Complete-Write -Code 3 -ErrorCode 'INPUT_NOT_FOUND' -Detail $ContentFile
    }

    $sourceBytes = $null
    try {
        $sourceBytes = [System.IO.File]::ReadAllBytes($sourcePath)
    }
    catch {
        Complete-Write -Code 3 -ErrorCode 'INPUT_READ_FAILED' -Detail $_.Exception.Message
    }

    $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    try {
        $text = $strictUtf8.GetString($sourceBytes)
    }
    catch {
        Complete-Write -Code 2 -ErrorCode 'INPUT_NOT_STRICT_UTF8' -Detail 'convert the source to UTF-8 first'
    }
}
else {
    $text = $Content
}

# A source file saved as UTF-8 with BOM decodes to a leading U+FEFF. Strip it so
# the output does not end up with two preambles.
if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) {
    $text = $text.Substring(1)
}

# --- 3. encode -----------------------------------------------------------
$encoder = Get-StrictEncoder -Name $Encoding
if (-not $encoder) {
    Complete-Write -Code 2 -ErrorCode 'ENCODER_UNAVAILABLE' -Detail ("cannot create a strict encoder for " + $Encoding)
}

try {
    $payload = $encoder.GetBytes($text)
}
catch {
    Complete-Write -Code 2 -ErrorCode 'UNREPRESENTABLE_CHARACTER' -Detail ("content contains characters that " + $Encoding + " cannot represent")
}

$preamble = $encoder.GetPreamble()
$bytes = New-Object 'byte[]' ($preamble.Length + $payload.Length)
if ($preamble.Length -gt 0) {
    [Array]::Copy($preamble, 0, $bytes, 0, $preamble.Length)
}
[Array]::Copy($payload, 0, $bytes, $preamble.Length, $payload.Length)

$result.Bytes = $bytes.Length
if ($preamble.Length -gt 0) {
    $result.Bom = (($preamble | ForEach-Object { $_.ToString('X2') }) -join '')
}

# --- 4. honour -WhatIf / -Confirm ---------------------------------------
# -WhatIf is answered before ShouldProcess is called, on purpose. ShouldProcess
# prints its own "What if:" banner to the host, that banner lands in stdout, and
# a -Output json document stops being JSON. The preview is reported here with the
# same fields and nothing is written.
if ($WhatIfPreference) {
    $result.Status = 'Previewed'
    $result.ExitCode = 0
    if ($Output -eq 'json') {
        $result | ConvertTo-Json -Depth 4
    }
    else {
        Write-Output 'STATE=Previewed'
        Write-Output ('WOULD_WRITE=' + $target)
        Write-Output ('WOULD_ENCODING=' + $Encoding)
        Write-Output ('WOULD_ENCODING_SOURCE=' + $encodingChoice.Source)
        Write-Output ('WOULD_BYTES=' + $bytes.Length)
        Write-Output 'EXITCODE=0'
    }
    exit 0
}

if (-not $PSCmdlet.ShouldProcess($target, ('write ' + $Encoding))) {
    # ShouldProcess returned $false and this is not -WhatIf, so the confirmation
    # prompt was declined. The previous version reported this as a preview with
    # exit 0, and a caller that only inspects the exit code recorded a write that
    # never happened.
    $result.Status = 'Cancelled'
    $result.Detail = 'the confirmation prompt was declined; nothing was written'
    $result.ExitCode = 4
    if ($Output -eq 'json') {
        $result | ConvertTo-Json -Depth 4
    }
    else {
        Write-Output 'STATE=Cancelled'
        Write-Output 'CANCELLED=True'
        Write-Output ('TARGET=' + $target)
        Write-Output ('ENCODING=' + $Encoding)
        Write-Output ('DETAIL=' + $result.Detail)
        Write-Output 'EXITCODE=4'
    }
    exit 4
}

# --- 5. write, verify, publish ------------------------------------------
$directory = [System.IO.Path]::GetDirectoryName($target)
if (-not $directory) { $directory = (Get-Location).ProviderPath }

try {
    [void][System.IO.Directory]::CreateDirectory($directory)
}
catch {
    Complete-Write -Code 3 -ErrorCode 'DIRECTORY_NOT_WRITABLE' -Detail $_.Exception.Message
}

$tempPath = $target + '.tmp-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
$failureCode = $null
$failureDetail = $null
$backupPath = $null
$throwawayBackup = $null

try {
    [System.IO.File]::WriteAllBytes($tempPath, $bytes)

    # Read back through the same code path a consumer would use, and compare both
    # the bytes and the decoded text. A short write or a silent replacement would
    # be caught here, before the original is touched.
    $writtenBytes = [System.IO.File]::ReadAllBytes($tempPath)
    $sameBytes = ($writtenBytes.Length -eq $bytes.Length)
    if ($sameBytes) {
        for ($i = 0; $i -lt $bytes.Length; $i++) {
            if ($writtenBytes[$i] -ne $bytes[$i]) { $sameBytes = $false; break }
        }
    }

    $sameText = $false
    if ($sameBytes) {
        try {
            $decoded = $encoder.GetString($writtenBytes, $preamble.Length, $writtenBytes.Length - $preamble.Length)
            $sameText = ($decoded -ceq $text)
        }
        catch {
            $sameText = $false
        }
    }

    if (-not ($sameBytes -and $sameText)) {
        $failureCode = 'VERIFY_FAILED'
        $failureDetail = 'the file read back does not match what was written'
    }
    else {
        $result.Verified = $true

        if ($targetExists) {
            if ($Backup) {
                $backupPath = Get-UniqueBackupPath -TargetPath $target
            }
            try {
                # File.Replace always needs a backup path: passing $null from
                # PowerShell binds to an empty string, which .NET rejects as an
                # illegal path. When the caller did not ask for a backup, use a
                # throwaway file next to the target and delete it afterwards.
                if ($null -ne $backupPath) {
                    [System.IO.File]::Replace($tempPath, $target, $backupPath, $true)
                }
                else {
                    $throwawayBackup = $target + '.tmp-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
                    [System.IO.File]::Replace($tempPath, $target, $throwawayBackup, $true)
                }
                $result.Replaced = $true
            }
            catch {
                $failureCode = 'REPLACE_FAILED'
                $failureDetail = $_.Exception.Message
            }
        }
        else {
            try {
                [System.IO.File]::Move($tempPath, $target)
            }
            catch {
                $failureCode = 'MOVE_FAILED'
                $failureDetail = $_.Exception.Message
            }
        }
    }
}
catch {
    if (-not $failureCode) {
        $failureCode = 'WRITE_FAILED'
        $failureDetail = $_.Exception.Message
    }
}
finally {
    if (Test-Path -LiteralPath $tempPath) {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
    if ($throwawayBackup -and (Test-Path -LiteralPath $throwawayBackup)) {
        Remove-Item -LiteralPath $throwawayBackup -Force -ErrorAction SilentlyContinue
    }
}

if ($failureCode) {
    Complete-Write -Code 2 -ErrorCode $failureCode -Detail $failureDetail
}

$result.Backup = $backupPath
$result.Status = 'Written'

if ($Output -eq 'json') {
    $result.ExitCode = 0
    $result | ConvertTo-Json -Depth 4
}
else {
    Write-Output 'STATE=Written'
    Write-Output ('WROTE=' + $target)
    Write-Output ('ENCODING=' + $Encoding)
    Write-Output ('ENCODING_SOURCE=' + $encodingChoice.Source)
    Write-Output ('BYTES=' + $bytes.Length)
    Write-Output ('BOM=' + $result.Bom)
    Write-Output ('VERIFIED=' + $result.Verified)
    if ($result.Replaced) { Write-Output 'REPLACED=True' }
    if ($backupPath) { Write-Output ('BACKUP=' + $backupPath) }
    Write-Output 'EXITCODE=0'
}

exit 0
