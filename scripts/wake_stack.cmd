@echo off
REM Start the local Postgres + API stack on demand (harvester + wake proxy).
REM Usage: scripts\wake_stack.cmd

setlocal
cd /d "%~dp0.."
if errorlevel 1 exit /b 1

set "LOG=%CD%\stack_wake.log"
set "ENVFILE=%CD%\.env"
set "RESTURL=http://127.0.0.1:3001"
set "APIURL=http://127.0.0.1:8000/api/health"
set "DOCKER=%ProgramFiles%\Docker\Docker\resources\bin\docker.exe"
set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%ProgramFiles%\Docker\Docker\resources;%PATH%"
set "ACTIVITY=%CD%\data\.last_api_activity"

if exist "%ENVFILE%" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ENVFILE%") do (
    if not "%%A"=="" if not "%%B"=="" set "%%A=%%B"
  )
)
if defined DATABASE_REST_URL set "RESTURL=%DATABASE_REST_URL%"

curl.exe -fsS "%APIURL%" >nul 2>&1
if not errorlevel 1 (
  call :touch_activity
  exit /b 0
)

call :log Waking Docker stack...
call :start_docker_engine
if errorlevel 1 exit /b 1

if not exist "%DOCKER%" (
  call :log ERROR: docker.exe not found.
  exit /b 1
)

"%DOCKER%" compose up -d postgres postgrest rest-gateway api
if errorlevel 1 (
  call :log ERROR: docker compose up failed.
  exit /b 1
)

set /a WAITED=0
:wait_api
curl.exe -fsS "%APIURL%" >nul 2>&1
if not errorlevel 1 (
  call :log API is healthy.
  call :touch_activity
  exit /b 0
)
curl.exe -fsS "%RESTURL%/healthz" >nul 2>&1
if errorlevel 1 (
  if %WAITED% GEQ 120 (
    call :log ERROR: REST gateway did not become healthy at %RESTURL%/healthz
    exit /b 1
  )
) else if %WAITED% GEQ 180 (
  call :log ERROR: API did not become healthy at %APIURL%
  exit /b 1
)
ping -n 4 127.0.0.1 >nul
set /a WAITED+=3
goto wait_api

:start_docker_engine
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 exit /b 0

call :log Starting Docker Desktop Service...
sc.exe query com.docker.service | findstr /i "RUNNING" >nul
if errorlevel 1 (
  sc.exe config com.docker.service start= auto >nul
  net start com.docker.service >nul 2>&1
)
if exist "%DOCKER%" "%DOCKER%" desktop start -d --timeout 180

set /a DWAIT=0
:wait_engine
"%DOCKER%" info >nul 2>&1
if not errorlevel 1 exit /b 0
if %DWAIT% GEQ 300 (
  call :log ERROR: Docker engine did not become ready.
  exit /b 1
)
ping -n 11 127.0.0.1 >nul
set /a DWAIT+=10
goto wait_engine

:touch_activity
if not exist "%CD%\data" mkdir "%CD%\data" >nul 2>&1
powershell -NoProfile -Command "[DateTime]::UtcNow.ToString('o')" > "%ACTIVITY%" 2>nul
exit /b 0

:log
echo(%*
>>"%LOG%" echo(%*
exit /b 0
