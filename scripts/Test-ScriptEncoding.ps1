param([Parameter(Mandatory = $true)][string]$Path)
# Keep this file pure ASCII. Reports encoding facts without printing any Chinese.
$b = [System.IO.File]::ReadAllBytes($Path)
$bom = 'NO-BOM'
if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { $bom = 'UTF8-BOM' }
elseif ($b.Length -ge 2 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE) { $bom = 'UTF16LE-BOM' }
elseif ($b.Length -ge 2 -and $b[0] -eq 0xFE -and $b[1] -eq 0xFF) { $bom = 'UTF16BE-BOM' }
$nonAscii = 0
foreach ($x in $b) { if ($x -gt 0x7F) { $nonAscii++ } }
$strict = New-Object System.Text.UTF8Encoding($false, $true)
try { [void]$strict.GetString($b); $valid = 'VALID-UTF8' } catch { $valid = 'NOT-UTF8' }
$ext = [System.IO.Path]::GetExtension($Path).ToLowerInvariant()
$verdict = 'OK'
$reasons = @()
if ($bom -eq 'UTF16LE-BOM' -or $bom -eq 'UTF16BE-BOM') {
    $verdict = 'FAIL'; $reasons += 'UTF-16 breaks Python/Node/Bash readers'
}
if ($ext -eq '.ps1' -and $bom -eq 'NO-BOM' -and $nonAscii -gt 0 -and $valid -eq 'VALID-UTF8') {
    $verdict = 'FAIL'; $reasons += 'BOM-less .ps1 with non-ASCII: PS5.1 parses it as GBK'
}
if (($ext -eq '.bat' -or $ext -eq '.cmd') -and $bom -eq 'UTF8-BOM') {
    $verdict = 'FAIL'; $reasons += 'BOM breaks the first cmd.exe command'
}
if (($ext -eq '.bat' -or $ext -eq '.cmd') -and $bom -eq 'NO-BOM' -and $nonAscii -gt 0 -and $valid -eq 'VALID-UTF8') {
    if ($verdict -eq 'OK') { $verdict = 'WARN' }
    $reasons += 'UTF-8 .bat: cmd.exe parses bytes as CP936; save as GBK or add chcp 65001'
}
Write-Output ("FILE={0} BOM={1} NON_ASCII_BYTES={2} STRICT={3} VERDICT={4}" -f $Path, $bom, $nonAscii, $valid, $verdict)
foreach ($r in $reasons) { Write-Output ("REASON=" + $r) }
