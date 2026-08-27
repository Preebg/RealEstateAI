@echo off
REM Stop the Docker stack after idle time to save power.
REM Register with Task Scheduler every 10 minutes (see setup_idle_guard.ps1).

setlocal
cd /d "%~dp0.."
if errorlevel 1 exit /b 1

set "ENVFILE=%CD%\.env"
set "DOCKER=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"
set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%ProgramFiles%\Docker\Docker\resources;%PATH%"
set "ACTIVITY=%CD%\data\.last_api_activity"
set "IDLE_MINUTES=30"
set "STOP_DOCKER=1"

if exist "%ENVFILE%" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENVFILE%") do (
    if not "%%A"=="" if not "%%B"=="" set "%%A=%%B"
  )
)

if "%STACK_ALWAYS_ON%"=="1" exit /b 0
if defined STACK_IDLE_MINUTES set "IDLE_MINUTES=%STACK_IDLE_MINUTES%"
if "%STACK_STOP_DOCKER%"=="0" set "STOP_DOCKER=0"

if not exist "%DOCKER%" exit /b 0

"%DOCKER%" compose ps --status running -q 2>nul | findstr . >nul
if errorlevel 1 exit /b 0

if not exist "%ACTIVITY%" exit /b 0

powershell -NoProfile -Command ^
  "$f='%ACTIVITY%';" ^
  "if (-not (Test-Path $f)) { exit 1 };" ^
  "$idle=[int]'%IDLE_MINUTES%';" ^
  "$age=((Get-Date).ToUniversalTime() - [DateTime]::Parse((Get-Content -Raw $f).Trim())).TotalMinutes;" ^
  "if ($age -lt $idle) { exit 2 } else { exit 0 }"
set "RC=%ERRORLEVEL%"
if "%RC%"=="1" exit /b 0
if "%RC%"=="2" exit /b 0
if not "%RC%"=="0" exit /b 0

echo Stopping idle Docker stack (no API traffic for %IDLE_MINUTES% min)...
"%DOCKER%" compose stop api postgres postgrest rest-gateway
if errorlevel 1 exit /b 1

if "%STOP_DOCKER%"=="0" exit /b 0

"%DOCKER%" ps -q 2>nul | findstr . >nul
if not errorlevel 1 exit /b 0

echo Stopping Docker Desktop engine...
"%DOCKER%" desktop stop >nul 2>&1
exit /b 0
