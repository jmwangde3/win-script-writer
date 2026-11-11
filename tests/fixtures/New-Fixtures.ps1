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
# 0xFF is not a valid GBK lead byte and not a valid UTF-8 byte: the stream must
# be reported as UNKNOWN, never as GBK.
Write-Fixture 'invalid-bytes.bin' ([byte[]](0x41, 0xFF, 0x42, 0xFF, 0x43)) 'neither UTF-8 nor CP936'
Write-Fixture 'empty.txt' ([byte[]]@()) 'zero length'

# --- writer inputs -------------------------------------------------------
$contentBody = $zh + $ceshi + ': content source for the writer.' + "`r`n"
Write-Fixture 'content-utf8.txt' (Get-EncodedBytes $utf8NoBom $contentBody) 'strict UTF-8 writer input'
Write-Fixture 'content-utf8-bom.txt' (Get-EncodedBytes $utf8Strict $contentBody -WithBom) 'strict UTF-8 with BOM writer input'
Write-Fixture 'content-emoji.txt' (Get-EncodedBytes $utf8NoBom $emojiBody) 'strict UTF-8 with char outside GBK'
Write-Fixture 'content-gbk.txt' (Get-EncodedBytes $gbk $contentBody) 'CP936 writer input, must be rejected'

Write-Output ("FIXTURE_DIR=" + (Resolve-Path $OutputDirectory).Path)
Write-Output ("FIXTURE_COUNT=" + (Get-ChildItem $OutputDirectory -File).Count)
