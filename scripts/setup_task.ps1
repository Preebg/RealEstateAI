# Register Task Scheduler to run the harvester every 90 minutes.
# Uses run_harvester.cmd with no arguments (same as a manual double-click).
# Run this as the Windows user that can start Docker Desktop — not SYSTEM.

$CmdPath = Join-Path $PSScriptRoot "run_harvester.cmd"
if (-not (Test-Path -LiteralPath $CmdPath)) {
    throw "run_harvester.cmd not found at $CmdPath"
}

$TaskName = "RealEstateAI_Harvester"
schtasks /create /tn $TaskName `
    /tr "`"$CmdPath`"" `
    /sc minute /mo 90 `
    /f

if ($LASTEXITCODE -ne 0) {
    throw "schtasks failed with exit $LASTEXITCODE"
}

Write-Host "Registered '$TaskName' -> $CmdPath (no arguments)." -ForegroundColor Green
Write-Host "Run as the logged-on Docker Desktop user, not SYSTEM."
