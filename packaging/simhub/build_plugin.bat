@echo off
rem Builds the SpeakerWeave plugin for SimHub with the C# compiler that comes with Windows.
rem Usage: build_plugin.bat [output folder]      SimHub must be installed on this PC.
setlocal
rem the folder of this file, taken before anything changes the current folder
set "HERE=%~dp0"
set "OUT=%~1"
if "%OUT%"=="" set "OUT=%HERE%out"
if "%OUT:~-1%"=="\" set "OUT=%OUT:~0,-1%"
set "SIMHUB=%SIMHUB_INSTALL_PATH%"
if "%SIMHUB%"=="" set "SIMHUB=%ProgramFiles(x86)%\SimHub"
if "%SIMHUB:~-1%"=="\" set "SIMHUB=%SIMHUB:~0,-1%"
if not exist "%SIMHUB%\SimHub.Plugins.dll" (
    echo SimHub was not found in "%SIMHUB%", the SimHub plugin is left out.
    exit /b 2
)
set "NET=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319"
if not exist "%NET%\csc.exe" set "NET=%WINDIR%\Microsoft.NET\Framework\v4.0.30319"
if not exist "%NET%\csc.exe" (
    echo The C# compiler of Windows was not found, the SimHub plugin is left out.
    exit /b 3
)
if not exist "%OUT%" mkdir "%OUT%"
"%NET%\csc.exe" /nologo /target:library /optimize+ /warn:3 /out:"%OUT%\SpeakerWeave.SimHubPlugin.dll" /lib:"%SIMHUB%" /lib:"%NET%\WPF" /reference:SimHub.Plugins.dll /reference:GameReaderCommon.dll /reference:WoteverCommon.dll /reference:SimHub.Logging.dll /reference:log4net.dll /reference:PresentationCore.dll /reference:PresentationFramework.dll /reference:WindowsBase.dll /reference:System.Xaml.dll "%HERE%SpeakerWeavePlugin.cs"
if errorlevel 1 (
    echo Building the SimHub plugin failed.
    exit /b 1
)
echo Built "%OUT%\SpeakerWeave.SimHubPlugin.dll"
exit /b 0
