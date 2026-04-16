@echo off
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
if exist "%CD%\.venv\Scripts\python.exe" (
  "%CD%\.venv\Scripts\python.exe" -m traffic_quantum.cli serve-web
) else (
  python -m traffic_quantum.cli serve-web
)
