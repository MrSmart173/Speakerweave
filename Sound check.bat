@echo off
cd /d "%~dp0"
title SpeakerWeave sound check
if not exist ".venv\Scripts\python.exe" (
    echo SpeakerWeave is not set up yet. Run Install.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m speakerweave.soundcheck "sound check report.txt"
echo.
echo The report is saved as "sound check report.txt" in this folder.
pause
