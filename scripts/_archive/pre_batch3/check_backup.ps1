$bak = "C:\dev\DC-EPMS_PRO\frontend\index.html.bak_pre_s1b_e4"
if (-not (Test-Path $bak)) { Write-Host "BACKUP MISSING" -ForegroundColor Red; exit 1 }
$bytes = [System.IO.File]::ReadAllBytes($bak)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$idx = $text.IndexOf("class=`"icon`">")
if ($idx -lt 0) { Write-Host "marker not found"; exit 1 }
# Show 10 bytes after class="icon">
$start = $idx + 12  # length of class="icon">
$snippet = $bytes[$start..($start+10)]
Write-Host "First icon bytes (hex): $($snippet | ForEach-Object { $_.ToString('X2') })"
# Decode as UTF-8
Write-Host "As UTF-8 char: '$([System.Text.Encoding]::UTF8.GetString($snippet))'"
