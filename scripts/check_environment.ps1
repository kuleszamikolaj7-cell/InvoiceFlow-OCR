# Szybka kontrola narzędzi do OCR na Windows.
Write-Host "=== InvoiceFlow OCR: kontrola narzedzi ==="
foreach ($tool in @("python", "pdfinfo", "pdftoppm", "tesseract")) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if ($found) {
        Write-Host "OK: $tool -> $($found.Source)" -ForegroundColor Green
    } else {
        Write-Host "BRAK w PATH: $tool" -ForegroundColor Yellow
    }
}
$commonTesseract = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (Test-Path $commonTesseract) {
    Write-Host "Znaleziono Tesseract: $commonTesseract" -ForegroundColor Green
}
