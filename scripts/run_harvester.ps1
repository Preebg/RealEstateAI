# Run the hot-market harvester (Task Scheduler / manual use)
# Output appends live to harvester_scheduled.log as Python runs.
param()

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$HarvesterPy = Join-Path $ProjectRoot "harvester.py"
$SecretsToml = Join-Path $ProjectRoot ".streamlit\secrets.toml"
$LogFile = Join-Path $ProjectRoot "harvester_scheduled.log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-LogLine([string]$Message) {
    Write-Host $Message
    Add-Content -Path $LogFile -Value $Message -Encoding UTF8
}

Write-LogLine ""
Write-LogLine "=== Harvest started $Timestamp ==="
Write-LogLine "Project: $ProjectRoot"
Write-LogLine "Python:  $VenvPython"

if (-not (Test-Path -LiteralPath $HarvesterPy)) {
    Write-LogLine "ERROR: harvester.py not found."
    Write-LogLine "=== Harvest aborted ==="
    exit 1
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-LogLine "ERROR: venv python not found. Run: python -m venv venv"
    Write-LogLine "=== Harvest aborted ==="
    exit 1
}
if (-not (Test-Path -LiteralPath $SecretsToml)) {
    Write-LogLine "ERROR: .streamlit\secrets.toml not found."
    Write-LogLine "=== Harvest aborted ==="
    exit 1
}

$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-LogLine "Launching harvester (live log below)..."

# cmd >> appends each line as Python flushes (-u). Avoids PowerShell stderr/Stop issues.
$cmdLine = "`"$VenvPython`" -u `"$HarvesterPy`" >> `"$LogFile`" 2>&1"
cmd.exe /c $cmdLine
$exitCode = $LASTEXITCODE

$finished = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-LogLine "=== Harvest finished $finished (exit $exitCode) ==="

if ($exitCode -ne 0) {
    Write-LogLine "Harvest failed. Common fixes:"
    Write-LogLine "  - Add SUPABASE_SERVICE_ROLE_KEY to .streamlit\secrets.toml"
    Write-LogLine "  - Verify GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY, ADMIN_USER_ID"
    Write-LogLine "  - Test: cd $ProjectRoot; .\scripts\run_harvester.ps1"
}

exit $exitCode
