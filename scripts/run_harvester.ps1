# Run the hot-market harvester (Task Scheduler / manual use)
# Output appends live to harvester_scheduled.log as Python runs.
param()

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$HarvesterPy = Join-Path $ProjectRoot "harvester.py"
$DotEnv = Join-Path $ProjectRoot ".env"
$LogFile = Join-Path $ProjectRoot "harvester_scheduled.log"
$DefaultLocalRestUrl = "http://127.0.0.1:3001"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-LogLine([string]$Message) {
    Write-Host $Message
    Add-Content -Path $LogFile -Value $Message -Encoding UTF8
}

function Get-DotEnvValue([string]$Key) {
    if (-not (Test-Path -LiteralPath $DotEnv)) {
        return $null
    }
    foreach ($raw in Get-Content -LiteralPath $DotEnv -Encoding UTF8) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#") -or ($line.IndexOf("=") -lt 1)) {
            continue
        }
        $name, $value = $line -split "=", 2
        if ($name.Trim() -eq $Key) {
            return $value.Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Import-ProjectDotEnv {
    if (-not (Test-Path -LiteralPath $DotEnv)) {
        return
    }
    foreach ($raw in Get-Content -LiteralPath $DotEnv -Encoding UTF8) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#") -or ($line.IndexOf("=") -lt 1)) {
            continue
        }
        $name, $value = $line -split "=", 2
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if (-not $name) {
            continue
        }
        $existing = [Environment]::GetEnvironmentVariable($name, "Process")
        if ([string]::IsNullOrWhiteSpace($existing)) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Test-DockerEngine {
    try {
        docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Start-DockerEngine {
    if (Test-DockerEngine) {
        return $true
    }

    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Docker\Docker\Docker Desktop.exe")
    )
    $started = $false
    foreach ($exe in $candidates) {
        if (Test-Path -LiteralPath $exe) {
            Write-LogLine "Starting Docker Desktop..."
            Start-Process -FilePath $exe | Out-Null
            $started = $true
            break
        }
    }
    if (-not $started) {
        Write-LogLine "ERROR: Docker engine is not running and Docker Desktop was not found."
        return $false
    }

    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerEngine) {
            Write-LogLine "Docker engine is ready."
            return $true
        }
        Write-LogLine "Waiting for Docker engine..."
        Start-Sleep -Seconds 10
    }
    Write-LogLine "ERROR: Docker engine did not become ready in time."
    return $false
}

function Test-RestGatewayHealthy([string]$BaseUrl) {
    $health = ($BaseUrl.TrimEnd("/")) + "/healthz"
    try {
        $resp = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 5
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
    } catch {
        return $false
    }
}

function Test-LocalRestUrl([string]$Url) {
    try {
        $parsed = [Uri]$Url
        return ($parsed.Host -in @("127.0.0.1", "localhost", "::1"))
    } catch {
        return $false
    }
}

function Start-LocalPostgresStack([string]$RestUrl) {
    if (-not (Test-LocalRestUrl $RestUrl)) {
        return $true
    }

    Write-LogLine "Local Postgres gateway: $RestUrl"
    if (-not (Start-DockerEngine)) {
        return $false
    }

    Write-LogLine "Ensuring postgres / postgrest / rest-gateway are up..."
    docker compose up -d postgres postgrest rest-gateway
    if ($LASTEXITCODE -ne 0) {
        Write-LogLine "ERROR: docker compose up failed (exit $LASTEXITCODE)."
        return $false
    }

    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        if (Test-RestGatewayHealthy $RestUrl) {
            Write-LogLine "REST gateway is healthy."
            return $true
        }
        Start-Sleep -Seconds 3
    }
    Write-LogLine "ERROR: REST gateway did not become healthy at $RestUrl/healthz"
    Write-LogLine "  Check: docker compose ps"
    return $false
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
if (-not (Test-Path -LiteralPath $DotEnv)) {
    Write-LogLine "ERROR: .env not found. Copy .env.example to .env and fill secrets."
    Write-LogLine "=== Harvest aborted ==="
    exit 1
}

Import-ProjectDotEnv

$restUrl = Get-DotEnvValue "DATABASE_REST_URL"
if ([string]::IsNullOrWhiteSpace($restUrl)) {
    $restUrl = $DefaultLocalRestUrl
    $env:DATABASE_REST_URL = $restUrl
    Write-LogLine "DATABASE_REST_URL missing from .env; using $restUrl for this run."
    Write-LogLine "  Add DATABASE_REST_URL=$restUrl to .env so harvest writes to local Postgres."
}

if (-not (Start-LocalPostgresStack $restUrl)) {
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
    Write-LogLine "  - Set GEMINI_API_KEY, SUPABASE_KEY, ADMIN_USER_ID, SUPABASE_SERVICE_ROLE_KEY in .env"
    Write-LogLine "  - For local Postgres: DATABASE_REST_URL=http://127.0.0.1:3001 and Docker Desktop running"
    Write-LogLine "  - Test: cd $ProjectRoot; .\scripts\run_harvester.ps1"
}

exit $exitCode
