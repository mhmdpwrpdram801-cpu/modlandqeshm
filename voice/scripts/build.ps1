# ساختِ mlqvoice.exe — روی خودِ ویندوز اجرا شود.
#
#   powershell -ExecutionPolicy Bypass -File scripts\build.ps1
#
# خروجی: dist\mlqvoice.exe  (تک‌فایل، بدونِ پنجره‌ی کنسول)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    Write-Host "ساختِ محیطِ مجازی…" -ForegroundColor Cyan
    python -m venv .venv
}
$py = ".\.venv\Scripts\python.exe"

Write-Host "نصبِ وابستگی‌ها…" -ForegroundColor Cyan
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -e ".[dev]" --quiet

Write-Host "اجرای تست‌ها…" -ForegroundColor Cyan
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "تست‌ها قرمزند — تا سبز نشده build نکن." }

Write-Host "لینت…" -ForegroundColor Cyan
& $py -m ruff check .
if ($LASTEXITCODE -ne 0) { throw "لینت قرمز است." }

Write-Host "ساختِ exe…" -ForegroundColor Cyan
& $py -m PyInstaller `
    --noconfirm --clean --onefile --windowed `
    --name mlqvoice `
    --add-data "src/mlqvoice/text/data;mlqvoice/text/data" `
    --add-data "src/mlqvoice/web;mlqvoice/web" `
    --add-data "src/mlqvoice/assets;mlqvoice/assets" `
    --collect-all comtypes `
    --hidden-import pycaw `
    --hidden-import pycaw.pycaw `
    --exclude-module tkinter `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.Qt3DCore `
    --exclude-module PySide6.QtMultimedia `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtCharts `
    --paths src `
    scripts/launcher.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller شکست خورد." }

$exe = "dist\mlqvoice.exe"
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ""
Write-Host "آماده شد: $exe  ($size مگابایت)" -ForegroundColor Green
Write-Host "برای اجرای خودکار در استارتاپ، یک میان‌بُر از آن را در پوشه‌ی زیر بگذار:" -ForegroundColor Yellow
Write-Host "  shell:startup" -ForegroundColor Yellow
