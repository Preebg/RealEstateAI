# Register the harvester to run every 90 minutes as NT AUTHORITY\SYSTEM.
# Requires Administrator. Object name in Task Scheduler: SYSTEM

$ErrorActionPreference = "Stop"

$CmdPath = Join-Path $PSScriptRoot "run_harvester.cmd"
if (-not (Test-Path -LiteralPath $CmdPath)) {
    throw "run_harvester.cmd not found at $CmdPath"
}

$TaskName = "RealEstateAI_Harvester"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell (Run as administrator)."
}

sc.exe config com.docker.service start= auto | Out-Null
sc.exe start com.docker.service 2>$null | Out-Null

schtasks /create /tn $TaskName `
    /tr "`"$CmdPath`"" `
    /sc minute /mo 90 `
    /ru SYSTEM `
    /rl HIGHEST `
    /f

if ($LASTEXITCODE -ne 0) {
    throw "schtasks failed with exit $LASTEXITCODE"
}

Write-Host "Registered '$TaskName' as NT AUTHORITY\SYSTEM -> $CmdPath" -ForegroundColor Green
Write-Host "In Task Scheduler, object name is SYSTEM (Check Names -> NT AUTHORITY\SYSTEM)."
Write-Host "No password. Arguments stay empty."
