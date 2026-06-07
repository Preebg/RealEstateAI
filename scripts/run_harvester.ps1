# Run the hot-market harvester (Task Scheduler / manual use)
# Logs append to harvester_scheduled.log in the project root.
param()

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $VenvPython = "python"
}

$LogFile = Join-Path $ProjectRoot "harvester_scheduled.log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$RunLog = Join-Path $ProjectRoot "harvester_run_$((Get-Date -Format 'yyyyMMdd_HHmmss')).log"

function Write-LogLine([string]$Message) {
    $line = $Message
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-LogLine ""
Write-LogLine "=== Harvest started $Timestamp ==="
Write-LogLine "Project: $ProjectRoot"
Write-LogLine "Python:  $VenvPython"

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

# Start-Process avoids PowerShell treating Python stderr (e.g. Streamlit warnings) as a
# terminating error when $ErrorActionPreference is Stop.
$proc = Start-Process `
    -FilePath $VenvPython `
    -ArgumentList @("-u", "harvester.py") `
    -WorkingDirectory $ProjectRoot `
    -Wait -PassThru -NoNewWindow `
    -RedirectStandardOutput $RunLog `
    -RedirectStandardError "${RunLog}.err"

if (Test-Path $RunLog) {
    Get-Content -Path $RunLog -Encoding UTF8 | Add-Content -Path $LogFile -Encoding UTF8
}
if (Test-Path "${RunLog}.err") {
    $errText = Get-Content -Path "${RunLog}.err" -Encoding UTF8 -Raw
    if ($errText.Trim()) {
        Add-Content -Path $LogFile -Value "--- stderr ---" -Encoding UTF8
        Add-Content -Path $LogFile -Value $errText -Encoding UTF8
    }
}

$exitCode = $proc.ExitCode
$finished = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-LogLine "=== Harvest finished $finished (exit $exitCode) ==="

if ($exitCode -ne 0) {
    Write-LogLine "Harvest failed. Common fixes:"
    Write-LogLine "  - Add SUPABASE_SERVICE_ROLE_KEY to .streamlit/secrets.toml (required for scheduled runs)"
    Write-LogLine "  - Verify GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY, ADMIN_USER_ID"
    Write-LogLine "  - Run manually: cd $ProjectRoot; .\venv\Scripts\python.exe -u harvester.py"
}

exit $exitCode
