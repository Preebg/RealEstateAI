# Register idle shutdown guard — run every 10 minutes as SYSTEM.
# Stops the Docker stack when there has been no API traffic for STACK_IDLE_MINUTES.

$ErrorActionPreference = "Stop"

$CmdPath = Join-Path $PSScriptRoot "stack_idle_guard.cmd"
if (-not (Test-Path -LiteralPath $CmdPath)) {
    throw "stack_idle_guard.cmd not found at $CmdPath"
}

$TaskName = "RealEstateAI_StackIdleGuard"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell (Run as administrator)."
}

schtasks /create /tn $TaskName `
    /tr "`"$CmdPath`"" `
    /sc minute /mo 10 `
    /ru SYSTEM `
    /rl HIGHEST `
    /f

if ($LASTEXITCODE -ne 0) {
    throw "schtasks failed with exit $LASTEXITCODE"
}

Write-Host "Registered '$TaskName' every 10 minutes -> $CmdPath" -ForegroundColor Green
Write-Host "Set STACK_IDLE_MINUTES in .env (default 30). Use STACK_ALWAYS_ON=1 to disable."
