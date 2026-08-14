@echo off
REM Task Scheduler entry point — no arguments required.
REM Program: <repo>\scripts\run_harvester.cmd
REM Arguments: (leave empty)
REM Start in: (optional; this script cds to the repo root)

setlocal
cd /d "%~dp0.."
if errorlevel 1 (
  echo ERROR: could not cd to project root from "%~dp0"
  exit /b 1
)

set "LOG=%CD%\harvester_scheduled.log"
set "PY=%CD%\venv\Scripts\python.exe"
set "ENVFILE=%CD%\.env"
set "RESTURL=http://127.0.0.1:3001"

echo.
echo.>> "%LOG%"
call :log === Harvest started %DATE% %TIME% ===
call :log Project: %CD%
call :log Python:  %PY%

if not exist "%CD%\harvester.py" (
  call :log ERROR: harvester.py not found.
  call :log === Harvest aborted ===
  exit /b 1
)
if not exist "%PY%" (
  call :log ERROR: venv python not found. Run: python -m venv venv
  call :log === Harvest aborted ===
  exit /b 1
)
if not exist "%ENVFILE%" (
  call :log ERROR: .env not found. Copy .env.example to .env and fill secrets.
  call :log === Harvest aborted ===
  exit /b 1
)

REM Load .env into this process (Task Scheduler has a clean environment).
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENVFILE%") do (
  if not "%%A"=="" if not "%%B"=="" set "%%A=%%B"
)

if defined DATABASE_REST_URL set "RESTURL=%DATABASE_REST_URL%"
if not defined DATABASE_REST_URL (
  set "DATABASE_REST_URL=%RESTURL%"
  call :log DATABASE_REST_URL missing from .env; using %RESTURL% for this run.
)

call :ensure_local_postgres
if errorlevel 1 (
  call :log === Harvest aborted ===
  exit /b 1
)

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

call :log Launching harvester - live log below...
"%PY%" -u harvester.py >> "%LOG%" 2>&1
set "EXITCODE=%ERRORLEVEL%"

call :log === Harvest finished %DATE% %TIME% (exit %EXITCODE%) ===
if not "%EXITCODE%"=="0" (
  call :log Harvest failed. Common fixes:
  call :log   - Set GEMINI_API_KEY, SUPABASE_KEY, ADMIN_USER_ID, SUPABASE_SERVICE_ROLE_KEY in .env
  call :log   - For local Postgres: DATABASE_REST_URL=http://127.0.0.1:3001 and Docker Desktop running
  call :log   - Test: scripts\run_harvester.cmd
)
exit /b %EXITCODE%

:log
echo(%*
>>"%LOG%" echo(%*
exit /b 0

:ensure_local_postgres
echo %RESTURL% | findstr /i /c:"127.0.0.1" /c:"localhost" >nul
if errorlevel 1 exit /b 0

call :log Local Postgres gateway: %RESTURL%

set "DOCKER=docker"
where docker >nul 2>&1
if errorlevel 1 (
  if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" (
    set "DOCKER=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"
  )
)

call :wait_docker
if errorlevel 1 exit /b 1

call :log Ensuring postgres / postgrest / rest-gateway are up...
"%DOCKER%" compose up -d postgres postgrest rest-gateway
if errorlevel 1 (
  call :log ERROR: docker compose up failed.
  exit /b 1
)

set /a WAITED=0
:wait_gw
curl.exe -fsS "%RESTURL%/healthz" >nul 2>&1
if not errorlevel 1 (
  call :log REST gateway is healthy.
  exit /b 0
)
if %WAITED% GEQ 120 (
  call :log ERROR: REST gateway did not become healthy at %RESTURL%/healthz
  call :log   Check: docker compose ps
  exit /b 1
)
REM ping instead of timeout - timeout fails in some Task Scheduler sessions
ping -n 4 127.0.0.1 >nul
set /a WAITED+=3
goto wait_gw

:wait_docker
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 exit /b 0

if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
  call :log Starting Docker Desktop...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
) else (
  call :log ERROR: Docker engine is not running and Docker Desktop was not found.
  exit /b 1
)

set /a DWAIT=0
:wait_engine
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 (
  call :log Docker engine is ready.
  exit /b 0
)
if %DWAIT% GEQ 300 (
  call :log ERROR: Docker engine did not become ready in time.
  exit /b 1
)
call :log Waiting for Docker engine...
ping -n 11 127.0.0.1 >nul
set /a DWAIT+=10
goto wait_engine
