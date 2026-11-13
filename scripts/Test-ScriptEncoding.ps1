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

    Python source is judged against the codec the file names in its PEP 263
    line, and each codec is checked with its own rules rather than with CP936:
    GBK and GB2312 are different repertoires, HZ-GB-2312 is a seven bit escape
    encoding, and GB18030 has four byte sequences. A name Python cannot resolve
    is a failure, not a pass.

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

    [ValidateSet('any', 'ascii', 'utf8-bom', 'utf8-nobom', 'gbk', 'utf16le-bom', 'utf16be-bom', 'utf32le-bom', 'utf32be-bom')]
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

    function Get-Utf32InvalidOffset {
        <#
            Returns the offset of the first code unit that is not a Unicode scalar
            value, or -1. Four byte units have two ways to be wrong that a lenient
            decoder hides: a value above U+10FFFF and a surrogate value, which is a
            legal 32 bit number but not a character.

            The shifts are done on [long]: [int] 0xFF -shl 24 overflows into the
            sign bit and every comparison after it is about a negative number.
        #>
        param([byte[]]$Slice, [bool]$BigEndian)

        $i = 0
        $n = $Slice.Length
        while (($i + 3) -lt $n) {
            if ($BigEndian) {
                $unit = ([long]$Slice[$i] -shl 24) -bor ([long]$Slice[$i + 1] -shl 16) -bor `
                    ([long]$Slice[$i + 2] -shl 8) -bor [long]$Slice[$i + 3]
            }
            else {
                $unit = ([long]$Slice[$i + 3] -shl 24) -bor ([long]$Slice[$i + 2] -shl 16) -bor `
                    ([long]$Slice[$i + 1] -shl 8) -bor [long]$Slice[$i]
            }
            if ($unit -gt 0x10FFFF) { return $i }
            if ($unit -ge 0xD800 -and $unit -le 0xDFFF) { return $i }
            $i += 4
        }
        if ($i -lt $n) { return $i }
        return -1
    }

    function Test-StrictUtf32Payload {
        param([byte[]]$Bytes, [int]$Offset, [bool]$BigEndian)

        $remaining = $Bytes.Length - $Offset
        if ($remaining -le 0) { return $null }
        if (($remaining % 4) -ne 0) {
            return [pscustomobject]@{
                Offset = ($Bytes.Length - 1)
                Detail = 'odd byte count: the final UTF-32 code unit is truncated'
            }
        }
        $slice = Copy-Range -Bytes $Bytes -Offset $Offset
        $bad = Get-Utf32InvalidOffset -Slice $slice -BigEndian $BigEndian
        if ($bad -ge 0) {
            return [pscustomobject]@{
                Offset = ($Offset + $bad)
                Detail = 'code point outside the Unicode range or a surrogate value'
            }
        }
        return $null
    }

    function Get-PythonNormalName {
        <#
            CPython's get_normal_name(): lower case, '_' folded to '-', the name
            cut at the first '.', and the utf-8 and iso-8859-1 families collapsed
            to one form each.

            This exists for two rules. A UTF-8 BOM is only allowed when the
            normalised name is exactly "utf-8", and the comparison is made on
            this form rather than on the raw text: "# coding: utf8" plus a BOM
            is a SyntaxError while "# coding: utf-8" plus the same BOM runs, and
            "utf-8-sig" is accepted because it normalises to the "utf-8" prefix.
            Resolve-PythonCodingName then uses the same form to accept spellings
            such as "utf-8-unix" and "iso-latin-1", which codecs.lookup() does
            not resolve but the tokenizer still decodes with.
        #>
        param([string]$Raw)

        $name = $Raw.ToLowerInvariant()
        $dot = $name.IndexOf('.')
        if ($dot -ge 0) { $name = $name.Substring(0, $dot) }
        $name = $name.Replace('_', '-')

        if ($name -eq 'utf-8' -or $name.StartsWith('utf-8-')) { return 'utf-8' }
        # CPython folds the latin-1 family to the ISO number, which is why the
        # SyntaxError for "# coding: latin-1" plus a BOM reads "encoding problem:
        # iso-8859-1 with BOM" while "# coding: latin1" keeps its own spelling.
        if ($name -eq 'latin-1' -or $name -eq 'iso-8859-1' -or $name -eq 'iso-latin-1' -or
            $name.StartsWith('latin-1-') -or $name.StartsWith('iso-8859-1-') -or
            $name.StartsWith('iso-latin-1-')) { return 'iso-8859-1' }
        return $name
    }

    function Resolve-PythonCodingName {
        <#
            Classifies the name written in a PEP 263 line. Three answers, not
            two:

              supported    this tool has a byte level verifier for the codec
              python-only  CPython resolves the name and the file runs, but this
                           tool cannot check the bytes, so it says so instead of
                           pretending the name is invalid
              unknown      no CPython 3 release in this project's test matrix
                           resolves the name, so the file never compiles

            Folding the last two together is what v1.0.2 did, and it failed
            every cp1252, shift_jis and big5 file the interpreter runs happily.
            Folding them the other way would pass a file Python refuses, so the
            two lists are kept apart and both are evidence based.

            Every entry below was checked with codecs.lookup() on CPython 3.13;
            the families are not inferred from the spelling. The negatives
            matter as much as the positives: "windows-936", "cp54936", "54936",
            "hzgb2312" and "cn-gb" all read like aliases and none of them
            resolve. A Windows code page number is not a codec name, and the
            separators in hz-gb-2312 are not optional.

            The four Chinese families stay apart because they are four byte
            layouts, not four spellings of code page 936: GB2312 is a subset of
            GBK, HZ is a seven bit escape encoding of GB2312, and GB18030 adds
            four byte sequences for what neither can carry.
        #>
        param([string]$Raw)

        $name = $Raw.ToLowerInvariant()

        # The tokenizer normalises the name before it looks it up, so every
        # spelling in the utf-8- and iso-latin-1- families behaves like the base
        # codec even though codecs.lookup() rejects the long form: "# coding:
        # utf-8-unix" runs, "# coding: iso-latin-1" runs. Reusing the same
        # normalisation here is what keeps the two from disagreeing.
        $normal = Get-PythonNormalName -Raw $name
        if ($normal -eq 'utf-8') { return [pscustomobject]@{ Name = 'utf-8'; Support = 'supported' } }
        if ($normal -eq 'iso-8859-1') { return [pscustomobject]@{ Name = 'latin-1'; Support = 'supported' } }

        # Verified negatives. Each of these was run through a real interpreter:
        # "# coding: <name>" plus an ASCII body, and CPython raised
        # "encoding problem: <name>". They have to sit in front of the family
        # rules because several of them look exactly like a valid spelling --
        # that is the point of the list. The transforms at the end resolve in
        # codecs.lookup() but are not text codecs, so the tokenizer refuses them
        # rather than guessing.
        foreach ($pattern in @(
                '^windows[-_.]?936$',
                '^cp[-_.]?54936$',
                '^54936$',
                '^hzgb2312$',
                '^cn[-_.]?gb$',
                # The separator is required: "gb2312" is valid, "gb-2312" is not.
                '^gb[-_.]2312$',
                '^gb18030[-_.]2022$',
                '^iso[-_.]?8859[-_.]17$',
                # Only the underscored form resolves; "utf8-sig" does not.
                '^utf8[-_.]sig$',
                '^utf[-_.]?9$',
                # Code page 424 is an alias with no module behind it.
                '^(cp|ibm|csibm)?[-_.]?424$',
                '^ebcdic[-_.]cp[-_.]he$',
                '^cs[-_.]?hp[-_.]?roman8$',
                # "latin2" runs, "latin-2" and "latin_2" do not. Every value of
                # N behaves the same way; latin-1 never reaches this list.
                '^latin[-_.][0-9]+$',
                '^unicode(big|little)unmarked$',
                '^(base64|base_64|bz2|hex|quopri|rot13|rot_13|uu|zip|zlib)([-_.]codec)?$',
                '^quoted[-_.]?printable$'
            )) {
            if ($name -match $pattern) { return [pscustomobject]@{ Name = ''; Support = 'unknown' } }
        }

        switch -Regex ($name) {
            # utf-8-sig is UTF-8 with an optional BOM, so the byte verifier is
            # the same one; only the BOM rule in Get-PythonSourceCoding cares
            # that the name was spelled that way.
            '^(utf[-_]?8|u8|utf|utf[-_]?8[-_]sig)$' { return [pscustomobject]@{ Name = 'utf-8'; Support = 'supported' } }
            '^(ascii|us[-_]?ascii|646)$' { return [pscustomobject]@{ Name = 'ascii'; Support = 'supported' } }
            '^(latin[-_]?1|iso[-_]?8859[-_]?1|8859|cp819|l1)$' { return [pscustomobject]@{ Name = 'latin-1'; Support = 'supported' } }
            '^(gbk|cp[-_]?936|ms[-_]?936|936)$' { return [pscustomobject]@{ Name = 'gbk'; Support = 'supported' } }
            '^(gb2312|euc[-_]?cn|euccn|gb2312[-_.]80|gb2312[-_.]1980|iso[-_]ir[-_]?58|chinese)$' { return [pscustomobject]@{ Name = 'gb2312'; Support = 'supported' } }
            # hzgb2312 is one word Python does not know; the separators matter.
            '^(hz|hzgb|hz[-_.]gb|hz[-_]gb[-_]2312)$' { return [pscustomobject]@{ Name = 'hz'; Support = 'supported' } }
            '^(gb18030|gb18030[-_]2000)$' { return [pscustomobject]@{ Name = 'gb18030'; Support = 'supported' } }
            # Not source encodings: CPython raises "encoding problem: <name>"
            # for a codec that is not ASCII compatible, BOM or no BOM.
            '^(utf[-_]?16|utf[-_]?16[-_]?le|utf[-_]?16[-_]?be|utf16|u16)$' { return [pscustomobject]@{ Name = 'utf-16'; Support = 'supported' } }
            '^(utf[-_]?32|utf[-_]?32[-_]?le|utf[-_]?32[-_]?be|utf32|u32)$' { return [pscustomobject]@{ Name = 'utf-32'; Support = 'supported' } }
        }

        # Codec families CPython ships and this tool does not verify. The list is
        # the ASCII compatible half of encodings/aliases.py written as families
        # rather than as three hundred spellings. cp936 and cp819 are absent on
        # purpose: they are aliases for gbk and latin-1 and were handled above.
        #
        # A name that matches here gets WARN, never FAIL. Missing a spelling that
        # CPython does resolve would turn a working file into a failure -- that
        # is the mistake this list exists to prevent, so the integration suite
        # runs every claimed name through the interpreter instead of trusting
        # the regexes.
        switch -Regex ($name) {
            '^cp[-_.]?(037|154|273|367|437|500|720|737|775|819|850|852|855|856|857|858|860|861|862|863|864|865|866|866u|869|874|875|932|949|950|1006|1026|1051|1125|1140|125[0-8]|1361|65001|gr|is)$' { }
            '^ms[-_.]?(932|949|950|1361|kanji)$' { }
            '^windows[-_.]?(125[0-8]|31j)$' { }
            '^ibm[0-9]{3,5}$' { }
            '^csibm[0-9]{3,5}$' { }
            '^iso[-_.]?8859([-_.](1[0-6]|[2-9]))?([-_.][0-9]{4})?$' { }
            '^iso[-_.]?ir[-_.]?[0-9]{1,3}$' { }
            '^iso[-_.]?646([-_.][a-z0-9]+)*$' { }
            '^iso[-_.]?celtic$' { }
            '^csisolatin[a-z0-9_]*$' { }
            '^csiso[0-9a-z_]*$' { }
            '^cspc[a-z0-9_]*$' { }
            '^csascii$' { }
            '^cs[-_.]?shift[-_.]?jis$' { }
            '^ansi([-_.]x3[-_.]4[-_.][0-9]{4})?$' { }
            '^mbcs$' { }
            '^us$' { }
            '^dbcs$' { }
            # "latin" and "latin2" run; the separated forms are rejected above.
            '^latin([0-9]{1,2})?$' { }
            '^l([2-9]|10)$' { }
            '^r8$' { }
            '^ecma[-_.]?[0-9]{2,3}$' { }
            '^ebcdic[-_.a-z]*$' { }
            '^hp[-_.]?roman8$' { }
            '^roman8$' { }
            '^(cs)?ptcp154$' { }
            '^pt[-_.]?154$' { }
            '^asmo[-_.]?708$' { }
            '^kz[-_.]?1048$' { }
            '^rk1048$' { }
            '^strk1048[-_.]?2002$' { }
            '^ruscii$' { }
            '^mac[-_.]?[a-z0-9]*$' { }
            '^x[-_.]mac[-_.].+$' { }
            '^euc[-_.]?[a-z0-9_]+$' { }
            '^jisx[0-9]+$' { }
            '^u?[-_]?jis$' { }
            '^iso[-_.]?2022[-_.]?[a-z0-9_]+$' { }
            '^(shift|s)[-_.]?jis[a-z0-9_]*$' { }
            '^sjis[a-z0-9_]*$' { }
            '^windows[-_.]?31j$' { }
            '^(big5|csbig5|hkscs)[-_.a-z0-9]*$' { }
            '^korean$' { }
            '^uhc$' { }
            '^ks[-_.]?c[-_.]?5601([-_.][0-9]+)?$' { }
            '^ks[-_.]?x[-_.]?1001$' { }
            '^ksc5601$' { }
            '^ksx1001$' { }
            '^tis[-_.]?620[a-z0-9_]*$' { }
            '^thai$' { }
            '^koi8[-_.]?[ru]$' { }
            '^cskoi8r$' { }
            '^johab$' { }
            '^utf[-_.]?7$' { }
            '^u7$' { }
            '^utf[-_.]?8[-_.]ucs[24]$' { }
            '^unicode[-_.]1[-_.]1[-_.]utf[-_.]7$' { }
            '^arabic$' { }
            '^greek8?$' { }
            '^elot[-_.]?928$' { }
            '^hebrew$' { }
            '^cyrillic([-_.]asian)?$' { }
            '^unicode[-_.]escape$' { }
            '^raw[-_.]unicode[-_.]escape$' { }
            # A bare code page number is a codec alias in CPython ("# coding:
            # 1252" runs). 54936 was already rejected above; it is the one number
            # that reads like an alias and is not one.
            '^[0-9]{3,5}$' { }
            default { return [pscustomobject]@{ Name = ''; Support = 'unknown' } }
        }
        return [pscustomobject]@{ Name = ''; Support = 'python-only' }
    }

    function Test-Gb2312Cell {
        <#
            Is this double byte pair an assigned GB2312 cell?

            Enumerated from the gb2312 codec of CPython 3.13: 7445 of the 8178
            pairs in the A1-F7 / A1-FE grid decode and re-encode byte for byte.
            The assigned area is not a rectangle: zone 10 to 15 (lead AA-AF) is
            empty, and half a dozen symbol rows stop short of FE.

            This is a real table and not a CP936 probe on purpose. CP936 assigns
            much more of the same grid -- GBK extensions such as 81 40 -- so
            asking CP936 accepts bytes that Python rejects under a gb2312
            declaration.
        #>
        param([int]$Lead, [int]$Trail)

        if ($Trail -lt 0xA1 -or $Trail -gt 0xFE) { return $false }
        # Zones 1 and 3 are full rows, so are the 39 first level and 32 second
        # level hanzi zones.
        if ($Lead -eq 0xA1 -or $Lead -eq 0xA3) { return $true }
        if ($Lead -ge 0xB0 -and $Lead -le 0xD6) { return $true }
        if ($Lead -ge 0xD8 -and $Lead -le 0xF7) { return $true }
        switch ($Lead) {
            0xA2 {
                return (($Trail -ge 0xB1 -and $Trail -le 0xE2) -or
                    ($Trail -ge 0xE5 -and $Trail -le 0xEE) -or
                    ($Trail -ge 0xF1 -and $Trail -le 0xFC))
            }
            0xA4 { return ($Trail -le 0xF3) }
            0xA5 { return ($Trail -le 0xF6) }
            0xA6 { return (($Trail -ge 0xA1 -and $Trail -le 0xB8) -or ($Trail -ge 0xC1 -and $Trail -le 0xD8)) }
            0xA7 { return (($Trail -ge 0xA1 -and $Trail -le 0xC1) -or ($Trail -ge 0xD1 -and $Trail -le 0xF1)) }
            0xA8 { return (($Trail -ge 0xA1 -and $Trail -le 0xBA) -or ($Trail -ge 0xC5 -and $Trail -le 0xE9)) }
            0xA9 { return ($Trail -ge 0xA4 -and $Trail -le 0xEF) }
            # The last hanzi zone stops one row early.
            0xD7 { return ($Trail -le 0xF9) }
        }
        return $false
    }

    function Test-Gb2312Payload {
        <#
            EUC-CN as Python knows it: bytes below 0x80 are themselves, every
            other byte starts a pair in the A1-F7 / A1-FE grid. There is no
            single byte range above 0x7F and no lead past F7.
        #>
        param([byte[]]$Slice)

        $i = 0
        while ($i -lt $Slice.Length) {
            $lead = $Slice[$i]
            if ($lead -lt 0x80) {
                $i++
                continue
            }
            if ($lead -lt 0xA1 -or $lead -gt 0xF7) { return $false }
            if ($i + 1 -ge $Slice.Length) { return $false }
            if (-not (Test-Gb2312Cell -Lead $lead -Trail $Slice[$i + 1])) { return $false }
            $i += 2
        }
        return $true
    }

    function Test-HzPayload {
        <#
            HZ-GB-2312 as CPython implements it, byte by byte.

            The encoding is stateful and the two states have different escape
            rules. That asymmetry is the whole job:

              ASCII mode   ~{ opens GB mode; ~~ is a literal tilde; ~<LF> is a
                           line continuation; any byte above 0x7F is an error
              GB mode      ~} closes, and only at a pair edge; every other byte
                           is half of a GB2312 cell shifted down by 0x80, so
                           0x7E is ordinary data when it lands on the second
                           half -- 56 7E is D6 FE, a real cell

            Measured on CPython 3.13. RFC 1843 also allows the line continuation
            inside GB mode and says nothing against ~~ there; the interpreter
            raises UnicodeDecodeError for both. Matching the interpreter is the
            point of this file, so its behaviour wins.

            End of file inside GB mode is tolerated as long as the last pair is
            complete -- the interpreter decodes such a file, and this tool must
            not refuse what Python runs. A single dangling byte is an error. A
            tolerated open run is reported through -Detail rather than swallowed,
            so the verdict can mention it.

            Testing for the tilde before looking at the mode gets three of these
            wrong: it accepts ~~ and ~<LF> inside GB mode, and it refuses a
            legitimate 0x7E trail byte.
        #>
        param([byte[]]$Slice, [ref]$Detail)

        $hasDetail = $PSBoundParameters.ContainsKey('Detail')
        $problem = ''
        $i = 0
        $inGb = $false

        while ($i -lt $Slice.Length) {
            $b = $Slice[$i]

            if ($inGb) {
                if ($b -eq 0x7E -and ($i + 1) -lt $Slice.Length -and $Slice[$i + 1] -eq 0x7D) {
                    $inGb = $false
                    $i += 2
                    continue
                }
                if (($i + 1) -ge $Slice.Length) {
                    $problem = ('the file ends with a single byte inside GB mode at offset {0}' -f $i)
                    break
                }
                $second = $Slice[$i + 1]
                # Shifting either half up by 0x80 has to land inside the GB2312
                # grid, so both bytes are printable ASCII and nothing else.
                if ($b -lt 0x21 -or $b -gt 0x7E) {
                    $problem = ('byte 0x{0:X2} at offset {1} cannot be half of a GB2312 cell' -f $b, $i)
                    break
                }
                if ($second -lt 0x21 -or $second -gt 0x7E) {
                    $problem = ('byte 0x{0:X2} at offset {1} cannot be half of a GB2312 cell' -f $second, ($i + 1))
                    break
                }
                if (-not (Test-Gb2312Cell -Lead ($b + 0x80) -Trail ($second + 0x80))) {
                    $problem = ('{0:X2} {1:X2} at offset {2} is not an assigned GB2312 cell' -f ($b + 0x80), ($second + 0x80), $i)
                    break
                }
                $i += 2
                continue
            }

            if ($b -eq 0x7E) {
                if (($i + 1) -ge $Slice.Length) {
                    $problem = ('a lone tilde at offset {0} has nothing to escape' -f $i)
                    break
                }
                $next = $Slice[$i + 1]
                if ($next -eq 0x7E -or $next -eq 0x0A) { $i += 2; continue }
                if ($next -eq 0x7B) { $inGb = $true; $i += 2; continue }
                $problem = ('0x7E 0x{0:X2} at offset {1} is not a legal escape in ASCII mode' -f $next, $i)
                break
            }
            if ($b -gt 0x7F) {
                $problem = ('byte 0x{0:X2} at offset {1} is above 0x7F, which HZ does not allow' -f $b, $i)
                break
            }
            $i++
        }

        if ($problem) {
            if ($hasDetail) { $Detail.Value = $problem }
            return $false
        }
        if ($inGb -and $hasDetail) { $Detail.Value = 'unterminated' }
        return $true
    }

    function Test-GbkCell {
        <#
            Is this double byte pair assigned in GBK?

            Enumerated from the gbk codec of CPython 3.13: 21791 of the 23940
            candidate pairs decode and re-encode byte for byte. The holes are
            structural rather than scattered -- the GB2312 symbol zones A1-A7
            carry trails above A0 only, A8 and A9 keep most of their low range
            but lose its tail, the empty GB2312 zones AA-AF are assigned only in
            the low trail range, and F8-FE is mostly unassigned.

            Windows code page 936 is not a substitute and never was. It maps
            every one of those 2149 open cells to a private use character, so a
            CP936 round trip accepts bytes Python raises UnicodeDecodeError for.
            That is how a UTF-8 byte stream came to be reported as valid GBK: 0xAD
            is a legal CP936 lead and an unassigned GBK cell.
        #>
        param([int]$Lead, [int]$Trail)

        if ($Lead -lt 0x81 -or $Lead -gt 0xFE) { return $false }
        if ($Trail -eq 0x7F) { return $false }
        if ($Trail -lt 0x40 -or $Trail -gt 0xFE) { return $false }

        if ($Trail -le 0xA0) {
            # The low trail range is the GBK extension area. It is assigned for
            # every lead except the GB2312 symbol zones, and only its first
            # sixteen values exist at the very end of the lead range.
            if ($Lead -ge 0xA1 -and $Lead -le 0xA7) { return $false }
            if ($Lead -eq 0xA8) { return ($Trail -le 0x95) }
            if ($Lead -eq 0xA9) {
                # A9 keeps most of the low range and loses a scattered tail plus
                # a run of four singles; those are real codec holes, not noise.
                return -not (($Trail -eq 0x58) -or ($Trail -eq 0x5B) -or
                    ($Trail -ge 0x5D -and $Trail -le 0x5F) -or
                    ($Trail -ge 0x89 -and $Trail -le 0x95) -or
                    ($Trail -ge 0x97))
            }
            if ($Lead -eq 0xFE) { return ($Trail -le 0x4F) }
            return $true
        }

        # High trail range: the GB2312 area plus GBK's own additions to it.
        if ($Lead -le 0xA0) { return $true }
        if ($Lead -ge 0xAA -and $Lead -le 0xAF) { return $false }
        if ($Lead -ge 0xB0 -and $Lead -le 0xD6) { return $true }
        if ($Lead -eq 0xD7) { return ($Trail -le 0xF9) }
        if ($Lead -ge 0xD8 -and $Lead -le 0xF7) { return $true }
        if ($Lead -ge 0xF8) { return $false }

        switch ($Lead) {
            0xA2 {
                return -not (($Trail -ge 0xAB -and $Trail -le 0xB0) -or
                    ($Trail -ge 0xE3 -and $Trail -le 0xE4) -or
                    ($Trail -ge 0xEF -and $Trail -le 0xF0) -or
                    ($Trail -ge 0xFD))
            }
            0xA4 { return ($Trail -le 0xF3) }
            0xA5 { return ($Trail -le 0xF6) }
            0xA6 {
                return -not (($Trail -ge 0xB9 -and $Trail -le 0xC0) -or
                    ($Trail -ge 0xD9 -and $Trail -le 0xDF) -or
                    ($Trail -ge 0xEC -and $Trail -le 0xED) -or
                    ($Trail -eq 0xF3) -or
                    ($Trail -ge 0xF6))
            }
            0xA7 {
                return -not (($Trail -ge 0xC2 -and $Trail -le 0xD0) -or ($Trail -ge 0xF2))
            }
            0xA8 {
                return -not (($Trail -eq 0xBC) -or ($Trail -eq 0xBF) -or
                    ($Trail -ge 0xC1 -and $Trail -le 0xC4) -or ($Trail -ge 0xEA))
            }
            0xA9 {
                return -not (($Trail -ge 0x97 -and $Trail -le 0xA3) -or ($Trail -ge 0xF0))
            }
        }
        # A1 and A3 are the two symbol zones GBK fills completely.
        return $true
    }

    function Test-GbkPayload {
        <#
            GBK as CPython decodes it: ASCII, then double byte cells from the
            table above. 0x80 and 0xFF are errors -- Windows code page 936 maps
            them to the euro sign and to U+F8F5, which is why this check cannot
            be a CP936 round trip.
        #>
        param([byte[]]$Slice)

        $i = 0
        while ($i -lt $Slice.Length) {
            $b = $Slice[$i]
            if ($b -le 0x7F) {
                $i++
                continue
            }
            if ($b -eq 0x80 -or $b -eq 0xFF) { return $false }
            if (($i + 1) -ge $Slice.Length) { return $false }
            if (-not (Test-GbkCell -Lead $b -Trail $Slice[$i + 1])) { return $false }
            $i += 2
        }
        return $true
    }

    function Test-CodingDecodes {
        <#
            Does the whole payload survive the declared codec? "Decodes" alone is
            not enough for a multi byte code page: a lossy decode followed by a
            re-encode produces different bytes, so both halves are checked. That
            is also what CPython ends up enforcing -- a declaration that decodes
            but does not re-encode raises SyntaxError: encoding problem.

            -Detail carries a codec specific note back to the caller. HZ uses it
            to report a run that never closed; that is not a decode failure, so
            the return value stays $true.
        #>
        param([byte[]]$Slice, [string]$Canonical, [ref]$Detail)

        switch ($Canonical) {
            'utf-8' {
                $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
                try { [void]$utf8.GetString($Slice); return $true }
                catch { return $false }
            }
            'ascii' {
                foreach ($b in $Slice) { if ($b -gt 0x7F) { return $false } }
                return $true
            }
            'latin-1' {
                # ISO-8859-1 maps all 256 byte values, so no byte string is
                # invalid Latin-1 and there is nothing to verify here. Whether
                # the bytes are *meant* to be Latin-1 is asked against the
                # detector's own label in Test-PythonCodingAgrees, not here:
                # folding the two questions together is what made a legal
                # non-ASCII Latin-1 file look like a conflict.
                return $true
            }
            # Neither of these is a Windows code page, so neither can be handled
            # by the round trip below. GB2312 is a table of assigned cells and
            # HZ is a state machine over that table; both are checked directly.
            'gb2312' { return (Test-Gb2312Payload -Slice $Slice) }
            'hz' {
                if ($Detail) { return (Test-HzPayload -Slice $Slice -Detail $Detail) }
                return (Test-HzPayload -Slice $Slice)
            }
            'gbk' { return (Test-GbkPayload -Slice $Slice) }
            'gb18030' { $codePage = 54936 }
            default { return $false }
        }

        $codec = Get-CodePageEncoding -CodePage $codePage
        if (-not $codec) { return $false }
        try {
            $text = $codec.GetString($Slice)
            if ($text.IndexOf([char]0xFFFD) -ge 0) { return $false }
            $back = $codec.GetBytes($text)
            if ($back.Length -ne $Slice.Length) { return $false }
            for ($i = 0; $i -lt $Slice.Length; $i++) {
                if ($back[$i] -ne $Slice[$i]) { return $false }
            }
            return $true
        }
        catch {
            return $false
        }
    }

    function Get-PythonSourceCoding {
        <#
            PEP 263: a comment on line 1, or on line 2 when line 1 is blank or a
            comment too, may declare the source encoding as
            `coding: <name>` or `coding=<name>`.

            This is source encoding detection, not a Python parser. Only the first
            two physical lines are read, only a comment can carry the declaration,
            and the bytes are still checked against the named codec afterwards.
        #>
        param([byte[]]$Bytes)

        $coding = [ordered]@{
            Parsed      = $false
            Raw         = ''
            Canonical   = ''
            Support     = ''
            Line        = 0
            Problem     = ''
            ProblemKind = ''
            OpenAtEof   = $false
            Repertoire  = @()
        }

        # A UTF-8 BOM sits before the first line. It is not part of the comment,
        # and a Latin-1 reading of it would hide the '#' from the pattern.
        $start = 0
        if ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF) {
            $start = 3
        }

        $lines = New-Object System.Collections.ArrayList
        $current = New-Object System.Collections.ArrayList
        for ($i = $start; $i -lt $Bytes.Length -and $lines.Count -lt 2; $i++) {
            if ($Bytes[$i] -eq 0x0A) {
                [void]$lines.Add([byte[]]$current.ToArray())
                $current.Clear()
                continue
            }
            [void]$current.Add($Bytes[$i])
        }
        if ($lines.Count -lt 2) { [void]$lines.Add([byte[]]$current.ToArray()) }

        $pattern = '^[ \t\f]*#.*?coding[:=][ \t]*([-_.a-zA-Z0-9]+)'
        for ($index = 0; $index -lt $lines.Count; $index++) {
            $text = -join ($lines[$index] | ForEach-Object { [char]$_ })
            if ($text -match $pattern) {
                $coding.Parsed = $true
                $coding.Raw = $matches[1]
                $coding.Line = $index + 1
                break
            }
            # Line 2 only counts when line 1 could not have been code.
            $trimmed = $text.Trim()
            if ($trimmed -ne '' -and -not $trimmed.StartsWith('#')) { break }
        }

        if (-not $coding.Parsed) { return $coding }

        $resolved = Resolve-PythonCodingName -Raw $coding.Raw
        $coding.Support = $resolved.Support

        if ($resolved.Support -eq 'unknown') {
            $coding.ProblemKind = 'unknown-name'
            $coding.Problem = ("'{0}' is not a codec name that CPython 3 resolves, so the file never compiles; a Windows code page number is not a codec name, and neither is a spelling with the separators dropped" -f $coding.Raw)
            return $coding
        }

        if ($resolved.Name) { $coding.Canonical = $resolved.Name }
        else { $coding.Canonical = (Get-PythonNormalName -Raw $coding.Raw) }

        # CPython compares the normalised name with "utf-8" before it decodes
        # anything, and refuses every other declaration outright when a BOM is
        # present. The spelling decides it: "# coding: utf8" plus a BOM raises,
        # "# coding: utf-8" plus the same BOM runs.
        if ($start -eq 3) {
            $normal = Get-PythonNormalName -Raw $coding.Raw
            if ($normal -ne 'utf-8') {
                $coding.ProblemKind = 'bom-conflict'
                $coding.Problem = ("the file starts with a UTF-8 BOM while line {0} declares {1}; CPython raises SyntaxError: encoding problem: {2} with BOM" -f $coding.Line, $coding.Raw, $normal)
                return $coding
            }
        }

        if ($resolved.Support -eq 'python-only') {
            # CPython resolves the name and decodes the file with it. This tool
            # has no verifier for those bytes, so it says exactly that. The
            # empty repertoire keeps the agreement check from claiming anything.
            return $coding
        }

        if ($coding.Canonical -eq 'utf-16' -or $coding.Canonical -eq 'utf-32') {
            # CPython raises "encoding problem" for a codec that is not ASCII
            # compatible, BOM or no BOM.
            $coding.ProblemKind = 'unusable-codec'
            $coding.Problem = ("{0} is a codec but not a usable Python source encoding; CPython raises SyntaxError: encoding problem: {1}" -f $coding.Raw, (Get-PythonNormalName -Raw $coding.Raw))
            return $coding
        }

        $slice = Copy-Range -Bytes $Bytes -Offset $start
        $detail = ''
        if (-not (Test-CodingDecodes -Slice $slice -Canonical $coding.Canonical -Detail ([ref]$detail))) {
            $coding.ProblemKind = 'bytes-mismatch'
            $coding.Problem = ("the bytes are not valid {0}, although line {1} declares it{2}" -f $coding.Canonical, $coding.Line, $(if ($detail) { ': ' + $detail } else { '' }))
            return $coding
        }
        if ($detail -eq 'unterminated') { $coding.OpenAtEof = $true }

        # Which labels the detector may legitimately produce for bytes whose
        # storage the declaration explains. Being a subset is fine: a GB2312 body
        # is also valid GBK, so a gbk declaration decodes it correctly.
        #
        # utf8-* labels are deliberately absent from every non-UTF-8 entry. When
        # the bytes are valid UTF-8 and the file declares something else, two
        # readings are possible -- C3 A9 is U+8305 in GB2312 and U+00E9 in
        # UTF-8 -- and the honest
        # answer is "ambiguous", not a conflict and not a silent pass. Python
        # picks the declaration, so such a file runs; the text just is not what
        # a UTF-8 reader sees.
        $repertoire = @()
        switch ($coding.Canonical) {
            'ascii' { $repertoire = @('ascii') }
            'utf-8' { $repertoire = @('ascii', 'utf8-nobom', 'utf8-bom') }
            'latin-1' { $repertoire = @('ascii', 'gbk', 'unknown') }
            'gbk' { $repertoire = @('ascii', 'gbk') }
            'gb2312' { $repertoire = @('ascii', 'gbk') }
            'gb18030' { $repertoire = @('ascii', 'gbk', 'unknown') }
            'hz' { $repertoire = @('ascii') }
        }
        $coding.Repertoire = $repertoire
        return $coding
    }

    function Test-PythonCodingAgrees {
        <#
            Is the detector's own label inside what the declared codec can hold?

            "Decodes" alone is the wrong question: a UTF-8 file that says
            `coding: gbk` decodes as GBK, into mojibake, and Python runs it. The
            answer is only honest if the bytes are already known to be valid for
            the declared codec -- that is checked before this runs -- and the
            detected label still sits inside the codec's repertoire.
        #>
        param([string]$Detected, [string[]]$Repertoire)

        if (-not $Repertoire -or $Repertoire.Count -eq 0) { return $false }
        return ($Repertoire -contains $Detected)
    }

    function Get-EncodingSnapshot {
        param([byte[]]$Bytes, [string]$EffectiveProfile = 'data')

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
            SourceCoding        = ''
            SourceCodingName    = ''
            SourceCodingLine    = 0
            SourceCodingProblem = ''
            SourceCodingKind    = ''
            SourceCodingSupport = ''
            SourceCodingOpen    = $false
            SourceCodingRepertoire = @()
        }

        # Only Python has a source encoding declaration, so only the python
        # profile pays for reading it. Every other profile keeps the same bytes
        # and the same fields as before.
        if ($EffectiveProfile -eq 'python' -and $Bytes.Length -gt 0) {
            $coding = Get-PythonSourceCoding -Bytes $Bytes
            if ($coding.Parsed) {
                $result.SourceCoding = $coding.Raw
                $result.SourceCodingName = $coding.Canonical
                $result.SourceCodingLine = $coding.Line
                $result.SourceCodingProblem = $coding.Problem
                $result.SourceCodingKind = $coding.ProblemKind
                $result.SourceCodingSupport = $coding.Support
                $result.SourceCodingOpen = [bool]$coding.OpenAtEof
                $result.SourceCodingRepertoire = @($coding.Repertoire)
            }
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
        # --- UTF-32 first, because FF FE 00 00 starts with FF FE ----------------
        # Matching the two byte marks before the four byte ones reported UTF-32LE
        # as UTF-16LE, and every verdict that followed was then about a file that
        # does not exist. The longer mark wins; that is the order the Unicode
        # standard describes and the one every consumer implements.
        if ($Bytes.Length -ge 4 -and $Bytes[0] -eq 0xFF -and $Bytes[1] -eq 0xFE -and
            $Bytes[2] -eq 0x00 -and $Bytes[3] -eq 0x00) {
            $result.Bom = 'FFFE0000'
            $result.Confidence = 'high'
            $problem = Test-StrictUtf32Payload -Bytes $Bytes -Offset 4 -BigEndian $false
            if ($null -eq $problem) {
                $result.Encoding = 'utf32le-bom'
                $result.Detection = 'bom-utf32le'
            }
            else {
                $result.Encoding = 'utf32le-bom-invalid'
                $result.Detection = 'bom-invalid-payload'
                $result.PayloadValid = $false
                $result.PayloadProblem = ('UTF-32LE BOM followed by invalid UTF-32 at byte {0}: {1}' -f $problem.Offset, $problem.Detail)
            }
            return $result
        }
        if ($Bytes.Length -ge 4 -and $Bytes[0] -eq 0x00 -and $Bytes[1] -eq 0x00 -and
            $Bytes[2] -eq 0xFE -and $Bytes[3] -eq 0xFF) {
            $result.Bom = '0000FEFF'
            $result.Confidence = 'high'
            $problem = Test-StrictUtf32Payload -Bytes $Bytes -Offset 4 -BigEndian $true
            if ($null -eq $problem) {
                $result.Encoding = 'utf32be-bom'
                $result.Detection = 'bom-utf32be'
            }
            else {
                $result.Encoding = 'utf32be-bom-invalid'
                $result.Detection = 'bom-invalid-payload'
                $result.PayloadValid = $false
                $result.PayloadProblem = ('UTF-32BE BOM followed by invalid UTF-32 at byte {0}: {1}' -f $problem.Offset, $problem.Detail)
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
            [string]$PayloadProblem,
            [string]$SourceCoding = '',
            [string]$SourceCodingName = '',
            [int]$SourceCodingLine = 0,
            [string]$SourceCodingProblem = '',
            [string]$SourceCodingKind = '',
            [string]$SourceCodingSupport = '',
            [bool]$SourceCodingOpen = $false,
            [string[]]$SourceCodingRepertoire = @()
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

        # UTF-32 is detected so that it is not mistaken for UTF-16, not because
        # anything here supports it. No shell, no cmd.exe and no Python reads a
        # UTF-32 source file, so the answer is the same in every profile.
        if ($Encoding -like 'utf32*') {
            $endianness = 'LE'
            if ($Encoding -like 'utf32be*') { $endianness = 'BE' }
            return [pscustomobject]@{
                Verdict = 'FAIL'
                Reasons = @(('UTF32_UNSUPPORTED: UTF-32{0} with a BOM is decoded as four byte code units; Windows PowerShell, PowerShell 7, cmd.exe and Python all either refuse the file or parse it as binary. Re-save as UTF-8 with BOM' -f $endianness))
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
                if ($SourceCodingProblem -and -not $SourceCodingKind) {
                    # Defensive: every problem carries a kind, and an unlabelled
                    # one must not fall through to the ambiguity branch, which
                    # would downgrade a real error to a warning.
                    $verdict = 'FAIL'
                    [void]$reasons.Add(('PY_SOURCE_CODING_UNKNOWN: ' + $SourceCodingProblem))
                }
                elseif ($SourceCodingSupport -eq 'python-only' -and -not $SourceCodingKind) {
                    # CPython resolves the name and runs the file. This tool has
                    # no verifier for the bytes, so it says so instead of calling
                    # the name invalid -- which is what v1.0.2 did.
                    $verdict = 'WARN'
                    [void]$reasons.Add(('PY_SOURCE_CODING_UNVERIFIED: line {0} declares {1}. CPython resolves that name and the file runs, but this detector has no byte level verifier for it, so the bytes were not checked. It is still not UTF-8, so editors, git and every other tool read it as mojibake' -f $SourceCodingLine, $SourceCoding))
                }
                else {
                    switch ($SourceCodingKind) {
                        'unknown-name' {
                            # CPython cannot look the name up, so it never even
                            # reads the file. Whatever the bytes are is moot.
                            $verdict = 'FAIL'
                            [void]$reasons.Add(('PY_SOURCE_CODING_UNKNOWN: {0}; Python 3 raises SyntaxError for a declaration it cannot resolve' -f $SourceCodingProblem))
                        }
                        'bom-conflict' {
                            $verdict = 'FAIL'
                            [void]$reasons.Add(('PY_SOURCE_CODING_BOM_CONFLICT: {0}; remove the BOM or declare utf-8' -f $SourceCodingProblem))
                        }
                        'unusable-codec' {
                            $verdict = 'FAIL'
                            [void]$reasons.Add(('PY_SOURCE_CODING_UNUSABLE: {0}' -f $SourceCodingProblem))
                        }
                        'bytes-mismatch' {
                            # The declaration resolves, the bytes do not satisfy
                            # it. This is the case CP936 validation used to miss:
                            # GBK extensions are legal GBK and illegal GB2312.
                            $verdict = 'FAIL'
                            [void]$reasons.Add(('PY_SOURCE_CODING_INVALID_BYTES: {0}; Python 3 decodes the file with the declared codec and stops at the first byte that codec cannot map' -f $SourceCodingProblem))
                        }
                        'python-only' {
                            # Kept for completeness: the branch above answers
                            # this case before the switch is reached.
                            $verdict = 'WARN'
                            [void]$reasons.Add(('PY_SOURCE_CODING_UNVERIFIED: line {0} declares {1}. CPython resolves that name and the file runs, but this detector has no byte level verifier for it, so the bytes were not checked. It is still not UTF-8, so editors, git and every other tool read it as mojibake' -f $SourceCodingLine, $SourceCoding))
                        }
                        default {
                            if ($SourceCoding -and -not (Test-PythonCodingAgrees -Detected $Encoding -Repertoire $SourceCodingRepertoire)) {
                                # Two readings fit the same bytes and the file
                                # says which one it wants. Python follows the
                                # declaration and runs; a FAIL here would be a
                                # false alarm, and a silent OK would hide that
                                # the text is not what a UTF-8 reader sees.
                                $verdict = 'WARN'
                                [void]$reasons.Add(('PY_SOURCE_CODING_AMBIGUOUS: line {0} declares {1} and the bytes are valid {1}, but they are also valid {2}. Python 3 decodes with the declaration, so the text reads as {1}; re-save as UTF-8 if the bytes are meant to be UTF-8' -f $SourceCodingLine, $SourceCoding, $Encoding))
                            }
                            else {
                                switch ($Encoding) {
                                    'ascii' {
                                        # Seven bit bytes decode identically
                                        # under every ASCII superset, so a
                                        # declaration costs nothing here --
                                        # except for HZ, where those ASCII bytes
                                        # are escape sequences standing in for
                                        # CJK text.
                                        if ($SourceCodingName -eq 'hz') {
                                            $verdict = 'WARN'
                                            $note = ''
                                            if ($SourceCodingOpen) {
                                                $note = ' The file also ends inside GB mode: the last ~{ run has no closing ~}. CPython decodes it anyway, so this is not an error, but the tail is escape text with no matching close.'
                                            }
                                            [void]$reasons.Add((('PY_SOURCE_CODING_HZ: line {0} declares {1}. The bytes are seven bit HZ-GB-2312, where tilde-brace runs carry the GB2312 characters; every byte is ASCII, so editors, git and grep show the escape text instead of the CJK. Python 3 runs it. Re-save as UTF-8 to make the content readable.' -f $SourceCodingLine, $SourceCoding) + $note))
                                        }
                                    }
                                    'utf8-nobom' { }
                                    'utf8-bom' {
                                        $verdict = 'WARN'
                                        [void]$reasons.Add('UTF8_BOM_PYTHON: Python 3 tolerates a UTF-8 BOM but tools that read the first line as text do not')
                                    }
                                    'gbk' {
                                        if ($SourceCoding) {
                                            # Legal Python, and still not what
                                            # this project stores.
                                            $verdict = 'WARN'
                                            [void]$reasons.Add(('PY_SOURCE_CODING_DECLARED: line {0} declares {1}, and Python 3 decodes the file with it. The file runs; it is still not UTF-8, so editors, git and every other tool read it as mojibake' -f $SourceCodingLine, $SourceCoding))
                                        }
                                        else {
                                            $verdict = 'FAIL'
                                            [void]$reasons.Add('CP936_PYTHON: Python 3 decodes source as UTF-8 by default, so this file raises SyntaxError. Add a PEP 263 coding declaration on line 1 or 2, or re-save as UTF-8')
                                        }
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
                                        if ($SourceCoding) {
                                            # GB18030 four byte sequences land here:
                                            # valid for the declaration, undetectable
                                            # by the CP936 probe. Latin-1 with a
                                            # non-ASCII body lands here too.
                                            $verdict = 'WARN'
                                            [void]$reasons.Add(('PY_SOURCE_CODING_DECLARED: line {0} declares {1}, and Python 3 decodes the file with it. The file runs; it is still not UTF-8, so editors, git and every other tool read it as mojibake' -f $SourceCodingLine, $SourceCoding))
                                        }
                                        else {
                                            $verdict = 'WARN'
                                            [void]$reasons.Add('UNKNOWN_ENCODING: could not be determined')
                                        }
                                    }
                                }
                            }
                        }
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

        $measured = Get-EncodingSnapshot -Bytes $bytes -EffectiveProfile $resolvedProfile
        $judgement = Get-EncodingVerdict -Encoding $measured.Encoding -EffectiveProfile $resolvedProfile `
            -NonAscii $measured.NonAscii -PayloadProblem $measured.PayloadProblem `
            -SourceCoding $measured.SourceCoding -SourceCodingName $measured.SourceCodingName `
            -SourceCodingLine $measured.SourceCodingLine -SourceCodingProblem $measured.SourceCodingProblem `
            -SourceCodingKind $measured.SourceCodingKind -SourceCodingSupport $measured.SourceCodingSupport `
            -SourceCodingOpen $measured.SourceCodingOpen -SourceCodingRepertoire $measured.SourceCodingRepertoire

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
            SourceCoding        = $measured.SourceCoding
            SourceCodingName    = $measured.SourceCodingName
            SourceCodingLine    = $measured.SourceCodingLine
            SourceCodingProblem = $measured.SourceCodingProblem
            SourceCodingKind    = $measured.SourceCodingKind
            SourceCodingSupport = $measured.SourceCodingSupport
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
            Version    = '1.0.3'
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
            if ($f.SourceCoding) {
                Write-Output ('SOURCE_CODING=' + $f.SourceCoding)
                Write-Output ('SOURCE_CODING_LINE=' + $f.SourceCodingLine)
                if ($f.SourceCodingName) { Write-Output ('SOURCE_CODING_NAME=' + $f.SourceCodingName) }
                if ($f.SourceCodingSupport) { Write-Output ('SOURCE_CODING_SUPPORT=' + $f.SourceCodingSupport) }
            }
            if ($f.SourceCodingProblem) {
                Write-Output ('SOURCE_CODING_PROBLEM=' + $f.SourceCodingProblem)
                if ($f.SourceCodingKind) { Write-Output ('SOURCE_CODING_KIND=' + $f.SourceCodingKind) }
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
