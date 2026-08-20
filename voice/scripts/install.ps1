# نصبِ mlqvoice — دانلود، وارسیِ اثرِ انگشت، و باز کردن بدونِ اخطارِ ویندوز.
#
# چرا این فایل وجود دارد
# ----------------------
# ویندوز روی هر فایلی که از اینترنت می‌آید یک نشانه می‌گذارد («Mark of the Web»،
# همان `Zone.Identifier`) و SmartScreen فقط روی همان نشانه اخطار می‌دهد. امضای
# دیجیتال این را حل نمی‌کند: طبقِ مستنداتِ خودِ مایکروسافت، فایلِ امضاشده‌ی تازه
# هم تا وقتی «اعتبار» جمع نکرده همان اخطار را می‌گیرد، و اعتبار از تعدادِ زیادِ
# دانلود ساخته می‌شود — چیزی که برنامه‌ای با یک کاربر هیچ‌وقت به دست نمی‌آورد.
#
# پس راهِ درست این نیست که اخطار را دور بزنیم، این است که **جای کلیک کردنِ
# کورکورانه روی «Run anyway»، فایل را واقعاً وارسی کنیم**: این اسکریپت اثرِ
# انگشتِ SHA-256 را با مقداری که در همین فایل نوشته شده مقابله می‌کند و فقط
# اگر خواند، نشانه را برمی‌دارد. یعنی به‌جای «مطمئنی؟ آره»، یک وارسیِ واقعی.
#
# اجرا:
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = 'Stop'

$Url    = 'https://github.com/mhmdpwrpdram801-cpu/modlandqeshm/releases/download/voice-latest/mlqvoice.zip'
$Sha    = '__SHA256__'   # گردش‌کار موقعِ انتشار جایش می‌گذارد
$Target = Join-Path $env:LOCALAPPDATA 'mlqvoice'

Write-Host ''
Write-Host '  mlqvoice — نصب' -ForegroundColor Cyan
Write-Host ''

$zip = Join-Path ([System.IO.Path]::GetTempPath()) 'mlqvoice.zip'

Write-Host '  [1/5] دانلود…'
# ProgressPreference را خاموش می‌کنیم چون نوارِ پیشرفتِ Invoke-WebRequest روی
# فایلِ ۵۰ مگابایتی خودش چند برابر کندش می‌کند (باگِ شناخته‌شده‌ی PowerShell 5).
$old = $ProgressPreference
$ProgressPreference = 'SilentlyContinue'
try {
  Invoke-WebRequest -Uri $Url -OutFile $zip -UseBasicParsing
} finally {
  $ProgressPreference = $old
}

Write-Host '  [2/5] وارسیِ اثرِ انگشت…'
$got = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
if ($Sha -notmatch '^[0-9a-f]{64}$') {
  # بهتر است بایستد تا اینکه وانمود کند وارسی کرده. وارسی‌ای که انجام نشده،
  # بدتر از نبودنش است — چون اعتمادی می‌سازد که پشتش چیزی نیست.
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
  throw "اثرِ انگشتِ مرجع در این اسکریپت درست جاگذاری نشده — نصب متوقف شد."
}
if ($got -ne $Sha) {
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
  throw "اثرِ انگشت نخواند. انتظار: $Sha — دریافت: $got. فایل را نصب نکردم."
}
Write-Host "        خواند: $got" -ForegroundColor Green

Write-Host '  [3/5] برداشتنِ نشانه‌ی «از اینترنت آمده»…'
# قبل از باز کردن، نه بعدش: ویندوز نشانه را به هر فایلی که از دلِ zip بیرون
# می‌آید ارث می‌دهد، پس اگر اول باز کنی باید تک‌تکشان را جدا پاک کنی.
Unblock-File -Path $zip

Write-Host '  [4/5] باز کردن…'
if (Test-Path $Target) { Remove-Item $Target -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $Target -Force
Remove-Item $zip -Force

$exe = Join-Path $Target 'mlqvoice.exe'
if (-not (Test-Path $exe)) { throw "پس از باز کردن، mlqvoice.exe پیدا نشد." }
# کمربندِ دوم: اگر نسخه‌ی ویندوز نشانه را جورِ دیگری ارث داده باشد.
Get-ChildItem $Target -Recurse -File | Unblock-File -ErrorAction SilentlyContinue

Write-Host '  [5/5] ساختنِ میان‌بُر در منوی استارت…'
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\mlqvoice.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($menu)
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = $Target
$lnk.Description = 'گفتار به متنِ فارسی'
$lnk.Save()

Write-Host ''
Write-Host '  نصب شد ✅' -ForegroundColor Green
Write-Host "  مسیر:  $Target"
Write-Host '  اجرا:  از منوی استارت «mlqvoice» را بزن'
Write-Host '  کلید:  Alt+Space'
Write-Host ''
