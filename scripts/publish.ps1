# Publish the web pages + latest data to the gh-pages branch (GitHub Pages).
# gh-pages is force-pushed as a single commit each time, so the repo does not grow.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\publish.ps1
$ErrorActionPreference = 'Stop'
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
$root = Split-Path -Parent $PSScriptRoot
$remote = (git -C $root remote get-url origin).Trim()
$name = (git -C $root config user.name)
$email = (git -C $root config user.email)
$tmp = Join-Path $env:TEMP 'cb-pages-publish'
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
New-Item -ItemType Directory -Force (Join-Path $tmp 'data') | Out-Null
Copy-Item (Join-Path $root '*.html') $tmp
foreach ($f in 'cb_quotes.js', 'cb_breakout.js', 'cb_treasury.js') {
    $src = Join-Path $root "data\$f"
    if (Test-Path $src) { Copy-Item $src (Join-Path $tmp 'data') }
}
New-Item -ItemType File (Join-Path $tmp '.nojekyll') | Out-Null
Push-Location $tmp
# git prints progress to stderr; in PowerShell 5.1 that becomes an error record, so rely on exit codes instead
$ErrorActionPreference = 'Continue'
try {
    git init -q -b gh-pages
    git config core.autocrlf false
    git config user.name $name
    git config user.email $email
    git add -A
    git commit -q -m ("data update " + (Get-Date -Format 'yyyy-MM-dd HH:mm'))
    $out = git push -q --force $remote gh-pages 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "git push failed ($LASTEXITCODE): $out" }
    Write-Output ("published " + (Get-Date -Format 'HH:mm:ss'))
} finally {
    Pop-Location
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
