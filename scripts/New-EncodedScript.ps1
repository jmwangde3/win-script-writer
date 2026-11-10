param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$ContentFile,
    [ValidateSet('utf8-nobom', 'utf8-bom', 'gbk')][string]$Encoding = 'utf8-nobom'
)
# Keep this file pure ASCII. Chinese content comes from $ContentFile (UTF-8 source),
# never from argv: cmd/PowerShell argv on CP936 is lossy for non-ASCII.
$utf8Strict = New-Object System.Text.UTF8Encoding($false, $true)
$text = [System.IO.File]::ReadAllText($ContentFile, $utf8Strict)
switch ($Encoding) {
    'utf8-nobom' { $enc = New-Object System.Text.UTF8Encoding($false) }
    'utf8-bom'   { $enc = New-Object System.Text.UTF8Encoding($true) }
    'gbk'        { $enc = [System.Text.Encoding]::GetEncoding(936) }
}
$dir = Split-Path -Parent $Path
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
[System.IO.File]::WriteAllText($Path, $text, $enc)
$b = [System.IO.File]::ReadAllBytes($Path)
Write-Output ("WROTE={0} ENC={1} BYTES={2} HEAD={3}" -f $Path, $Encoding, $b.Length, (($b | Select-Object -First 4) -join ' '))
