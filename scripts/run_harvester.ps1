# Optional helper. Task Scheduler should run run_harvester.cmd with no arguments.
# powershell.exe -File this script also works; it just launches the .cmd.
param()

$Cmd = Join-Path $PSScriptRoot "run_harvester.cmd"
if (-not (Test-Path -LiteralPath $Cmd)) {
    Write-Error "run_harvester.cmd not found next to this script."
    exit 1
}

cmd.exe /c "`"$Cmd`""
exit $LASTEXITCODE
