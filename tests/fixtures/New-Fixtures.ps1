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

# --- writer inputs -------------------------------------------------------
$contentBody = $zh + $ceshi + ': content source for the writer.' + "`r`n"
Write-Fixture 'content-utf8.txt' (Get-EncodedBytes $utf8NoBom $contentBody) 'strict UTF-8 writer input'
Write-Fixture 'content-utf8-bom.txt' (Get-EncodedBytes $utf8Strict $contentBody -WithBom) 'strict UTF-8 with BOM writer input'
Write-Fixture 'content-emoji.txt' (Get-EncodedBytes $utf8NoBom $emojiBody) 'strict UTF-8 with char outside GBK'
Write-Fixture 'content-gbk.txt' (Get-EncodedBytes $gbk $contentBody) 'CP936 writer input, must be rejected'

Write-Output ("FIXTURE_DIR=" + (Resolve-Path $OutputDirectory).Path)
Write-Output ("FIXTURE_COUNT=" + (Get-ChildItem $OutputDirectory -File).Count)
