# Build notazizelse.xyz and ship it to the VM.
#
#   .\deploy\deploy.ps1              build, upload, swap the site in
#   .\deploy\deploy.ps1 -FirstTime   the same, then create the tunnel, start everything and install cron
#
# The SSH target (user@host) comes from -Server, $env:NOTAZIZELSE_SSH, or deploy\target.txt (not in git).
# A new project needs no DNS step: *.notazizelse.xyz already points at this site's tunnel.
param(
  [string]$Server,
  [switch]$FirstTime
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Server) { $Server = $env:NOTAZIZELSE_SSH }
$targetFile = Join-Path $PSScriptRoot "target.txt"
if (-not $Server -and (Test-Path $targetFile)) { $Server = (Get-Content $targetFile -TotalCount 1).Trim() }
if (-not $Server) { throw "No server. Pass -Server user@host, set NOTAZIZELSE_SSH, or put user@host in deploy\target.txt" }

Write-Host "==> building" -ForegroundColor Cyan
python build.py --bundle
if ($LASTEXITCODE -ne 0) { throw "build failed" }

Write-Host "==> uploading to $Server" -ForegroundColor Cyan
ssh $Server "mkdir -p ~/site/incoming"
if ($LASTEXITCODE -ne 0) { throw "ssh failed" }
scp "dist\bundle.tgz" "${Server}:site/incoming/bundle.tgz"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }

Write-Host "==> installing" -ForegroundColor Cyan
$remote = 'set -e; cd ~/site/incoming; rm -rf x; mkdir x; tar xzf bundle.tgz -C x; bash x/sitectl install ~/site/incoming/x; rm -rf x bundle.tgz'
if ($FirstTime) { $remote += '; ~/site/sitectl tunnel-setup; ~/site/sitectl start; ~/site/sitectl cron-install' }
$remote += '; ~/site/sitectl status'
ssh $Server $remote
if ($LASTEXITCODE -ne 0) { throw "remote install failed" }
Write-Host "==> done: https://notazizelse.xyz" -ForegroundColor Green
