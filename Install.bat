@echo off
rem Sets SpeakerWeave up in this folder. Run it once (and again after an update).
cd /d "%~dp0"
title SpeakerWeave setup

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (
    where python >nul 2>nul && set PY=python
)
if not defined PY (
    echo.
    echo Python was not found on this PC.
    echo Install Python 3.12 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" on the first page of its installer.
    echo Then run this file again.
    echo.
    pause
    exit /b 1
)

echo Creating a private Python environment in this folder...
%PY% -m venv .venv
if errorlevel 1 goto failed

echo Downloading the libraries (a few minutes the first time)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo.
echo All done. Start the app with SpeakerWeave.bat
echo.
pause
exit /b 0

:failed
echo.
echo Setup did not finish. Scroll up to see the first error message.
echo.
pause
exit /b 1
