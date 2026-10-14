@echo off
rem Optional: checks the mixing engine on this PC. No sound is played.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install pytest >nul
".venv\Scripts\python.exe" -m pytest -q tests
pause
