#Requires -Version 5.1
<#
.SYNOPSIS
    Detects and validates the text encoding of scripts and data files.

.DESCRIPTION
    Reads a file as bytes, reports what it really is, then judges that result
    against the rules of a target tool chain: Windows PowerShell 5.1, PowerShell
    7, cmd.exe, Python, Bash or generic data.

    The detector never guesses. A byte stream that fails strict UTF-8 decoding is
    labelled gbk only when the CP936 round trip is byte exact; everything else is
    reported as unknown with confidence=low.

    Read-only. The tool never writes to the inspected file and never changes the
    console code page.

.PARAMETER Path
    One or more files to inspect. Directories are rejected.

.PARAMETER Profile
    Rule set used for the verdict. auto derives it from the file extension:
    .ps1/.psm1/.psd1 -> ps51, .bat/.cmd -> cmd, .py -> python, .sh/.bash -> bash,
    everything else -> data.

.PARAMETER ExpectedEncoding
    Declared encoding. When supplied, a mismatch is a hard failure.

.PARAMETER Output
    text (default) or json.

.PARAMETER FailOnWarning
    Treat WARN as failure, so CI can gate on warnings.

.OUTPUTS
    Exit codes: 0 OK, 1 WARN, 2 FAIL, 3 parameter or I/O error.

.EXAMPLE
    .\Test-ScriptEncoding.ps1 -Path .\build.ps1

.EXAMPLE
    Get-ChildItem -Recurse -Filter *.ps1 | .\Test-ScriptEncoding.ps1 -Profile ps51 -Output Json
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidAssignmentToAutomaticVariable', '',
    Justification = 'Profile is the documented switch name and matches the reference documentation; $PROFILE is never read in this script.')]
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
    [Alias('FullName')]
    [string[]]$Path,

    [ValidateSet('auto', 'ps51', 'ps7', 'cmd', 'python', 'bash', 'data')]
    [string]$Profile = 'auto',

    [ValidateSet('any', 'ascii', 'utf8-bom', 'utf8-nobom', 'gbk', 'utf16le-bom', 'utf16be-bom')]
    [string]$ExpectedEncoding = 'any',

    [ValidateSet('text', 'json')]
    [string]$Output = 'text',

    [switch]$FailOnWarning
)

begin {
    Set-StrictMode -Version 2.0
    $ErrorActionPreference = 'Stop'

    $findings = New-Object System.Collections.ArrayList
    $ioError = $false

    function Get-CodePageEncoding {
        param([int]$CodePage)

        try {
            return [System.Text.Encoding]::GetEncoding($CodePage)
        }
        catch {
            # .NET Core does not ship the code page encodings in the box. PowerShell
            # 7 registers them at startup, a bare hosted runspace may not.
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

    function Resolve-TargetProfile {
        param([string]$Requested, [string]$FilePath)

        if ($Requested -ne 'auto') { return $Requested }
        $ext = [System.IO.Path]::GetExtension($FilePath).ToLowerInvariant()
        switch ($ext) {
            '.ps1' { return 'ps51' }
            '.psm1' { return 'ps51' }
            '.psd1' { return 'ps51' }
            '.bat' { return 'cmd' }
            '.cmd' { return 'cmd' }
            '.py' { return 'python' }
            '.sh' { return 'bash' }
            '.bash' { return 'bash' }
            default { return 'data' }
        }
    }

    function Get-EncodingSnapshot {
        param([byte[]]$Bytes)

        $result = [ordered]@{
            Encoding     = 'unknown'
            Confidence   = 'low'
            Detection    = 'unknown'
            Bom          = 'NONE'
            Bytes        = $Bytes.Length
            NonAscii     = 0
            StrictUtf8   = $false
            GbkRoundTrip = $false
            Utf16Suspect = $false
            NulRatio     = 0.0
        }

        if ($Bytes.Length -eq 0) {
            $result.Encoding = 'ascii'
            $result.Confidence = 'high'
            $result.Detection = 'empty-file'
            $result.StrictUtf8 = $true
            return $result
        }

        foreach ($b in $Bytes) {
            if ($b -gt 0x7F) { $result.NonAscii++ }
        }

        # --- byte order marks -------------------------------------------------
        if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
            $result.Encoding = 'utf8-bom'
            $result.Confidence = 'high'
            $result.Detection = 'bom'
            $result.Bom = 'EFBBBF'
            $result.StrictUtf8 = $true
            return $result
        }
        if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFF -and $Bytes[1] -eq 0xFE) {
            $result.Encoding = 'utf16le-bom'
            $result.Confidence = 'high'
            $result.Detection = 'bom'
            $result.Bom = 'FFFE'
            return $result
        }
        if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFE -and $Bytes[1] -eq 0xFF) {
            $result.Encoding = 'utf16be-bom'
            $result.Confidence = 'high'
            $result.Detection = 'bom'
            $result.Bom = 'FEFF'
            return $result
        }

        # --- UTF-16 without a BOM --------------------------------------------
        # ASCII text stored as UTF-16 is valid UTF-8, so the NUL pattern has to be
        # examined before the UTF-8 attempt; otherwise every BOM-less UTF-16 file
        # would be reported as utf8-nobom.
        $nul = 0
        $nulOdd = 0
        for ($i = 0; $i -lt $Bytes.Length; $i++) {
            if ($Bytes[$i] -eq 0) {
                $nul++
                if ($i % 2 -eq 1) { $nulOdd++ }
            }
        }
        $result.NulRatio = [Math]::Round($nul / $Bytes.Length, 3)

        if ($Bytes.Length -ge 4 -and ($nul / $Bytes.Length) -ge 0.2) {
            $nulEven = $nul - $nulOdd
            if ($nulOdd -ge ($nulEven * 2)) {
                $result.Encoding = 'utf16le-no-bom-suspected'
                $result.Confidence = 'low'
                $result.Detection = 'nul-pattern-odd'
                $result.Utf16Suspect = $true
                return $result
            }
            if ($nulEven -ge ($nulOdd * 2)) {
                $result.Encoding = 'utf16be-no-bom-suspected'
                $result.Confidence = 'low'
                $result.Detection = 'nul-pattern-even'
                $result.Utf16Suspect = $true
                return $result
            }
        }

        # --- strict UTF-8 ------------------------------------------------------
        $strict = New-Object System.Text.UTF8Encoding($false, $true)
        try {
            [void]$strict.GetString($Bytes)
            $result.StrictUtf8 = $true
        }
        catch {
            $result.StrictUtf8 = $false
        }

        if ($result.StrictUtf8) {
            if ($result.NonAscii -eq 0) {
                $result.Encoding = 'ascii'
                $result.Confidence = 'high'
                $result.Detection = 'all-bytes-ascii'
            }
            else {
                $result.Encoding = 'utf8-nobom'
                $result.Confidence = 'high'
                $result.Detection = 'strict-utf8'
            }
            return $result
        }

        # --- CP936, only when the round trip is byte exact ---------------------
        # A failed UTF-8 decode proves nothing on its own: the file may be CP936,
        # truncated, or a mix. Only a lossless CP936 round trip earns the label,
        # and it still only earns medium confidence.
        $gbk = Get-CodePageEncoding -CodePage 936
        if ($gbk) {
            try {
                $decoded = $gbk.GetString($Bytes)
                if ($decoded.IndexOf([char]0xFFFD) -lt 0) {
                    $reencoded = $gbk.GetBytes($decoded)
                    if ($reencoded.Length -eq $Bytes.Length) {
                        $same = $true
                        for ($i = 0; $i -lt $Bytes.Length; $i++) {
                            if ($reencoded[$i] -ne $Bytes[$i]) { $same = $false; break }
                        }
                        if ($same) {
                            $result.GbkRoundTrip = $true
                            $result.Encoding = 'gbk'
                            $result.Confidence = 'medium'
                            $result.Detection = 'cp936-roundtrip'
                            return $result
                        }
                    }
                }
            }
            catch {
                Write-Verbose ('CP936 probe failed: ' + $_.Exception.Message)
            }
        }

        $result.Encoding = 'unknown'
        $result.Confidence = 'low'
        $result.Detection = 'ambiguous-bytes'
        return $result
    }

    function Get-EncodingVerdict {
        param(
            [string]$Encoding,
            [string]$EffectiveProfile,
            [int]$NonAscii
        )

        $reasons = New-Object System.Collections.ArrayList
        $verdict = 'OK'
        $hasNonAscii = $NonAscii -gt 0

        switch ($EffectiveProfile) {
            'ps51' {
                switch ($Encoding) {
                    'ascii' { }
                    'utf8-bom' { }
                    'utf8-nobom' {
                        if ($hasNonAscii) {
                            $verdict = 'FAIL'
                            [void]$reasons.Add('BOMLESS_UTF8_PS51: no BOM with non-ASCII bytes; Windows PowerShell 5.1 decodes the file as the ANSI code page')
                        }
                    }
                    'gbk' {
                        $verdict = 'WARN'
                        [void]$reasons.Add('CP936_PS51: parses only on a host whose ANSI code page is 936; not portable')
                    }
                    'utf16le-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: Windows PowerShell 5.1 cannot parse UTF-16 scripts reliably')
                    }
                    'utf16be-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: Windows PowerShell 5.1 cannot parse UTF-16 scripts reliably')
                    }
                    'utf16le-no-bom-suspected' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_NO_BOM: two byte wide text without a BOM; re-save as UTF-8 with BOM')
                    }
                    'utf16be-no-bom-suspected' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_NO_BOM: two byte wide text without a BOM; re-save as UTF-8 with BOM')
                    }
                    default {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UNKNOWN_ENCODING: neither valid UTF-8 nor a lossless CP936 round trip')
                    }
                }
            }
            'ps7' {
                switch ($Encoding) {
                    'ascii' { }
                    'utf8-nobom' { }
                    'utf8-bom' {
                        [void]$reasons.Add('UTF8_BOM_ACCEPTED: PowerShell 7 honours the BOM; the BOM is redundant but harmless')
                    }
                    'gbk' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('CP936_PS7: PowerShell 7 reads BOM-less files as UTF-8, so non-ASCII text becomes replacement characters')
                    }
                    'utf16le-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: keep scripts in UTF-8')
                    }
                    'utf16be-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: keep scripts in UTF-8')
                    }
                    'utf16le-no-bom-suspected' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_NO_BOM: re-save as UTF-8')
                    }
                    'utf16be-no-bom-suspected' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_NO_BOM: re-save as UTF-8')
                    }
                    default {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UNKNOWN_ENCODING: could not be determined')
                    }
                }
            }
            'cmd' {
                switch ($Encoding) {
                    'ascii' { }
                    'gbk' { }
                    'utf8-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('CMD_UTF8_BOM: cmd.exe feeds the BOM bytes to the first command, which fails with a not recognized error')
                    }
                    'utf8-nobom' {
                        if ($hasNonAscii) {
                            $verdict = 'WARN'
                            [void]$reasons.Add('CMD_UTF8_NO_BOM: cmd.exe parses the bytes as the OEM code page; add chcp 65001 or save as CP936')
                        }
                    }
                    'utf16le-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: cmd.exe cannot parse UTF-16 batch files')
                    }
                    'utf16be-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: cmd.exe cannot parse UTF-16 batch files')
                    }
                    default {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UNKNOWN_ENCODING: could not be determined')
                    }
                }
            }
            'python' {
                switch ($Encoding) {
                    'ascii' { }
                    'utf8-nobom' { }
                    'utf8-bom' {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UTF8_BOM_PYTHON: Python 3 tolerates a UTF-8 BOM but tools that read the first line as text do not')
                    }
                    'gbk' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('CP936_PYTHON: Python 3 decodes source as UTF-8 by default')
                    }
                    'utf16le-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: Python source must be UTF-8')
                    }
                    'utf16be-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: Python source must be UTF-8')
                    }
                    default {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UNKNOWN_ENCODING: could not be determined')
                    }
                }
            }
            'bash' {
                switch ($Encoding) {
                    'ascii' { }
                    'utf8-nobom' { }
                    'utf8-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('BASH_UTF8_BOM: the BOM precedes the shebang and the file is no longer executable')
                    }
                    'gbk' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('CP936_BASH: POSIX shells expect UTF-8 on a UTF-8 locale')
                    }
                    'utf16le-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED')
                    }
                    'utf16be-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED')
                    }
                    default {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UNKNOWN_ENCODING: could not be determined')
                    }
                }
            }
            default {
                switch ($Encoding) {
                    'ascii' { }
                    'utf8-nobom' { }
                    'utf8-bom' {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UTF8_BOM_DATA: many JSON, YAML and INI parsers reject a BOM')
                    }
                    'gbk' {
                        $verdict = 'WARN'
                        [void]$reasons.Add('CP936_DATA: consumers that assume UTF-8 will mis-decode this file')
                    }
                    'utf16le-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: keep data files in UTF-8')
                    }
                    'utf16be-bom' {
                        $verdict = 'FAIL'
                        [void]$reasons.Add('UTF16_UNSUPPORTED: keep data files in UTF-8')
                    }
                    default {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UNKNOWN_ENCODING: could not be determined')
                    }
                }
            }
        }

        return [pscustomobject]@{
            Verdict = $verdict
            Reasons = $reasons
        }
    }
}

process {
    foreach ($candidate in $Path) {
        $resolved = $null
        try {
            $resolved = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).ProviderPath
        }
        catch {
            $ioError = $true
            [Console]::Error.WriteLine(('ERROR=NOT_FOUND path=' + $candidate))
            continue
        }

        if (Test-Path -LiteralPath $resolved -PathType Container) {
            $ioError = $true
            [Console]::Error.WriteLine(('ERROR=IS_DIRECTORY path=' + $resolved))
            continue
        }

        $resolvedProfile = Resolve-TargetProfile -Requested $Profile -FilePath $resolved

        try {
            $bytes = [System.IO.File]::ReadAllBytes($resolved)
        }
        catch {
            $ioError = $true
            [Console]::Error.WriteLine(('ERROR=READ_FAILED path=' + $resolved + ' ' + $_.Exception.Message))
            continue
        }

        $measured = Get-EncodingSnapshot -Bytes $bytes
        $judgement = Get-EncodingVerdict -Encoding $measured.Encoding -EffectiveProfile $resolvedProfile -NonAscii $measured.NonAscii

        $expectedMatch = $null
        if ($ExpectedEncoding -ne 'any') {
            $compatible = ($measured.Encoding -eq $ExpectedEncoding)
            if (($ExpectedEncoding -eq 'utf8-nobom') -and ($measured.Encoding -eq 'ascii')) { $compatible = $true }
            if (($ExpectedEncoding -eq 'ascii') -and ($measured.Encoding -eq 'utf8-nobom')) { $compatible = $true }
            $expectedMatch = $compatible
            if (-not $compatible) {
                $judgement.Verdict = 'FAIL'
                [void]$judgement.Reasons.Add(('EXPECTED_MISMATCH: declared {0} but detected {1}' -f $ExpectedEncoding, $measured.Encoding))
            }
        }

        $item = [ordered]@{
            Path          = $resolved
            Profile       = $resolvedProfile
            Encoding      = $measured.Encoding
            Confidence    = $measured.Confidence
            Detection     = $measured.Detection
            Bom           = $measured.Bom
            Bytes         = $measured.Bytes
            NonAsciiBytes = $measured.NonAscii
            StrictUtf8    = $measured.StrictUtf8
            GbkRoundTrip  = $measured.GbkRoundTrip
            Utf16Suspect  = $measured.Utf16Suspect
            Expected      = $ExpectedEncoding
            ExpectedMatch = $expectedMatch
            Verdict       = $judgement.Verdict
            Reasons       = @($judgement.Reasons)
        }
        [void]$findings.Add($item)
    }
}

end {
    $okCount = 0
    $warnCount = 0
    $failCount = 0
    foreach ($f in $findings) {
        switch ($f.Verdict) {
            'OK' { $okCount++ }
            'WARN' { $warnCount++ }
            'FAIL' { $failCount++ }
        }
    }

    if ($ioError) {
        $exitCode = 3
    }
    elseif ($failCount -gt 0) {
        $exitCode = 2
    }
    elseif ($warnCount -gt 0) {
        if ($FailOnWarning) { $exitCode = 2 } else { $exitCode = 1 }
    }
    else {
        $exitCode = 0
    }

    $worst = 'OK'
    if ($failCount -gt 0) { $worst = 'FAIL' }
    elseif ($warnCount -gt 0) { $worst = 'WARN' }

    if ($Output -eq 'json') {
        $document = [ordered]@{
            Tool       = 'Test-ScriptEncoding.ps1'
            Version    = '1.0.0'
            Runtime    = $PSVersionTable.PSEdition
            PSVersion  = $PSVersionTable.PSVersion.ToString()
            Profile    = $Profile
            Expected   = $ExpectedEncoding
            FailOnWarn = [bool]$FailOnWarning
            Files      = @($findings)
            Summary    = [ordered]@{
                Files    = $findings.Count
                Ok       = $okCount
                Warn     = $warnCount
                Fail     = $failCount
                ExitCode = $exitCode
            }
            Verdict    = $worst
            ExitCode   = $exitCode
        }
        $document | ConvertTo-Json -Depth 6
    }
    else {
        foreach ($f in $findings) {
            Write-Output ('FILE=' + $f.Path)
            Write-Output ('PROFILE=' + $f.Profile)
            Write-Output ('ENCODING=' + $f.Encoding)
            Write-Output ('CONFIDENCE=' + $f.Confidence)
            Write-Output ('DETECTION=' + $f.Detection)
            Write-Output ('BOM=' + $f.Bom)
            Write-Output ('BYTES=' + $f.Bytes)
            Write-Output ('NON_ASCII_BYTES=' + $f.NonAsciiBytes)
            Write-Output ('STRICT_UTF8=' + $f.StrictUtf8)
            Write-Output ('GBK_ROUNDTRIP=' + $f.GbkRoundTrip)
            Write-Output ('UTF16_SUSPECTED=' + $f.Utf16Suspect)
            Write-Output ('EXPECTED=' + $f.Expected)
            Write-Output ('EXPECTED_MATCH=' + $f.ExpectedMatch)
            Write-Output ('VERDICT=' + $f.Verdict)
            foreach ($r in $f.Reasons) {
                Write-Output ('REASON=' + $r)
            }
            Write-Output '---'
        }
        Write-Output ('RUNTIME=' + $PSVersionTable.PSEdition)
        Write-Output ('SUMMARY files={0} ok={1} warn={2} fail={3} exit={4}' -f $findings.Count, $okCount, $warnCount, $failCount, $exitCode)
    }

    exit $exitCode
}
