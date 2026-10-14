@echo off
rem Same as SpeakerWeave.bat, but keeps a window open that shows any error text.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo SpeakerWeave is not set up yet. Run Install.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m speakerweave %*
pause
