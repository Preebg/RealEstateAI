@echo off
REM Always-on wake proxy for /api traffic (low CPU; starts Docker only on demand).
REM Point Caddy /api/* at http://127.0.0.1:8088

setlocal
cd /d "%~dp0.."
set "PY=%CD%\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -u scripts\wake_proxy.py
