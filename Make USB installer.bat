@echo off
rem Builds the installer with the latest changes and copies everything needed to
rem install SpeakerWeave on another PC into a folder on a USB drive.
cd /d "%~dp0"
title Put SpeakerWeave on a USB drive
if not exist ".venv\Scripts\python.exe" (
    echo SpeakerWeave is not set up yet. Run Install.bat first.
    pause
    exit /b 1
)
echo Step 1 of 2: building the installer with the latest changes. This takes a few minutes.
echo.
".venv\Scripts\python.exe" packaging\build.py
if errorlevel 1 (
    echo.
    echo The build did not finish, so nothing was copied to the USB drive.
    pause
    exit /b 1
)
echo.
echo Step 2 of 2: copying it to the USB drive
echo.
".venv\Scripts\python.exe" packaging\make_usb.py %*
echo.
pause
