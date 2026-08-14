@echo off
REM Task Scheduler entry point — no arguments required.
REM Program: <repo>\scripts\run_harvester.cmd
REM Arguments: (leave empty)
REM Run as: NT AUTHORITY\SYSTEM  (object name: SYSTEM)

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
set "DOCKER=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"
set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%ProgramFiles%\Docker\Docker\resources;%PATH%"

echo.
echo.>> "%LOG%"
call :log === Harvest started %DATE% %TIME% ===
call :log Project: %CD%
call :log Python:  %PY%
for /f "delims=" %%U in ('whoami') do call :log User: %%U

if not exist "%CD%\harvester.py" (
  call :log ERROR: harvester.py not found.
  goto :abort
)
if not exist "%PY%" (
  call :log ERROR: venv python not found. Run: python -m venv venv
  goto :abort
)
if not exist "%ENVFILE%" (
  call :log ERROR: .env not found. Copy .env.example to .env and fill secrets.
  goto :abort
)

REM Load .env into this process (SYSTEM has a clean environment).
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENVFILE%") do (
  if not "%%A"=="" if not "%%B"=="" set "%%A=%%B"
)

if defined DATABASE_REST_URL set "RESTURL=%DATABASE_REST_URL%"
if not defined DATABASE_REST_URL (
  set "DATABASE_REST_URL=%RESTURL%"
  call :log DATABASE_REST_URL missing from .env; using %RESTURL% for this run.
)

call :ensure_local_postgres
if errorlevel 1 goto :abort

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

call :log Launching harvester - live log below...
"%PY%" -u harvester.py >> "%LOG%" 2>&1
set "EXITCODE=%ERRORLEVEL%"

call :log === Harvest finished %DATE% %TIME% (exit %EXITCODE%) ===
if not "%EXITCODE%"=="0" (
  call :log Harvest failed. Common fixes:
  call :log   - Set GEMINI_API_KEY, SUPABASE_KEY, ADMIN_USER_ID, SUPABASE_SERVICE_ROLE_KEY in .env
  call :log   - Set DATABASE_REST_URL=http://127.0.0.1:3001 in .env
  call :log   - Docker Desktop Service must be running - the wrapper starts it as SYSTEM
  call :log   - Test: scripts\run_harvester.cmd
)
exit /b %EXITCODE%

:abort
call :log === Harvest aborted ===
exit /b 1

:log
echo(%*
>>"%LOG%" echo(%*
exit /b 0

:ensure_local_postgres
echo %RESTURL% | findstr /i /c:"127.0.0.1" /c:"localhost" >nul
if errorlevel 1 exit /b 0

call :log Local Postgres gateway: %RESTURL%

curl.exe -fsS "%RESTURL%/healthz" >nul 2>&1
if not errorlevel 1 (
  call :log REST gateway already healthy.
  exit /b 0
)

call :start_docker_engine
if errorlevel 1 exit /b 1

if not exist "%DOCKER%" (
  call :log ERROR: docker.exe not found at %DOCKER%
  exit /b 1
)

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
ping -n 4 127.0.0.1 >nul
set /a WAITED+=3
goto wait_gw

:start_docker_engine
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 (
  call :log Docker engine is already ready.
  exit /b 0
)

call :log Starting Docker Desktop Service as LocalSystem...
sc.exe query com.docker.service | findstr /i "RUNNING" >nul
if errorlevel 1 (
  sc.exe config com.docker.service start= auto >nul
  net start com.docker.service >nul 2>&1
)

if exist "%DOCKER%" (
  call :log Starting Docker engine via docker desktop start...
  "%DOCKER%" desktop start -d --timeout 180
)

set /a DWAIT=0
:wait_engine
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 (
  call :log Docker engine is ready.
  exit /b 0
)
curl.exe -fsS "%RESTURL%/healthz" >nul 2>&1
if not errorlevel 1 (
  call :log REST gateway became healthy while waiting for Docker.
  exit /b 0
)
if %DWAIT% GEQ 300 (
  call :log ERROR: Docker engine did not become ready in time.
  call :log   The harvest task runs as SYSTEM. It starts com.docker.service
  call :log   and "docker desktop start" - it does not use a Windows login.
  exit /b 1
)
call :log Waiting for Docker engine...
ping -n 11 127.0.0.1 >nul
set /a DWAIT+=10
goto wait_engine
