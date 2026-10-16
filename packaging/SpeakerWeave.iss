; Inno Setup recipe for the SpeakerWeave installer.
; Run through "Build installer.bat", which fills in the version and publisher.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; how the version is shown, for example "Beta v1.0" (see STAGE in speakerweave/release.py)
#ifndef AppVersionName
  #define AppVersionName AppVersion
#endif
#ifndef SetupName
  #define SetupName "SpeakerWeave-Setup-" + AppVersion
#endif
#ifndef Publisher
  #define Publisher "SpeakerWeave"
#endif
#ifndef Website
  #define Website ""
#endif
; DistDir is the folder that holds the built "SpeakerWeave" app folder.
#ifndef DistDir
  #define DistDir "..\dist"
#endif
#define AppName "SpeakerWeave"
#define AppExe "SpeakerWeave.exe"

[Setup]
; AppId ties every future version to this one, so a new installer updates the
; existing copy instead of adding a second one. Never change it.
AppId={{EDB9FFFE-5B25-4100-AC8F-3D212E27D4EA}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersionName}
AppPublisher={#Publisher}
#if Website != ""
AppPublisherURL={#Website}
AppSupportURL={#Website}
#endif
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany={#Publisher}

; The person installing picks the folder. "For me only" needs no admin rights,
; "for everyone" installs under Program Files and asks for them.
DefaultDirName={autopf}\{#AppName}
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

; Updating: close the running app, replace its files, start it again.
CloseApplications=yes
CloseApplicationsFilter={#AppExe}
RestartApplications=no

#ifdef LicenseFile
; the person installing must accept these terms
LicenseFile={#LicenseFile}
#endif
OutputDir={#DistDir}\installer
OutputBaseFilename={#SetupName}
SetupIconFile=SpeakerWeave.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start SpeakerWeave when Windows starts, so the PC plays through your speakers from the moment it boots"; GroupDescription: "Starting:"
#ifdef WithVbCable
Name: "vbcable"; Description: "Install the VB-CABLE virtual sound device by VB-Audio (lets SpeakerWeave receive everything this PC plays)"; GroupDescription: "Virtual sound device:"; Check: not VbCablePresent
#endif

[Files]
Source: "{#DistDir}\SpeakerWeave\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef WithVbCable
Source: "..\third_party\VBCABLE\*"; DestDir: "{app}\VBCABLE"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[InstallDelete]
; files of an older version that the new one no longer ships
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
#ifdef WithVbCable
; VB-CABLE is a donationware, all participations are welcome. https://vb-audio.com/Cable/
Filename: "{app}\VBCABLE\VBCABLE_Setup_x64.exe"; StatusMsg: "Opening the VB-CABLE driver setup. Press Install Driver in its window..."; Verb: runas; Flags: shellexec waituntilterminated skipifsilent; Tasks: vbcable
#endif
; first install: offer to start the app on the last page
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
; update started from inside the app: start the new version again without asking
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[Registry]
; the same entry the app writes for "Start SpeakerWeave when Windows starts". Only a
; normal install sets it, so a quiet update never turns it back on after it was switched off.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --tray"; Tasks: startup; Check: not WizardSilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
var
  DataDir: String;      { SpeakerWeave's own data folder, deleted at the very end when set }

{ /NAME or /NAME="value" on the command line. SpeakerWeave's Settings page starts the
  uninstaller with /REMOVEDATA="<its data folder>" or /KEEPDATA. }
function CmdValue(const Name: String; var Value: String): Boolean;
var
  I: Integer;
  P, Key: String;
begin
  Result := False;
  Key := '/' + Uppercase(Name);
  for I := 1 to ParamCount do
  begin
    P := ParamStr(I);
    if Uppercase(P) = Key then
    begin
      Value := '';
      Result := True;
      Exit;
    end;
    if Uppercase(Copy(P, 1, Length(Key) + 1)) = Key + '=' then
    begin
      Value := RemoveQuotes(Copy(P, Length(Key) + 2, Length(P)));
      Result := True;
      Exit;
    end;
  end;
end;

{ only SpeakerWeave's own folder may ever be deleted, never one that merely holds it }
function IsDataFolder(const Folder: String): Boolean;
var
  Name: String;
begin
  Name := Lowercase(ExtractFileName(RemoveBackslashUnlessRoot(Folder)));
  Result := (Folder <> '') and DirExists(Folder) and (Pos('speakerweave', Name) = 1);
end;

{ the SpeakerWeave plugin SimHub may have been given from the Effects tab }
procedure RemoveSimHubPlugin();
var
  Folder, Dll: String;
  Code: Integer;
begin
  Folder := GetEnv('SIMHUB_INSTALL_PATH');
  if (Folder = '') or not FileExists(AddBackslash(Folder) + 'SimHubWPF.exe') then
    if not RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{019253FE-5A17-42BE-A6B8-D71A729FA5DE}_is1',
                               'InstallLocation', Folder) then
      Folder := ExpandConstant('{commonpf32}\SimHub');
  Dll := AddBackslash(Folder) + 'SpeakerWeave.SimHubPlugin.dll';
  if FileExists(Dll) and not DeleteFile(Dll) then
    { SimHub lives in Program Files: a "for me only" uninstall asks Windows for the rights }
    ShellExec('runas', ExpandConstant('{cmd}'), '/c del /f /q "' + Dll + '"', '', SW_HIDE,
              ewWaitUntilTerminated, Code);
end;

function InitializeUninstall(): Boolean;
var
  Waited: Integer;
begin
  Result := True;
  { started from SpeakerWeave itself, it is closing right now: give it time to finish }
  Waited := 0;
  while CheckForMutexes('SpeakerWeaveAppRunning') and (Waited < 150) do
  begin
    Sleep(100);
    Waited := Waited + 1;
  end;
  while CheckForMutexes('SpeakerWeaveAppRunning') do
    if MsgBox('SpeakerWeave is still running. Quit it first: right click its icon in the system ' +
              'tray and choose Quit SpeakerWeave. Then press OK.', mbInformation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  Sleep(500);           { the closed app lets go of its files }
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Value, Usual: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    { VB-CABLE stays installed: give its output back its own name, "CABLE Input" }
    Exec(ExpandConstant('{app}\{#AppExe}'), '--unbrand', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    { the app itself may have added SpeakerWeave to the Windows start list }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
    RemoveSimHubPlugin();
    DataDir := '';
    Usual := ExpandConstant('{localappdata}\{#AppName}');
    if CmdValue('REMOVEDATA', Value) then
      DataDir := Value
    else if FileExists(AddBackslash(Usual) + 'remove on uninstall') then
      DataDir := Usual          { the app left this mark when its data should go }
    else if not CmdValue('KEEPDATA', Value) and not UninstallSilent() and IsDataFolder(Usual) then
    begin
      { started from Windows Settings, Apps: ask }
      { the line breaks stay inside the line: ISPP reads a line starting with # as its own }
      if MsgBox('Also delete your SpeakerWeave settings, speaker setups, game setups and test sounds?' + #13#10#13#10 +
                Usual, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DataDir := Usual;
    end;
  end;
  if (CurUninstallStep = usPostUninstall) and IsDataFolder(DataDir) then
    DelTree(DataDir, True, True, True);
end;

function VbCablePresent(): Boolean;
begin
  { VB-CABLE registers its driver service under this name }
  Result := RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\VBAudioVACMME');
end;
