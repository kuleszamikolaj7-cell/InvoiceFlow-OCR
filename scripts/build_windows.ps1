# InvoiceFlow OCR v0.6 - local Windows build (not run on Linux CI).
# Run from any directory: powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $PSScriptRoot
Set-Location $project
$py = Join-Path $project ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "Brak .venv. Utworz: py -3.12 -m venv .venv"
}
& $py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Nie mozna zainstalowac zaleznosci." }
& $py -m pip install "pyinstaller>=6,<7"
if ($LASTEXITCODE -ne 0) { throw "Instalacja PyInstaller nie powiodla sie." }
& $py -m PyInstaller --noconfirm --clean --onedir --windowed --contents-directory "." --name "InvoiceFlowOCR" --collect-all "customtkinter" --add-data "templates;templates" --add-data "examples;examples" "gui.py"
if ($LASTEXITCODE -ne 0) { throw "Budowanie EXE nie powiodlo sie." }
Write-Host "Gotowe: $project\dist\InvoiceFlowOCR\InvoiceFlowOCR.exe"
Write-Host "UWAGA: Tesseract i Poppler wymagaja osobnej instalacji. Nie publikuj prywatnego katalogu data/ ani output/."
