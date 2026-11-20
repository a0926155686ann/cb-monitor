# Daily CB quote updater (run by Windows Task Scheduler "CB-Quotes-Daily").
# Weekdays: refresh 1-year daily K history, then update quotes every 30s until 13:35.
# Query only - no order functions. Credentials come from user env vars YUANTA_ACCOUNT / YUANTA_PASSWORD.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$logDir = Join-Path $root 'data\logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("{0:yyyyMMdd}.log" -f (Get-Date))
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUNBUFFERED = '1'
$py = 'C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe'
"=== start $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File $log -Append -Encoding utf8
# --publish-every 600: push pages + data to GitHub Pages every 10 min (Pages allows ~10 builds/hour)
& $py (Join-Path $PSScriptRoot 'cb_quotes.py') --loop 30 --until 13:35 --publish-every 600 *>> $log
"=== end $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') exit=$LASTEXITCODE ===" | Out-File $log -Append -Encoding utf8
# keep 30 days of logs
Get-ChildItem $logDir -Filter *.log | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item -Force
