#Requires -Version 5.1
<#
.SYNOPSIS
    Builds the distributable zip for a release.

.DESCRIPTION
    Used by .github/workflows/release.yml and runnable by hand, so the packaging
    logic that runs on a tag is the same logic that was tested locally.

    Entries are created one by one instead of via Compress-Archive on purpose.
    Compress-Archive on Windows PowerShell 5.1 writes backslash separators into
    the entry names ("win-script-writer\SKILL.md"), which is not what APPNOTE
    specifies and makes the archive unpack into a single literal filename on
    tools that take the spec literally. Every entry name here is normalised to
    forward slashes.

    The manifest is printed as ENTRY= lines so a caller can assert on the result
    without reopening the archive.

.PARAMETER Tag
    Release tag, for example v1.0.0. Used for the file name only.

.PARAMETER OutputPath
    Full path of the .zip to create. Existing files are overwritten.

.PARAMETER NotesPath
    Optional. When supplied, the CHANGELOG section for this tag is written here,
    so the release body comes from the file instead of a hand-typed summary that
    drifts away from it.

.EXAMPLE
    .\package.ps1 -Tag v1.0.0 -OutputPath (Join-Path $env:TEMP 'win-script-writer-v1.0.0.zip')
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [string]$NotesPath
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$repoRoot = Split-Path -Parent $PSScriptRoot
$topLevelFiles = @('SKILL.md', 'README.md', 'CHANGELOG.md', 'LICENSE')
$topLevelDirs = @('references', 'scripts')

$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('wsw-package-' + [guid]::NewGuid().ToString('N'))
$stagingDir = Join-Path $stagingRoot 'win-script-writer'

try {
    New-Item -ItemType Directory -Path $stagingDir -Force | Out-Null

    foreach ($name in $topLevelFiles) {
        $source = Join-Path $repoRoot $name
        if (-not (Test-Path -LiteralPath $source)) { throw "missing top level file: $name" }
        Copy-Item -LiteralPath $source -Destination $stagingDir
    }
    foreach ($name in $topLevelDirs) {
        $source = Join-Path $repoRoot $name
        if (-not (Test-Path -LiteralPath $source)) { throw "missing directory: $name" }
        Copy-Item -LiteralPath $source -Destination $stagingDir -Recurse
    }

    $files = Get-ChildItem -LiteralPath $stagingDir -Recurse -File | Sort-Object FullName
    if ($files.Count -eq 0) { throw 'staging directory is empty' }

    $resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
    $outputDir = Split-Path -Parent $resolvedOutput
    if (-not (Test-Path -LiteralPath $outputDir)) {
        New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    }
    if (Test-Path -LiteralPath $resolvedOutput) {
        Remove-Item -LiteralPath $resolvedOutput -Force
    }

    $prefixLength = $stagingRoot.TrimEnd('\', '/').Length + 1
    $archive = [System.IO.Compression.ZipFile]::Open($resolvedOutput, 'Create')
    try {
        foreach ($file in $files) {
            $entryName = $file.FullName.Substring($prefixLength).Replace('\', '/')
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive, $file.FullName, $entryName, [System.IO.Compression.CompressionLevel]::Optimal)
        }
    }
    finally {
        $archive.Dispose()
    }

    Write-Output ('PACKAGE=' + $resolvedOutput)
    Write-Output ('PACKAGE_BYTES=' + (Get-Item -LiteralPath $resolvedOutput).Length)
    Write-Output ('ENTRY_COUNT=' + $files.Count)

    # Reopen and report what actually landed in the file, not what was intended.
    $check = [System.IO.Compression.ZipFile]::OpenRead($resolvedOutput)
    try {
        $names = @($check.Entries | ForEach-Object { $_.FullName })
    }
    finally {
        $check.Dispose()
    }
    foreach ($name in $names) { Write-Output ('ENTRY=' + $name) }

    $backslashed = @($names | Where-Object { $_.Contains('\') })
    if ($backslashed.Count -gt 0) {
        Write-Output ('ERROR=ENTRY_USES_BACKSLASH count=' + $backslashed.Count)
        exit 1
    }
    Write-Output 'ENTRY_SEPARATOR=FORWARD_SLASH_OK'

    if ($NotesPath) {
        # Release notes come from the changelog, not from a separate document
        # that nobody updates. The section runs until the next "## [" heading.
        $changelogPath = Join-Path $repoRoot 'CHANGELOG.md'
        # -Encoding UTF8 is not optional here. Without it Windows PowerShell 5.1
        # decodes this UTF-8, BOM-less file as CP936 and the release notes come
        # out as mojibake -- the exact first broken link this repository exists
        # to document, caught in this repository's own build script.
        $changelog = Get-Content -LiteralPath $changelogPath -Raw -Encoding UTF8
        $version = $Tag.TrimStart('v')
        $pattern = '(?ms)^## \[' + [regex]::Escape($version) + '\].*?(?=^## \[|\z)'
        $section = [regex]::Match($changelog, $pattern)
        if ($section.Success) {
            $body = $section.Value.TrimEnd() + "`n"
            Write-Output 'NOTES_SOURCE=changelog'
        }
        else {
            $body = ('Release ' + $Tag + "`n")
            Write-Output 'NOTES_SOURCE=fallback'
        }
        $resolvedNotes = [System.IO.Path]::GetFullPath($NotesPath)
        [System.IO.File]::WriteAllText($resolvedNotes, $body, (New-Object System.Text.UTF8Encoding($false)))
        Write-Output ('NOTES=' + $resolvedNotes)
        Write-Output ('NOTES_BYTES=' + ([System.IO.File]::ReadAllBytes($resolvedNotes)).Length)
    }
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
