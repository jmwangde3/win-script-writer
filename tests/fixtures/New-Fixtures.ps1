#Requires -Version 5.1
<#
.SYNOPSIS
    Regenerates every binary fixture under tests/fixtures/data.

.DESCRIPTION
    Fixtures are generated instead of committed as opaque binaries so that the
    exact bytes are reviewable in source. Run this file after changing any
    fixture definition:

        powershell -NoProfile -File tests/fixtures/New-Fixtures.ps1
        pwsh       -NoProfile -File tests/fixtures/New-Fixtures.ps1

    The output is deterministic: same source, same bytes.

    This file is intentionally ASCII-only. All non-ASCII payloads are built from
    Unicode code points so the generator itself never depends on the code page
    that happens to be active.
#>
[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot 'data'
}

function ConvertFrom-CodePoints {
    param([int[]]$CodePoint)
    -join ($CodePoint | ForEach-Object { [char]$_ })
}

function Write-Fixture {
    param(
        [string]$Name,
        [byte[]]$Bytes,
        [string]$Note
    )
    $path = Join-Path $OutputDirectory $Name
    [System.IO.File]::WriteAllBytes($path, $Bytes)
    Write-Output ("WROTE {0} BYTES={1} {2}" -f $Name, $Bytes.Length, $Note)
}

# Encoding.GetBytes never emits a preamble: concatenate it explicitly so the
# BOM fixtures really start with EF BB BF / FF FE / FE FF.
function Get-EncodedBytes {
    param(
        [System.Text.Encoding]$Encoding,
        [string]$Text,
        [switch]$WithBom
    )
    $body = $Encoding.GetBytes($Text)
    if (-not $WithBom) { return , $body }
    $preamble = $Encoding.GetPreamble()
    $all = New-Object 'byte[]' ($preamble.Length + $body.Length)
    [Array]::Copy($preamble, 0, $all, 0, $preamble.Length)
    [Array]::Copy($body, 0, $all, $preamble.Length, $body.Length)
    return , $all
}

# --- text payloads, built from code points -------------------------------
# U+4E2D U+6587 = "zhongwen", U+6D4B U+8BD5 = "ceshi" (test)
$zh = ConvertFrom-CodePoints @(0x4E2D, 0x6587)
$ceshi = ConvertFrom-CodePoints @(0x6D4B, 0x8BD5)
$banner = '# ' + $zh + ' fixture: ' + $ceshi

$psBody = $banner + "`r`n" + 'Write-Output "' + $zh + '"' + "`r`n"
$psAsciiBody = '# ascii only fixture' + "`r`n" + 'Write-Output "hello"' + "`r`n"
$batBody = '@echo off' + "`r`n" + 'echo ' + $zh + "`r`n"
$pyBody = '# -*- coding: utf-8 -*-' + "`n" + 'BANNER = "' + $zh + '"' + "`n"
$shBody = '#!/usr/bin/env bash' + "`n" + 'echo "' + $zh + '"' + "`n"

# U+1F600 (grinning face) is outside the GBK repertoire on CP936.
$emoji = ConvertFrom-CodePoints @(0xD83D, 0xDE00)
$emojiBody = 'GREETING = "' + $emoji + '"' + "`n" + 'NAME = "' + $zh + '"' + "`n"

# --- encoders ------------------------------------------------------------
# PowerShell 7 does not ship the OEM code pages until the provider is
# registered; Windows PowerShell has them in the box. The generator runs under
# both, so it asks for the provider instead of assuming either.
function Get-WindowsCodePage {
    param([int]$CodePage)

    try {
        return [System.Text.Encoding]::GetEncoding($CodePage)
    }
    catch {
        $providerType = [System.Type]::GetType(
            'System.Text.CodePagesEncodingProvider, System.Text.Encoding.CodePages',
            $false)
        if ($providerType) {
            [System.Text.Encoding]::RegisterProvider($providerType.GetProperty('Instance').GetValue($null, $null))
            return [System.Text.Encoding]::GetEncoding($CodePage)
        }
    }
    throw ('code page {0} is not available in this host' -f $CodePage)
}

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$utf8Strict = New-Object System.Text.UTF8Encoding($true)
$gbk = [System.Text.Encoding]::GetEncoding(936)
$utf16LeBom = New-Object System.Text.UnicodeEncoding($false, $true)
$utf16BeBom = New-Object System.Text.UnicodeEncoding($true, $true)
$utf16LeNoBom = New-Object System.Text.UnicodeEncoding($false, $false)

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

# --- PowerShell fixtures -------------------------------------------------
Write-Fixture 'ps51-ascii.ps1' (Get-EncodedBytes $utf8NoBom $psAsciiBody) 'ascii, no BOM'
Write-Fixture 'ps51-utf8bom.ps1' (Get-EncodedBytes $utf8Strict $psBody -WithBom) 'UTF-8 with BOM + CJK'
Write-Fixture 'ps51-utf8nobom-cn.ps1' (Get-EncodedBytes $utf8NoBom $psBody) 'UTF-8 no BOM + CJK'
Write-Fixture 'ps51-gbk-cn.ps1' (Get-EncodedBytes $gbk $psBody) 'CP936 + CJK, no BOM'
Write-Fixture 'ps51-utf16le-bom.ps1' (Get-EncodedBytes $utf16LeBom $psBody -WithBom) 'UTF-16LE with BOM'
Write-Fixture 'ps51-utf16be-bom.ps1' (Get-EncodedBytes $utf16BeBom $psBody -WithBom) 'UTF-16BE with BOM'
Write-Fixture 'utf16le-nobom.ps1' (Get-EncodedBytes $utf16LeNoBom ('Write-Output "hello"' + "`r`n")) 'UTF-16LE without BOM (NUL pattern)'
# The BE counterpart is what proved the earlier verdict wrong: the previous
# "UTF-16BE does not run" measurement had been taken on a BOM-less file, because
# Python's utf-16-be codec does not emit a mark. With a real FE FF it runs.
Write-Fixture 'utf16be-nobom.ps1' (Get-EncodedBytes (New-Object System.Text.UnicodeEncoding($true, $false)) ('Write-Output "hello"' + "`r`n")) 'UTF-16BE without BOM (NUL pattern)'

# --- CMD fixtures --------------------------------------------------------
Write-Fixture 'bat-ascii.bat' (Get-EncodedBytes $gbk ('@echo off' + "`r`n" + 'echo hello' + "`r`n")) 'ascii batch'
Write-Fixture 'bat-gbk-cn.bat' (Get-EncodedBytes $gbk $batBody) 'CP936 batch, correct for CP936 console'
Write-Fixture 'bat-utf8nobom-cn.bat' (Get-EncodedBytes $utf8NoBom $batBody) 'UTF-8 no BOM batch, needs chcp 65001'
Write-Fixture 'bat-utf8bom-cn.bat' (Get-EncodedBytes $utf8Strict $batBody -WithBom) 'UTF-8 BOM batch, breaks first command'

# --- Python / Bash fixtures ---------------------------------------------
Write-Fixture 'py-utf8nobom.py' (Get-EncodedBytes $utf8NoBom $pyBody) 'UTF-8 no BOM python'
Write-Fixture 'py-gbk.py' (Get-EncodedBytes $gbk $pyBody) 'CP936 python, misread by Python 3'
Write-Fixture 'sh-utf8nobom.sh' (Get-EncodedBytes $utf8NoBom $shBody) 'UTF-8 no BOM bash'

# --- data fixtures -------------------------------------------------------
$jsonBody = '{' + "`n" + '  "message": "' + $zh + '"' + "`n" + '}' + "`n"
Write-Fixture 'data-utf8nobom.json' (Get-EncodedBytes $utf8NoBom $jsonBody) 'UTF-8 no BOM json'
Write-Fixture 'data-gbk.txt' (Get-EncodedBytes $gbk ($zh + $ceshi + "`r`n")) 'CP936 plain text'

# --- edge cases ----------------------------------------------------------
# 0x81 is a CP936 lead byte and 0x20 is not a valid trail byte, so the stream
# decodes to a replacement character and cannot round trip. It is also invalid
# UTF-8. 0xFF would have been a bad choice: Windows maps it to U+F8F5.
Write-Fixture 'invalid-bytes.bin' ([byte[]](0x41, 0x81, 0x20, 0x42)) 'neither UTF-8 nor CP936'
Write-Fixture 'empty.txt' ([byte[]]@()) 'zero length'

# --- BOM payload validation (v1.0.1) -------------------------------------
# A byte order mark is a claim, not a proof. Every fixture below starts with a
# valid BOM, and the detector used to answer "utf8-bom / OK / exit 0" for all of
# them without ever decoding the payload.
$utf8Bom = [byte[]](0xEF, 0xBB, 0xBF)
Write-Fixture 'utf8bom-empty.ps1' ($utf8Bom) 'BOM and nothing else: valid, empty payload'
Write-Fixture 'utf8bom-ascii.ps1' ($utf8Bom + [byte[]](0x41)) 'BOM + "A": valid UTF-8'
# 0xFF can never appear in UTF-8.
Write-Fixture 'utf8bom-invalid-ff.bin' ($utf8Bom + [byte[]](0xFF)) 'BOM + FF: invalid UTF-8'
# C3 starts a two byte sequence, 0x28 is not a continuation byte.
Write-Fixture 'utf8bom-invalid-continuation.bin' ($utf8Bom + [byte[]](0xC3, 0x28)) 'BOM + C3 28: invalid continuation'
# E4 B8 is the first two thirds of a three byte sequence.
Write-Fixture 'utf8bom-incomplete-sequence.bin' ($utf8Bom + [byte[]](0xE4, 0xB8)) 'BOM + E4 B8: truncated sequence'

# UTF-16 payload damage. 0xD800 is a high surrogate with no low surrogate after
# it, which is not text; the odd length fixture drops the final byte of a code
# unit. Windows PowerShell 5.1 runs the readable prefix of both and exits 0.
$utf16Body = $utf16LeBom.GetBytes('Write-Output "hello"' + "`r`n")
$utf16Truncated = New-Object 'byte[]' ($utf16Body.Length - 1)
[Array]::Copy($utf16Body, 0, $utf16Truncated, 0, $utf16Truncated.Length)
Write-Fixture 'utf16le-bom-truncated.ps1' ([byte[]](0xFF, 0xFE) + $utf16Truncated) 'UTF-16LE BOM + odd byte count'
Write-Fixture 'utf16le-bom-lone-surrogate.ps1' ([byte[]](0xFF, 0xFE) + $utf16Body + [byte[]](0x00, 0xD8)) 'UTF-16LE BOM + unpaired high surrogate'

# --- non-ASCII outside CJK (v1.0.1) --------------------------------------
# U+00E9 (e acute) is a single two byte UTF-8 sequence. It exists so the ascii
# expectation has a case that is neither CJK nor a BOM.
#
# The line ends with a bare LF although every other text fixture uses CRLF. This
# directory is marked -text, so the CR would reach the blob and `git diff --check`
# reads it as trailing whitespace (core.whitespace has no cr-at-eol here). The
# fixture exists to carry the e acute, not to pin a line ending; an LF keeps the
# whitespace check quiet without weakening the case.
$eacute = ConvertFrom-CodePoints @(0x00E9)
Write-Fixture 'utf8nobom-latin1.txt' (Get-EncodedBytes $utf8NoBom ('caf' + $eacute + "`n")) 'UTF-8 no BOM, Latin-1 range character'

# --- UTF-32 with a BOM (v1.0.2) ------------------------------------------
# FF FE 00 00 begins with the UTF-16LE mark, so a detector that matches the two
# byte marks first labels a UTF-32LE file as UTF-16LE and then reports a verdict
# about a file that does not exist. The four byte mark has to win.
$utf32Le = New-Object System.Text.UTF32Encoding($false, $true)
$utf32Be = New-Object System.Text.UTF32Encoding($true, $true)
$plainBody = 'Write-Output "hello"' + "`r`n"
Write-Fixture 'utf32le-bom.ps1' (Get-EncodedBytes $utf32Le $plainBody -WithBom) 'UTF-32LE with BOM'
Write-Fixture 'utf32be-bom.ps1' (Get-EncodedBytes $utf32Be $plainBody -WithBom) 'UTF-32BE with BOM'

# --- Python source encoding declarations (v1.0.2) ------------------------
# PEP 263 lets a comment on line 1 or 2 name the source encoding. A GBK file
# that says so is legal Python and runs; a GBK file that stays silent raises
# SyntaxError. The detector used to fail both.
$pyCodingDash = '# -*- coding: gbk -*-' + "`n"
$pyCodingEquals = '# coding=cp936' + "`n"
$pyCodingBody = 'MARKER = "' + $zh + '"' + "`n" + 'print("PYCODING_GBK_OK " + MARKER)' + "`n"
Write-Fixture 'py-coding-gbk.py' (Get-EncodedBytes $gbk ($pyCodingDash + $pyCodingBody)) 'CP936 python with a PEP 263 declaration'
Write-Fixture 'py-coding-equals.py' (Get-EncodedBytes $gbk ($pyCodingEquals + $pyCodingBody)) 'CP936 python, coding=cp936 form'
Write-Fixture 'py-nocoding-gbk.py' (Get-EncodedBytes $gbk ($pyCodingBody)) 'CP936 python without a declaration'
# A UTF-8 BOM and a non-UTF-8 declaration cannot both be true; Python refuses.
Write-Fixture 'py-coding-conflict-bom.py' (Get-EncodedBytes $utf8Strict ($pyCodingDash + 'print("conflict")' + "`n") -WithBom) 'UTF-8 BOM plus coding: gbk'
# "utf-9" is not a codec. Python raises SyntaxError even for an ASCII body.
Write-Fixture 'py-coding-unknown.py' (Get-EncodedBytes $utf8NoBom ('# coding: utf-9' + "`n" + 'print("unknown")' + "`n")) 'unknown source encoding'

# --- Python source codec aliases (v1.0.3) --------------------------------
# GBK, GB2312, HZ-GB-2312 and GB18030 are four different byte layouts, not
# four spellings of code page 936. GB2312 is a subset of GBK, HZ is a 7 bit
# escape encoding of GB2312, and GB18030 adds four byte sequences for the code
# points neither of the others can carry. A detector that validates every
# declaration with CP936 accepts files that Python rejects, and rejects files
# that Python runs.
$gb18030 = Get-WindowsCodePage 54936

function ConvertTo-HzText {
    <#
        HZ-GB-2312 carries GB2312 in seven bit form: the double byte codes are
        shifted down by 0x80 and wrapped in ~{ ... ~}. The shift can produce
        '~' (0x7E), which HZ reserves for its escape sequences, so such a
        payload cannot be represented and is a generator error rather than a
        silently corrupt fixture.
    #>
    param([byte[]]$Gb2312Bytes)

    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('~{')
    for ($i = 0; $i + 1 -lt $Gb2312Bytes.Length; $i += 2) {
        $high = $Gb2312Bytes[$i] - 0x80
        $low = $Gb2312Bytes[$i + 1] - 0x80
        if ($high -eq 0x7E -or $low -eq 0x7E) {
            throw 'this payload contains a byte that HZ has to escape; pick another character'
        }
        [void]$sb.Append([char]$high)
        [void]$sb.Append([char]$low)
    }
    [void]$sb.Append('~}')
    return $sb.ToString()
}

$pyGb2312Body = 'MARKER = "' + $zh + '"' + "`n" + 'print("PYCODING_GB2312_OK " + MARKER)' + "`n"
Write-Fixture 'py-coding-gb2312.py' (Get-EncodedBytes $gbk ('# -*- coding: gb2312 -*-' + "`n" + $pyGb2312Body)) 'GB2312 bytes declared as gb2312'
Write-Fixture 'py-coding-euc-cn.py' (Get-EncodedBytes $gbk ('# -*- coding: euc-cn -*-' + "`n" + $pyGb2312Body)) 'GB2312 bytes declared as euc-cn'

# HZ output is pure ASCII by construction, so the file contains no byte above
# 0x7F at all. Anything that only looks for high bytes calls it ASCII.
$hzMarker = ConvertTo-HzText -Gb2312Bytes $gbk.GetBytes($zh)
$hzBody = '# -*- coding: hz -*-' + "`n" + 'MARKER = "' + $hzMarker + '"' + "`n" + 'print("PYCODING_HZ_OK " + MARKER)' + "`n"
Write-Fixture 'py-coding-hz.py' (Get-EncodedBytes $utf8NoBom $hzBody) 'HZ-GB-2312 source, seven bit only'

# U+10000 has no GB2312 or GBK form: GB18030 writes it as 90 30 81 30.
$bmpOutsideGbk = [char]::ConvertFromUtf32(0x10000)
$gb18030Body = '# -*- coding: gb18030 -*-' + "`n" + 'MARKER = "' + $zh + $bmpOutsideGbk + '"' + "`n" + 'print("PYCODING_GB18030_OK " + MARKER)' + "`n"
Write-Fixture 'py-coding-gb18030.py' (Get-EncodedBytes $gb18030 $gb18030Body) 'GB18030 with a four byte sequence'

# U+4E02 exists in GBK (81 40) and nowhere in GB2312. Declaring gb2312 over
# these bytes is a lie that CP936 validation cannot see.
$gbkOnly = [char]::ConvertFromUtf32(0x4E02)
$gbkOnlyBody = '# -*- coding: gb2312 -*-' + "`n" + 'MARKER = "' + $gbkOnly + '"' + "`n" + 'print("PYCODING_SHOULD_NOT_RUN")' + "`n"
Write-Fixture 'py-coding-gbk-as-gb2312.py' (Get-EncodedBytes $gbk $gbkOnlyBody) 'GBK only bytes declared as gb2312'

# codecs.lookup('windows-936') raises LookupError in CPython: the real aliases
# are cp936, ms936 and 936. A detector that accepts this name passes a file
# that Python refuses to even compile.
Write-Fixture 'py-coding-windows936.py' (Get-EncodedBytes $gbk ('# -*- coding: windows-936 -*-' + "`n" + $pyGb2312Body)) 'a name CPython does not resolve'

# Same trap, other family: 54936 is the Windows code page, not a Python codec
# name, and GB18030's aliases are gb18030 and gb18030-2000.
Write-Fixture 'py-coding-cp54936.py' (Get-EncodedBytes $gbk ('# -*- coding: cp54936 -*-' + "`n" + $pyGb2312Body)) 'a Windows code page used as a codec name'

# A ~{ that never closes leaves the decoder inside GB mode at end of file, and
# the newline that follows is a single byte with no partner. CPython tolerates
# an unterminated run but not a dangling byte, which is the distinction this
# fixture pins: it must fail.
Write-Fixture 'py-coding-hz-truncated.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: hz -*-' + "`n" + 'MARKER = "~{VPND' + "`n")) 'HZ with a dangling byte at end of file'

# --- HZ state machine (v1.0.3) -------------------------------------------
# CPython's hz codec disagrees with a naive reading of RFC 1843 in both
# directions, and every case below was measured on the interpreter:
#
#   ~\n  in ASCII mode   continuation, both agree
#   ~\n  in GB mode      error: 0x0A is not a pair byte
#   ~~   in ASCII mode   literal tilde, both agree
#   ~~   in GB mode      error: 0x7E shifts to a lead byte outside A1-F7
#   ~}   at a pair edge  closes GB mode
#   ~}   in ASCII mode   error
#   0x7E as a pair trail data, not an escape: 56 7E is D6 FE, a real cell
#   EOF  inside GB mode  tolerated when no byte is left dangling
#
# A state machine that tests for the tilde before it looks at the mode gets
# three of these wrong: it accepts ~~ and ~\n inside GB mode, and it refuses a
# legitimate 0x7E trail byte.
Write-Fixture 'py-coding-hz-tilde-in-gb.py' (Get-EncodedBytes $utf8NoBom (
        '# -*- coding: hz -*-' + "`n" +
        'MARKER = "~{V~~}"' + "`n" +
        'print("PYCODING_HZ_TILDE_OK " + MARKER)' + "`n")) 'HZ pair whose trail byte is 0x7E'

Write-Fixture 'py-coding-hz-escape-in-gb.py' (Get-EncodedBytes $utf8NoBom (
        '# -*- coding: hz -*-' + "`n" +
        'MARKER = "~{~~}"' + "`n" +
        'print("PYCODING_HZ_ESCAPE_SHOULD_NOT_RUN")' + "`n")) 'HZ ~~ inside GB mode'

Write-Fixture 'py-coding-hz-close-in-ascii.py' (Get-EncodedBytes $utf8NoBom (
        '# -*- coding: hz -*-' + "`n" +
        'MARKER = "~}"' + "`n" +
        'print("PYCODING_HZ_CLOSE_SHOULD_NOT_RUN")' + "`n")) 'HZ ~} outside GB mode'

Write-Fixture 'py-coding-hz-continuation.py' (Get-EncodedBytes $utf8NoBom (
        '# -*- coding: hz -*-' + "`n" +
        'MARKER = "ab~' + "`n" + 'cd"' + "`n" +
        'print("PYCODING_HZ_CONTINUATION_OK " + MARKER)' + "`n")) 'HZ line continuation in ASCII mode'

Write-Fixture 'py-coding-hz-open.py' (Get-EncodedBytes $utf8NoBom (
        '# -*- coding: hz -*-' + "`n" +
        'print("PYCODING_HZ_OPEN_OK")' + "`n" +
        '# ~{VPND')) 'HZ that ends inside GB mode with complete pairs'

# --- encoding overlap (v1.0.3) -------------------------------------------
# C3 A9 is U+8305 in GB2312, GBK and GB18030, and it is also a valid two byte UTF-8
# sequence (U+00E9). The detector labels such a file utf8-nobom and used to
# call any declaration that is not UTF-8 a conflict -- but Python decodes the
# file with the declared codec and runs it. Overlap is not a conflict.
$mao = ConvertFrom-CodePoints @(0x8305)
$maoBody = 'MARKER = "' + $mao + '"' + "`n"

Write-Fixture 'py-coding-gb2312-overlap.py' (Get-EncodedBytes $gbk ('# -*- coding: gb2312 -*-' + "`n" + $maoBody + 'print("PYCODING_GB2312_OVERLAP_OK " + MARKER)' + "`n")) 'GB2312 bytes that also decode as UTF-8'
Write-Fixture 'py-coding-gbk-overlap.py' (Get-EncodedBytes $gbk ('# -*- coding: gbk -*-' + "`n" + $maoBody + 'print("PYCODING_GBK_OVERLAP_OK " + MARKER)' + "`n")) 'GBK bytes that also decode as UTF-8'
Write-Fixture 'py-coding-gb18030-overlap.py' (Get-EncodedBytes $gb18030 ('# -*- coding: gb18030 -*-' + "`n" + $maoBody + 'print("PYCODING_GB18030_OVERLAP_OK " + MARKER)' + "`n")) 'GB18030 bytes that also decode as UTF-8'

# The other direction: the declaration cannot decode these bytes at all. CP936
# stops at byte 1 of the UTF-8 sequence, so CPython raises SyntaxError and so
# must the detector. This is the case the overlap rule must not swallow.
Write-Fixture 'py-coding-utf8-as-gbk.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: gbk -*-' + "`n" + 'MARKER = "' + $zh + '"' + "`n" + 'print("PYCODING_UTF8_AS_GBK_SHOULD_NOT_RUN")' + "`n")) 'UTF-8 bytes declared as gbk: undecodable'
Write-Fixture 'py-coding-utf8-as-gb2312.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: gb2312 -*-' + "`n" + 'MARKER = "' + $zh + '"' + "`n" + 'print("PYCODING_UTF8_AS_GB2312_SHOULD_NOT_RUN")' + "`n")) 'UTF-8 bytes declared as gb2312: undecodable'

# --- Latin-1 (v1.0.3) ----------------------------------------------------
# ISO-8859-1 has no invalid byte sequence at all: every one of the 256 values
# decodes. A detector that decides "is this Latin-1" by looking for a code page
# round trip refuses the file, and a repertoire that only lists ascii calls a
# legal non-ASCII file a conflict.
$latin1 = [System.Text.Encoding]::GetEncoding(28591)
$eacuteBody = 'MARKER = "' + $eacute + '"' + "`n"
Write-Fixture 'py-coding-latin1.py' (Get-EncodedBytes $latin1 ('# -*- coding: latin-1 -*-' + "`n" + $eacuteBody + 'print("PYCODING_LATIN1_OK " + MARKER)' + "`n")) 'Latin-1 with a non-ASCII character'
Write-Fixture 'py-coding-latin1-ascii.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: latin-1 -*-' + "`n" + 'print("PYCODING_LATIN1_ASCII_OK")' + "`n")) 'ASCII body declared as Latin-1'
Write-Fixture 'py-coding-latin1-utf8.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: latin-1 -*-' + "`n" + $eacuteBody + 'print("PYCODING_LATIN1_UTF8_OK " + MARKER)' + "`n")) 'UTF-8 bytes declared as Latin-1: runs, as mojibake'
# A BOM and any declaration other than utf-8 is a SyntaxError in CPython, and
# Latin-1 is no exception.
Write-Fixture 'py-coding-latin1-bom.py' (Get-EncodedBytes $utf8Strict ('# -*- coding: latin-1 -*-' + "`n" + 'print("PYCODING_LATIN1_BOM_SHOULD_NOT_RUN")' + "`n") -WithBom) 'UTF-8 BOM plus coding: latin-1'

# --- Python codec names the detector cannot verify (v1.0.3) --------------
# These resolve in CPython and Python runs the file, but this tool has no byte
# level verifier for them. "Cannot verify" and "Python does not know the name"
# are different answers and used to share one.
Write-Fixture 'py-coding-cp1252.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: cp1252 -*-' + "`n" + 'print("PYCODING_CP1252_OK")' + "`n")) 'a codec Python knows and this tool does not verify'
Write-Fixture 'py-coding-shift-jis.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: shift_jis -*-' + "`n" + 'print("PYCODING_SHIFTJIS_OK")' + "`n")) 'a codec Python knows and this tool does not verify'
Write-Fixture 'py-coding-big5.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: big5 -*-' + "`n" + 'print("PYCODING_BIG5_OK")' + "`n")) 'a codec Python knows and this tool does not verify'

# Names that look like codecs and are not. Each one was checked with
# codecs.lookup() on the interpreter the tests run on.
Write-Fixture 'py-coding-54936.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: 54936 -*-' + "`n" + 'print("PYCODING_54936_SHOULD_NOT_RUN")' + "`n")) 'bare code page number as a codec name'
Write-Fixture 'py-coding-hzgb2312.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: hzgb2312 -*-' + "`n" + 'print("PYCODING_HZGB2312_SHOULD_NOT_RUN")' + "`n")) 'HZ with the separator dropped'
Write-Fixture 'py-coding-cn-gb.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: cn-gb -*-' + "`n" + 'print("PYCODING_CNGB_SHOULD_NOT_RUN")' + "`n")) 'a national body spelling CPython does not list'

# utf-8-sig is UTF-8 with an optional BOM; the bytes still have to be UTF-8.
Write-Fixture 'py-coding-utf8-sig.py' (Get-EncodedBytes $utf8NoBom ('# -*- coding: utf-8-sig -*-' + "`n" + 'MARKER = "' + $zh + '"' + "`n" + 'print("PYCODING_UTF8SIG_OK " + MARKER)' + "`n")) 'utf-8-sig declaration, no BOM'

# CPython normalises the name before comparing it with "utf-8" for the BOM
# rule, and "utf8" is not "utf-8": the spelling alone decides whether the file
# compiles.
Write-Fixture 'py-coding-utf8-spelling-bom.py' (Get-EncodedBytes $utf8Strict ('# -*- coding: utf8 -*-' + "`n" + 'print("PYCODING_UTF8_SPELLING_SHOULD_NOT_RUN")' + "`n") -WithBom) 'BOM plus the utf8 spelling of utf-8'


# --- writer inputs -------------------------------------------------------
$contentBody = $zh + $ceshi + ': content source for the writer.' + "`r`n"
Write-Fixture 'content-utf8.txt' (Get-EncodedBytes $utf8NoBom $contentBody) 'strict UTF-8 writer input'
Write-Fixture 'content-utf8-bom.txt' (Get-EncodedBytes $utf8Strict $contentBody -WithBom) 'strict UTF-8 with BOM writer input'
Write-Fixture 'content-emoji.txt' (Get-EncodedBytes $utf8NoBom $emojiBody) 'strict UTF-8 with char outside GBK'
Write-Fixture 'content-gbk.txt' (Get-EncodedBytes $gbk $contentBody) 'CP936 writer input, must be rejected'

Write-Output ("FIXTURE_DIR=" + (Resolve-Path $OutputDirectory).Path)
Write-Output ("FIXTURE_COUNT=" + (Get-ChildItem $OutputDirectory -File).Count)
