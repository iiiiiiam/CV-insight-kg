@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create .venv and install server/requirements.txt first. See README-D.md.
  exit /b 1
)
".venv\Scripts\python.exe" -m server.run_a
