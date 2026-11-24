@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install requirements-graph.txt in your Python environment first. See README-D.md.
  exit /b 1
)
".venv\Scripts\python.exe" -m server.run_c
