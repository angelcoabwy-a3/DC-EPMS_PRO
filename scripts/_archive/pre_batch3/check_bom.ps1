$bytes = [System.IO.File]::ReadAllBytes("C:\dev\DC-EPMS_PRO\frontend\index.html")
Write-Host "First 3 bytes: $($bytes[0].ToString('X2')) $($bytes[1].ToString('X2')) $($bytes[2].ToString('X2'))"
if ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
    Write-Host "BOM PRESENT" -ForegroundColor Green
} else {
    Write-Host "BOM MISSING" -ForegroundColor Red
}
