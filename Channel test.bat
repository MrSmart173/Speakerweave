@echo off
cd /d "%~dp0"
title SpeakerWeave channel test
echo Playing quiet test tones into CABLE Input for a few seconds...
".venv\Scripts\python.exe" -m speakerweave.channelcheck "channel test.txt"
echo.
echo Done. The result is in "channel test.txt".
pause
