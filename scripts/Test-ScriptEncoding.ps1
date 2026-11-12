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

    A byte order mark is a claim, not a proof: when a file starts with EF BB BF,
    FF FE or FE FF, the bytes after the mark are still decoded strictly, and a
    payload that does not decode is reported as an invalid-encoding failure
    instead of a pass. See references/encoding-matrix.md.

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

    The comparison is asymmetric: ascii means every byte is 0x00-0x7F, so a
    utf8-nobom file with non-ASCII bytes and any file carrying a BOM both fail
    it; a pure ASCII file does satisfy utf8-nobom, because ASCII is a strict
    subset of UTF-8.

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
    $script:pipelineRan = $false

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

    function Copy-Range {
        param([byte[]]$Bytes, [int]$Offset)

        $count = $Bytes.Length - $Offset
        if ($count -le 0) { return (New-Object 'byte[]' 0) }
        $slice = New-Object 'byte[]' $count
        [Array]::Copy($Bytes, $Offset, $slice, 0, $count)
        return $slice
    }

    function Test-ByteInRange {
        param([byte]$Value, [int]$Low, [int]$High)
        return (($Value -ge $Low) -and ($Value -le $High))
    }

    function Get-Utf8InvalidOffset {
        <#
            Returns the offset of the first byte that cannot begin or continue a
            well formed UTF-8 sequence, or -1 when the slice is valid.

            DecoderFallbackException.Index cannot answer this: measured on this
            machine it reports -1 for a lone FF and -2 for a truncated E4 B8, so
            the offset it carries is not an offset at all. The decoder still owns
            the valid/invalid decision; this scan only names the position.
        #>
        param([byte[]]$Slice)

        $i = 0
        $n = $Slice.Length
        while ($i -lt $n) {
            $b = [int]$Slice[$i]
            if ($b -le 0x7F) { $i++; continue }

            $need = 0
            $firstLow = 0x80
            $firstHigh = 0xBF
            if ($b -ge 0xC2 -and $b -le 0xDF) { $need = 1 }
            elseif ($b -eq 0xE0) { $need = 2; $firstLow = 0xA0 }
            elseif ($b -ge 0xE1 -and $b -le 0xEC) { $need = 2 }
            elseif ($b -eq 0xED) { $need = 2; $firstHigh = 0x9F }
            elseif ($b -ge 0xEE -and $b -le 0xEF) { $need = 2 }
            elseif ($b -eq 0xF0) { $need = 3; $firstLow = 0x90 }
            elseif ($b -ge 0xF1 -and $b -le 0xF3) { $need = 3 }
            elseif ($b -eq 0xF4) { $need = 3; $firstHigh = 0x8F }
            else { return $i }

            if (($i + $need) -ge $n) { return $i }
            for ($k = 1; $k -le $need; $k++) {
                $low = 0x80
                $high = 0xBF
                if ($k -eq 1) { $low = $firstLow; $high = $firstHigh }
                if (-not (Test-ByteInRange -Value $Slice[$i + $k] -Low $low -High $high)) { return $i }
            }
            $i += $need + 1
        }
        return -1
    }

    function Get-Utf16InvalidOffset {
        <#
            Same idea for UTF-16: returns the offset of an unpaired surrogate or
            of a truncated final code unit, -1 when the slice is valid text.
        #>
        param([byte[]]$Slice, [bool]$BigEndian)

        $i = 0
        $n = $Slice.Length
        while (($i + 1) -lt $n) {
            if ($BigEndian) { $unit = ([int]$Slice[$i] -shl 8) -bor [int]$Slice[$i + 1] }
            else { $unit = ([int]$Slice[$i + 1] -shl 8) -bor [int]$Slice[$i] }

            if ($unit -ge 0xD800 -and $unit -le 0xDBFF) {
                if (($i + 3) -ge $n) { return $i }
                if ($BigEndian) { $next = ([int]$Slice[$i + 2] -shl 8) -bor [int]$Slice[$i + 3] }
                else { $next = ([int]$Slice[$i + 3] -shl 8) -bor [int]$Slice[$i + 2] }
                if ($next -lt 0xDC00 -or $next -gt 0xDFFF) { return $i }
                $i += 4
                continue
            }
            if ($unit -ge 0xDC00 -and $unit -le 0xDFFF) { return $i }
            $i += 2
        }
        if ($i -lt $n) { return $i }
        return -1
    }

    function Test-StrictUtf8Payload {
        <#
            Decodes the bytes after Offset with a throwing decoder. Returns $null
            when they are valid UTF-8, otherwise the absolute offset of the first
            byte that is not.

            A BOM is a claim, not a proof. EF BB BF followed by FF is a corrupt
            file, and the detector used to answer OK for it because it returned
            as soon as it saw the mark and never looked at the payload.
        #>
        param([byte[]]$Bytes, [int]$Offset)

        if ($Bytes.Length -le $Offset) { return $null }
        $slice = Copy-Range -Bytes $Bytes -Offset $Offset
        $strict = New-Object System.Text.UTF8Encoding($false, $true)
        try {
            [void]$strict.GetString($slice)
            return $null
        }
        catch [System.Text.DecoderFallbackException] {
            $bad = Get-Utf8InvalidOffset -Slice $slice
            if ($bad -lt 0) { $bad = 0 }
            return [pscustomobject]@{
                Offset = ($Offset + $bad)
                Detail = 'the byte sequence is not valid UTF-8'
            }
        }
    }

    function Test-StrictUtf16Payload {
        <#
            Decodes the bytes after Offset as UTF-16 with a throwing decoder.
            Returns $null when valid, otherwise a descriptor.

            Two failure modes matter here and neither is caught by a lenient
            decoder: an odd byte count (the last code unit is truncated) and an
            unpaired surrogate. Both are reported by Windows PowerShell 5.1 as a
            broken token while the process still exits 0, so the file has to be
            rejected before anyone runs it.
        #>
        param([byte[]]$Bytes, [int]$Offset, [bool]$BigEndian)

        $remaining = $Bytes.Length - $Offset
        if ($remaining -le 0) { return $null }
        if (($remaining % 2) -ne 0) {
            return [pscustomobject]@{
                Offset = ($Bytes.Length - 1)
                Detail = 'odd byte count: the final UTF-16 code unit is truncated'
            }
        }
        $slice = Copy-Range -Bytes $Bytes -Offset $Offset
        $encoding = New-Object System.Text.UnicodeEncoding($BigEndian, $false, $true)
        try {
            [void]$encoding.GetString($slice)
            return $null
        }
        catch [System.Text.DecoderFallbackException] {
            $bad = Get-Utf16InvalidOffset -Slice $slice -BigEndian $BigEndian
            if ($bad -lt 0) { $bad = 0 }
            return [pscustomobject]@{
                Offset = ($Offset + $bad)
                Detail = 'unpaired surrogate'
            }
        }
        catch [System.ArgumentException] {
            return [pscustomobject]@{
                Offset = $Offset
                Detail = $_.Exception.Message
            }
        }
    }

    function Get-EncodingSnapshot {
        param([byte[]]$Bytes)

        $result = [ordered]@{
            Encoding       = 'unknown'
            Confidence     = 'low'
            Detection      = 'unknown'
            Bom            = 'NONE'
            Bytes          = $Bytes.Length
            NonAscii       = 0
            StrictUtf8     = $false
            GbkRoundTrip   = $false
            Utf16Suspect   = $false
            NulRatio       = 0.0
            PayloadValid   = $true
            PayloadProblem = ''
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
        # Every BOM branch validates the payload behind the mark. Detecting the
        # mark answers "what did the producer claim", not "is the file readable".
        if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
            $result.Bom = 'EFBBBF'
            $result.Confidence = 'high'
            $problem = Test-StrictUtf8Payload -Bytes $Bytes -Offset 3
            if ($null -eq $problem) {
                $result.Encoding = 'utf8-bom'
                $result.Detection = 'bom'
                $result.StrictUtf8 = $true
            }
            else {
                $result.Encoding = 'utf8-bom-invalid'
                $result.Detection = 'bom-invalid-payload'
                $result.StrictUtf8 = $false
                $result.PayloadValid = $false
                $result.PayloadProblem = ('UTF-8 BOM followed by invalid UTF-8 at byte {0}: {1}' -f $problem.Offset, $problem.Detail)
            }
            return $result
        }
        if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFF -and $Bytes[1] -eq 0xFE) {
            $result.Bom = 'FFFE'
            $result.Confidence = 'high'
            $problem = Test-StrictUtf16Payload -Bytes $Bytes -Offset 2 -BigEndian $false
            if ($null -eq $problem) {
                $result.Encoding = 'utf16le-bom'
                $result.Detection = 'bom'
            }
            else {
                $result.Encoding = 'utf16le-bom-invalid'
                $result.Detection = 'bom-invalid-payload'
                $result.PayloadValid = $false
                $result.PayloadProblem = ('UTF-16LE BOM followed by invalid UTF-16 at byte {0}: {1}' -f $problem.Offset, $problem.Detail)
            }
            return $result
        }
        if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFE -and $Bytes[1] -eq 0xFF) {
            $result.Bom = 'FEFF'
            $result.Confidence = 'high'
            $problem = Test-StrictUtf16Payload -Bytes $Bytes -Offset 2 -BigEndian $true
            if ($null -eq $problem) {
                $result.Encoding = 'utf16be-bom'
                $result.Detection = 'bom'
            }
            else {
                $result.Encoding = 'utf16be-bom-invalid'
                $result.Detection = 'bom-invalid-payload'
                $result.PayloadValid = $false
                $result.PayloadProblem = ('UTF-16BE BOM followed by invalid UTF-16 at byte {0}: {1}' -f $problem.Offset, $problem.Detail)
            }
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
            [int]$NonAscii,
            [string]$PayloadProblem
        )

        # A payload that does not decode is a failure in every profile: no
        # consumer of any kind can read it. This is checked before the profile
        # switch so that no profile can accidentally rate a corrupt file as OK.
        if ($PayloadProblem) {
            return [pscustomobject]@{
                Verdict = 'FAIL'
                Reasons = @(('INVALID_ENCODING_PAYLOAD: ' + $PayloadProblem))
            }
        }

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
                        $verdict = 'WARN'
                        [void]$reasons.Add('UTF16LE_RUNNABLE_NOT_PREFERRED: verified on Windows PowerShell 5.1.26100 and PowerShell 7.6.9 that UTF-16LE with BOM is parsed and executed by both; it is still not the recommended storage because cmd.exe, git diff, editors and most text tools read it as binary or mojibake. Keep scripts in UTF-8 with BOM')
                    }
                    'utf16be-bom' {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UTF16BE_RUNNABLE_NOT_PREFERRED: verified on Windows PowerShell 5.1.26100 and PowerShell 7.7.0 that the FE FF mark is honoured and the script runs, CJK included. It is still not the recommended storage: cmd.exe, git diff, editors and most text tools read it as binary or mojibake. Keep scripts in UTF-8 with BOM')
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
                        $verdict = 'WARN'
                        [void]$reasons.Add('UTF16LE_RUNNABLE_NOT_PREFERRED: both runtimes do parse and run UTF-16LE with BOM, but the file is unreadable to git, editors and most tools. Keep scripts in UTF-8')
                    }
                    'utf16be-bom' {
                        $verdict = 'WARN'
                        [void]$reasons.Add('UTF16BE_RUNNABLE_NOT_PREFERRED: both runtimes parse it, but nothing else on the machine expects UTF-16BE. Keep scripts in UTF-8')
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
                        [void]$reasons.Add('UTF16_UNSUPPORTED: verified that cmd.exe feeds the FF FE mark to the first command and fails with "is not recognized"; a UTF-16 batch file never runs')
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
                        [void]$reasons.Add('UTF16_UNSUPPORTED: verified that Python 3.13 refuses a UTF-16 source file with "Non-UTF-8 code starting with \xff ... no encoding declared"')
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

    function Test-ExpectedEncodingMatch {
        <#
            Asymmetric by design. ASCII is a strict subset of UTF-8, so a pure
            ASCII file does satisfy a utf8-nobom expectation. The reverse is not
            true: a utf8-nobom file with any byte above 0x7F is not ASCII, and a
            BOM is not an ASCII byte either. The previous version had a symmetric
            exception that let "-ExpectedEncoding ascii" pass on a file with 18
            non-ASCII bytes.
        #>
        param([string]$Detected, [string]$Expected)

        if ($Expected -eq 'any') { return $null }

        switch ($Expected) {
            'ascii' { return ($Detected -eq 'ascii') }
            'utf8-nobom' { return (($Detected -eq 'utf8-nobom') -or ($Detected -eq 'ascii')) }
            default { return ($Detected -eq $Expected) }
        }
    }

    function Add-Inspection {
        param([string]$Candidate)

        if (-not $Candidate) {
            $script:ioError = $true
            [Console]::Error.WriteLine('ERROR=EMPTY_PATH')
            return
        }

        $resolved = $null
        try {
            $resolved = (Resolve-Path -LiteralPath $Candidate -ErrorAction Stop).ProviderPath
        }
        catch {
            $script:ioError = $true
            [Console]::Error.WriteLine(('ERROR=NOT_FOUND path=' + $Candidate))
            return
        }

        if (Test-Path -LiteralPath $resolved -PathType Container) {
            $script:ioError = $true
            [Console]::Error.WriteLine(('ERROR=IS_DIRECTORY path=' + $resolved))
            return
        }

        $resolvedProfile = Resolve-TargetProfile -Requested $Profile -FilePath $resolved

        try {
            $bytes = [System.IO.File]::ReadAllBytes($resolved)
        }
        catch {
            $script:ioError = $true
            [Console]::Error.WriteLine(('ERROR=READ_FAILED path=' + $resolved + ' ' + $_.Exception.Message))
            return
        }

        $measured = Get-EncodingSnapshot -Bytes $bytes
        $judgement = Get-EncodingVerdict -Encoding $measured.Encoding -EffectiveProfile $resolvedProfile `
            -NonAscii $measured.NonAscii -PayloadProblem $measured.PayloadProblem

        $expectedMatch = $null
        if ($ExpectedEncoding -ne 'any') {
            $expectedMatch = Test-ExpectedEncodingMatch -Detected $measured.Encoding -Expected $ExpectedEncoding
            if (-not $expectedMatch) {
                $judgement.Verdict = 'FAIL'
                $detail = 'declared {0} but detected {1}' -f $ExpectedEncoding, $measured.Encoding
                if ($measured.NonAscii -gt 0) {
                    $detail += (' ({0} non-ASCII bytes)' -f $measured.NonAscii)
                }
                if ($measured.Bom -ne 'NONE') {
                    $detail += (' (BOM={0})' -f $measured.Bom)
                }
                [void]$judgement.Reasons.Add('EXPECTED_MISMATCH: ' + $detail)
            }
        }

        $item = [ordered]@{
            Path           = $resolved
            Profile        = $resolvedProfile
            Encoding       = $measured.Encoding
            Confidence     = $measured.Confidence
            Detection      = $measured.Detection
            Bom            = $measured.Bom
            Bytes          = $measured.Bytes
            NonAsciiBytes  = $measured.NonAscii
            StrictUtf8     = $measured.StrictUtf8
            GbkRoundTrip   = $measured.GbkRoundTrip
            Utf16Suspect   = $measured.Utf16Suspect
            PayloadValid   = $measured.PayloadValid
            PayloadProblem = $measured.PayloadProblem
            Expected       = $ExpectedEncoding
            ExpectedMatch  = $expectedMatch
            Verdict        = $judgement.Verdict
            Reasons        = @($judgement.Reasons)
        }
        [void]$findings.Add($item)
    }
}

process {
    $script:pipelineRan = $true
    foreach ($candidate in $Path) {
        Add-Inspection -Candidate $candidate
    }
}

end {
    # Windows PowerShell skips the process block entirely when the host
    # redirects stdin and the script is started with -File, even though the
    # parameters bound correctly. Without this fallback the tool would report
    # "files=0 exit=0" for a file it never inspected -- a silent false pass.
    if (-not $script:pipelineRan) {
        foreach ($candidate in $Path) {
            Add-Inspection -Candidate $candidate
        }
    }

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
            Version    = '1.0.1'
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
            Write-Output ('PAYLOAD_VALID=' + $f.PayloadValid)
            if ($f.PayloadProblem) {
                Write-Output ('PAYLOAD_PROBLEM=' + $f.PayloadProblem)
            }
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
