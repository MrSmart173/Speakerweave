@echo off
rem Builds SpeakerWeave.exe and its installer. The result lands in dist\installer.
cd /d "%~dp0"
title Build the SpeakerWeave installer
if not exist ".venv\Scripts\python.exe" (
    echo SpeakerWeave is not set up yet. Run Install.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" packaging\build.py
echo.
pause
