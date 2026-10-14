@echo off
rem Builds the installer like "Build installer.bat", and keeps everything it says in "build log.txt" next to this file.
cd /d "%~dp0.."
".venv\Scripts\python.exe" -u packaging\build.py > "packaging\build log.txt" 2>&1 < nul
echo EXIT %ERRORLEVEL% >> "packaging\build log.txt"
