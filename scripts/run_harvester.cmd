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

if not "%STACK_ALWAYS_ON%"=="1" (
  call :log Stopping Docker stack after harvest to save power...
  if exist "%DOCKER%" "%DOCKER%" compose stop api postgres postgrest rest-gateway >nul 2>&1
  if not "%STACK_STOP_DOCKER%"=="0" (
    "%DOCKER%" ps -q 2>nul | findstr . >nul
    if errorlevel 1 "%DOCKER%" desktop stop >nul 2>&1
  )
)

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
call "%~dp0wake_stack.cmd"
exit /b %ERRORLEVEL%
