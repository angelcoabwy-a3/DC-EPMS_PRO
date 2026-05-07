# Add UTF-8 BOM to index.html if missing
# This fixes the mojibake on icon characters in the sidebar nav items.

$path = "C:\dev\DC-EPMS_PRO\frontend\index.html"

if (-not (Test-Path $path)) {
    Write-Host "ERROR: file not found: $path" -ForegroundColor Red
    exit 1
}

$bytes = [System.IO.File]::ReadAllBytes($path)
Write-Host "File size: $($bytes.Length) bytes" -ForegroundColor Cyan

if ($bytes.Length -lt 3) {
    Write-Host "ERROR: file too small to check" -ForegroundColor Red
    exit 1
}

$hasBom = ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)

if ($hasBom) {
    Write-Host "BOM already present. No change." -ForegroundColor Yellow
} else {
    $bom = [byte[]]@(0xEF, 0xBB, 0xBF)
    $newBytes = New-Object byte[] ($bom.Length + $bytes.Length)
    [System.Array]::Copy($bom, 0, $newBytes, 0, $bom.Length)
    [System.Array]::Copy($bytes, 0, $newBytes, $bom.Length, $bytes.Length)
    [System.IO.File]::WriteAllBytes($path, $newBytes)
    Write-Host "BOM added. New file size: $($newBytes.Length) bytes" -ForegroundColor Green
}
