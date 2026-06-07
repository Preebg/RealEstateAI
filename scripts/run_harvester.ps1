# Run the hot-market harvester (for Task Scheduler / manual use)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = "python"
}

$LogFile = Join-Path $ProjectRoot "harvester_scheduled.log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $LogFile -Value "`n=== Harvest started $Timestamp ==="

& $VenvPython harvester.py 2>&1 | Tee-Object -FilePath $LogFile -Append
