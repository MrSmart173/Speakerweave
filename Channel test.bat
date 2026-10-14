@echo off
cd /d "%~dp0"
title SpeakerWeave channel test
echo Playing quiet test tones into CABLE Input for about 20 seconds...
".venv\Scripts\python.exe" -m speakerweave.channelcheck "channel test.txt"
echo.
echo Done. The result is in "channel test.txt".
pause
