; ============================================================
;  Z's Multi Tool - Inno Setup installer script
; ============================================================
; Requires Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
;
; Build the app first (build.bat), THEN compile this script -
; it expects "dist\Z's Multi Tool.exe" to already exist.
;
; To compile: open this file in the Inno Setup IDE and hit
; Build > Compile, or from the command line:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" install.iss
; ============================================================

#define MyAppName "Z's Multi Tool"
#define MyAppVersion "4.0.5"
#define MyAppPublisher "Z"
#define MyAppExeName "Z's Multi Tool.exe"
#define MyAppIcon "assets\icon.ico"
; Pascal-string-safe copy of MyAppName - use this (not MyAppName) anywhere
; it gets embedded inside a single-quoted string in [Code]. MyAppName
; contains an apostrophe, which would otherwise close the Pascal string
; literal early and break compilation (same issue build.bat's comment
; warns about for PyInstaller's --name).
#define MyAppNamePS StringChange(MyAppName, "'", "''")

[Setup]
; AppId uniquely identifies this app to Windows so upgrades/uninstalls
; work correctly - generated once, don't change it between versions.
AppId={{C3B4E9E1-6C3A-4B2F-9A2F-9F9B7B2C4A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=installer_output
OutputBaseFilename=ZsMultiTool_Setup_{#MyAppVersion}
SetupIconFile={#MyAppIcon}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
; Program Files install needs admin rights. Switch to
; PrivilegesRequired=lowest + DefaultDirName={localappdata}\Programs\{#MyAppName}
; if you'd rather install per-user with no UAC prompt.
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; portablemode keeps the application and its bundled tools together in the selected folder.
; Note: this is portable-style, not a true registry-free portable build.
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startupicon"; Description: "Launch {#MyAppName} at Windows startup"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "runasadmin"; Description: "Always run {#MyAppName} as administrator (needed for the Network Auditor module's packet capture)"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "portablemode"; Description: "Portable-style installation (keep app files together in the selected folder)"; GroupDescription: "Installation options:"; Flags: unchecked

[Files]
; The onefile PyInstaller / Qt (PySide6) build - everything
; (modules/core/pages/assets) is already bundled inside this single exe.
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; VLC runtime, needed by Media Player (python-vlc loads libvlc.dll at
; runtime - PyInstaller can't bundle this into the exe itself).
; build.bat copies these into dist\ automatically if it finds a local
; VLC install; if dist\libvlc.dll doesn't exist when you compile this
; script, re-run build.bat with VLC installed first.
Source: "dist\libvlc.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\libvlccore.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\plugins\*"; DestDir: "{app}\plugins"; Flags: ignoreversion recursesubdirs createallsubdirs

; Helper script used at install time to look up the current Npcap/Nmap
; download links (see [Code] below) - extracted to {tmp} on demand via
; ExtractTemporaryFile, never actually installed into {app}.
Source: "resolve_net_tools.ps1"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
; Dependencies are prepared before the main installation in PrepareToInstall.
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; Removes the exe/shortcuts installed above. Deliberately NOT touching
; %APPDATA%\ZsMultiTool here - that's where the Security Vault's
; master.key/vault.json, save-manager backups, and notes live, and
; silently wiping that on every uninstall would be a good way to lose
; someone's vault. Uncomment below if you ever want a "delete all my
; data" style uninstall instead:
; Type: filesandordirs; Name: "{userappdata}\ZsMultiTool"

[Code]

function SendMessageTimeout(hWnd, Msg, wParam, lParam, fuFlags, uTimeout: Integer; var lpdwResult: Integer): Integer; external 'SendMessageTimeoutW@user32.dll stdcall';

var
  DownloadedNpcap, DownloadedNmap, DownloadedYtDlp: Boolean;

const
  YtDlpUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe';
  FfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip';

function RunHidden(const FileName, Parameters, WorkingDir: String; var ResultCode: Integer): Boolean;
begin
  Result := Exec(FileName, Parameters, WorkingDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// Checks whether CommandName resolves on the system PATH (e.g. a
// standalone ffmpeg or yt-dlp the user already installed themselves,
// outside of {app}\tools). where.exe returns 0 if it finds a match and
// 1 if it doesn't, so this is a cheap, reliable presence check without
// needing to know where the thing actually lives.
function IsCommandOnPath(const CommandName: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := RunHidden(ExpandConstant('{sys}\where.exe'), CommandName,
    ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0);
  if Result then
    Log('Dependency check: ' + CommandName + ' found on system PATH.');
end;

procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel2.Caption :=
    WizardForm.WelcomeLabel2.Caption + Chr(13) + Chr(10) + Chr(13) + Chr(10) +
    'Dependency detection is automatic. Z''s Multi Tool checks for Npcap, ' +
    'Nmap, FFmpeg, and yt-dlp and only downloads components that are missing.' +
    Chr(13) + Chr(10) + Chr(13) + Chr(10) +
    'Upgrades keep the same application ID and installation directory so ' +
    'existing installations can be updated without creating a second app.';
end;

function IsNpcapInstalled(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Npcap') or
            RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Npcap');
  if Result then
    Log('Dependency check: Npcap is installed.')
  else
    Log('Dependency check: Npcap is missing.');
end;

function IsNmapInstalled(): Boolean;
begin
  { Registry is the official install, but chocolatey/scoop/manual copies
    often skip it. If nmap.exe is already on PATH or in Program Files,
    treat it as installed so we do not re-run nmap-setup.exe (that
    installer always recreates the Zenmap desktop shortcut). }
  Result := RegKeyExists(HKLM, 'SOFTWARE\Nmap') or
            RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Nmap') or
            FileExists(ExpandConstant('{pf}\Nmap\nmap.exe')) or
            FileExists(ExpandConstant('{pf32}\Nmap\nmap.exe')) or
            IsCommandOnPath('nmap.exe');
  if Result then
    Log('Dependency check: Nmap is installed.')
  else
    Log('Dependency check: Nmap is missing.');
end;

{ The official Nmap NSIS installer always writes "Nmap - Zenmap GUI" on
  the desktop, including under /S. We only need the nmap CLI for Network
  Auditor — delete the GUI shortcut after install / on every upgrade so
  it does not keep coming back. }
procedure TryDeleteFile(const FileName: String);
begin
  if FileExists(FileName) then
  begin
    if DeleteFile(FileName) then
      Log('Removed Nmap desktop shortcut: ' + FileName)
    else
      Log('Could not remove Nmap desktop shortcut: ' + FileName);
  end;
end;

procedure RemoveNmapDesktopShortcuts();
begin
  TryDeleteFile(ExpandConstant('{userdesktop}\Nmap - Zenmap GUI.lnk'));
  TryDeleteFile(ExpandConstant('{commondesktop}\Nmap - Zenmap GUI.lnk'));
  TryDeleteFile(ExpandConstant('{userdesktop}\Zenmap.lnk'));
  TryDeleteFile(ExpandConstant('{commondesktop}\Zenmap.lnk'));
  TryDeleteFile(ExpandConstant('{userdesktop}\Nmap.lnk'));
  TryDeleteFile(ExpandConstant('{commondesktop}\Nmap.lnk'));
  TryDeleteFile(ExpandConstant('{userdesktop}\Nmap - Zenmap.lnk'));
  TryDeleteFile(ExpandConstant('{commondesktop}\Nmap - Zenmap.lnk'));
end;

procedure AddToSystemPath(const NewPath: String);
var
  PathValue: String;
  BroadcastResult: Integer;
begin
  PathValue := '';
  if not RegQueryStringValue(HKLM,
       'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
       'Path', PathValue) then
  begin
    Log('Could not read the system PATH.');
    Exit;
  end;

  if Pos(';' + LowerCase(NewPath) + ';', ';' + LowerCase(PathValue) + ';') = 0 then
  begin
    if (PathValue <> '') and (PathValue[Length(PathValue)] <> ';') then
      PathValue := PathValue + ';';
    if RegWriteStringValue(HKLM,
         'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
         'Path', PathValue + NewPath) then
    begin
      BroadcastResult := 0;
      SendMessageTimeout($FFFF, $001A, 0, 0, $0002, 5000, BroadcastResult);
      Log('Added to system PATH: ' + NewPath);
    end
    else
      Log('Could not update system PATH with: ' + NewPath);
  end
  else
    Log('Already in system PATH: ' + NewPath);
end;

procedure DownloadFfmpeg();
var
  CurlExe, PowerShellExe, ZipFile, ExtractDir, TargetDir, BinDir: String;
  ResultCode: Integer;
begin
  TargetDir := ExpandConstant('{app}\tools\ffmpeg');
  BinDir := TargetDir + '\bin';
  if FileExists(BinDir + '\ffmpeg.exe') then
  begin
    Log('Dependency check: FFmpeg is already installed in {app}\tools.');
    AddToSystemPath(BinDir);
    Exit;
  end;
  if IsCommandOnPath('ffmpeg.exe') then
  begin
    Log('Dependency check: FFmpeg already available on system PATH - skipping download.');
    Exit;
  end;
  Log('Dependency check: FFmpeg is missing; downloading it.');

  CurlExe := ExpandConstant('{sys}\curl.exe');
  PowerShellExe := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  if (not FileExists(CurlExe)) or (not FileExists(PowerShellExe)) then
  begin
    Log('DownloadFfmpeg: curl.exe or PowerShell not found.');
    Exit;
  end;

  ForceDirectories(TargetDir);
  ZipFile := ExpandConstant('{tmp}\ffmpeg-release-essentials.zip');
  ExtractDir := ExpandConstant('{tmp}\ffmpeg_extract');

  if not (RunHidden(CurlExe,
       '--connect-timeout 15 --max-time 300 -L --fail -o "' + ZipFile + '" "' + FfmpegUrl + '"',
       ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0) and FileExists(ZipFile)) then
  begin
    Log('DownloadFfmpeg: download failed, ResultCode=' + IntToStr(ResultCode));
    Exit;
  end;

  if DirExists(ExtractDir) then
    DelTree(ExtractDir, True, True, True);
  ForceDirectories(ExtractDir);

  if not (RunHidden(PowerShellExe,
       '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''' + ZipFile + ''' -DestinationPath ''' + ExtractDir + ''' -Force"',
       ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0)) then
  begin
    Log('DownloadFfmpeg: extraction failed, ResultCode=' + IntToStr(ResultCode));
    Exit;
  end;

  if not Exec(PowerShellExe,
       '-NoProfile -ExecutionPolicy Bypass -Command "$d=Get-ChildItem -LiteralPath ''' + ExtractDir + ''' -Directory | Select-Object -First 1; if ($null -eq $d) { exit 1 }; Copy-Item -LiteralPath ($d.FullName+''\bin'') -Destination ''' + TargetDir + ''' -Recurse -Force"',
       ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('DownloadFfmpeg: could not copy FFmpeg files.');
    Exit;
  end;

  if FileExists(BinDir + '\ffmpeg.exe') then
    AddToSystemPath(BinDir)
  else
    Log('DownloadFfmpeg: ffmpeg.exe was not found after extraction.');
end;

procedure DownloadYtDlp();
var
  CurlExe: String;
  ResultCode: Integer;
  TargetDir, TargetFile, TempFile: String;
begin
  DownloadedYtDlp := False;
  TargetDir := ExpandConstant('{app}\tools');
  TargetFile := TargetDir + '\yt-dlp.exe';
  if FileExists(TargetFile) then
  begin
    Log('Dependency check: yt-dlp is already installed in {app}\tools.');
    Exit;
  end;
  if IsCommandOnPath('yt-dlp.exe') then
  begin
    Log('Dependency check: yt-dlp already available on system PATH - skipping download.');
    Exit;
  end;
  Log('Dependency check: yt-dlp is missing; downloading it.');

  CurlExe := ExpandConstant('{sys}\curl.exe');
  if not FileExists(CurlExe) then
  begin
    Log('DownloadYtDlp: curl.exe not found, skipping yt-dlp auto-download.');
    Exit;
  end;

  ForceDirectories(TargetDir);
  TempFile := ExpandConstant('{tmp}\yt-dlp.exe');
  if RunHidden(CurlExe,
       '--connect-timeout 15 --max-time 120 -L --fail -o "' + TempFile + '" "' + YtDlpUrl + '"',
       ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0) and FileExists(TempFile) then
  begin
    if FileCopy(TempFile, TargetFile, False) then
    begin
      DownloadedYtDlp := True;
      AddToSystemPath(TargetDir);
    end
    else
      Log('DownloadYtDlp: could not copy yt-dlp.exe into ' + TargetDir);
  end
  else
    Log('DownloadYtDlp: download failed, ResultCode=' + IntToStr(ResultCode));
end;

procedure DownloadNetTools();
var
  ScriptPath, ListFile, Line, Url, PowerShellExe, CurlExe, ScriptArgs: String;
  Lines: TArrayOfString;
  I, ResultCode: Integer;
  NeedNpcap, NeedNmap: Boolean;
begin
  DownloadedNpcap := False;
  DownloadedNmap := False;

  { Check the registry up front so we can skip the PowerShell round-trip
    entirely when both tools are already present, and skip the per-tool
    web lookup inside the script when only one of them is missing -
    resolve_net_tools.ps1 previously always hit npcap.com and nmap.org
    even on a machine that already had both installed. }
  NeedNpcap := not IsNpcapInstalled();
  NeedNmap := not IsNmapInstalled();

  if (not NeedNpcap) and (not NeedNmap) then
  begin
    Log('DownloadNetTools: Npcap and Nmap are both already installed - skipping lookup entirely.');
    Exit;
  end;

  PowerShellExe := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
  CurlExe := ExpandConstant('{sys}\curl.exe');

  if FileExists(PowerShellExe) and FileExists(CurlExe) then
  begin
    ExtractTemporaryFile('resolve_net_tools.ps1');
    ScriptPath := ExpandConstant('{tmp}\resolve_net_tools.ps1');
    ListFile := ExpandConstant('{tmp}\net_tools.txt');

    ScriptArgs := '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '" -OutFile "' + ListFile + '"';
    if not NeedNpcap then
      ScriptArgs := ScriptArgs + ' -SkipNpcap';
    if not NeedNmap then
      ScriptArgs := ScriptArgs + ' -SkipNmap';

    if RunHidden(PowerShellExe, ScriptArgs,
         ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0) then
    begin
      if LoadStringsFromFile(ListFile, Lines) then
      begin
        for I := 0 to GetArrayLength(Lines) - 1 do
        begin
          Line := Lines[I];

          if (Pos('NPCAP_URL=', Line) = 1) then
          begin
            Url := Copy(Line, Length('NPCAP_URL=') + 1, MaxInt);
            if (Url <> '') and (not IsNpcapInstalled()) then
            begin
              if RunHidden(CurlExe,
                   '--connect-timeout 15 --max-time 120 -L --fail -o "' + ExpandConstant('{tmp}\npcap-setup.exe') + '" "' + Url + '"',
                   ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0) then
                DownloadedNpcap := True
              else
                Log('Npcap download failed, ResultCode=' + IntToStr(ResultCode));
            end;
          end
          else if (Pos('NMAP_URL=', Line) = 1) then
          begin
            Url := Copy(Line, Length('NMAP_URL=') + 1, MaxInt);
            if (Url <> '') and (not IsNmapInstalled()) then
            begin
              if RunHidden(CurlExe,
                   '--connect-timeout 15 --max-time 120 -L --fail -o "' + ExpandConstant('{tmp}\nmap-setup.exe') + '" "' + Url + '"',
                   ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0) then
                DownloadedNmap := True
              else
                Log('Nmap download failed, ResultCode=' + IntToStr(ResultCode));
            end;
          end;
        end;
      end
      else
        Log('DownloadNetTools: could not read ' + ListFile);
    end
    else
      Log('resolve_net_tools.ps1 failed, ResultCode=' + IntToStr(ResultCode));
  end
  else
    Log('DownloadNetTools: powershell.exe or curl.exe not found, skipping Npcap/Nmap auto-download.');
end;

// Inno Setup has no built-in way to set a shortcut's "Run as
// administrator" flag (the one on a .lnk's Properties > Advanced
// dialog), so this pokes it directly: byte offset 21 of a .lnk file
// holds a bitfield Explorer checks before launching, and bit 0x20
// there is the elevation flag - undocumented by Microsoft but stable
// since Vista, and the standard workaround for this in Inno Setup.
procedure SetShortcutRunAsAdmin(const FileName: String);
var
  Buffer: AnsiString;
begin
  if not FileExists(FileName) then
    Exit;
  if not LoadStringFromFile(FileName, Buffer) then
  begin
    Log('SetShortcutRunAsAdmin: could not read ' + FileName);
    Exit;
  end;
  if Length(Buffer) > 21 then
  begin
    Buffer[22] := Chr(Ord(Buffer[22]) or $20);
    if not SaveStringToFile(FileName, Buffer, False) then
      Log('SetShortcutRunAsAdmin: could not write ' + FileName);
  end;
end;

// Only touches shortcuts that actually got created - desktopicon and
// startupicon are each gated behind their own task, so a shortcut
// might not exist even though "runasadmin" was checked.
procedure ApplyRunAsAdminToShortcuts();
begin
  if not IsTaskSelected('runasadmin') then
    Exit;
  SetShortcutRunAsAdmin(ExpandConstant('{group}\{#MyAppNamePS}.lnk'));
  SetShortcutRunAsAdmin(ExpandConstant('{autodesktop}\{#MyAppNamePS}.lnk'));
  SetShortcutRunAsAdmin(ExpandConstant('{userstartup}\{#MyAppNamePS}.lnk'));
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = wpSelectDir then
  begin
    if IsTaskSelected('portablemode') then
    begin
      if WizardDirValue = ExpandConstant('{autopf}\{#MyAppNamePS}') then
        WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\ZsMultiTool');
      Log('Portable-style installation selected. Install directory: ' + WizardDirValue);
    end;
  end;
end;


function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  NeedsRestart := False;

  Log('=== Preparing dependencies ===');

  { Detect/download Npcap and Nmap only when missing. }
  DownloadNetTools();

  { Install downloaded Npcap before continuing. The free Npcap installer
    may display its own setup UI; Nmap is installed silently below. }
  if DownloadedNpcap then
  begin
    Log('Installing downloaded Npcap...');
    if not Exec(ExpandConstant('{tmp}\npcap-setup.exe'), '',
         ExpandConstant('{tmp}'), SW_SHOWNORMAL, ewWaitUntilTerminated,
         ResultCode) then
    begin
      Result := 'Could not start the Npcap installer.';
      Exit;
    end;
    Log('Npcap installer finished with exit code ' + IntToStr(ResultCode) + '.');
  end;

  { Install downloaded Nmap silently. }
  if DownloadedNmap then
  begin
    Log('Installing downloaded Nmap silently...');
    if not Exec(ExpandConstant('{tmp}\nmap-setup.exe'), '/S',
         ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated,
         ResultCode) then
    begin
      Result := 'Could not start the Nmap installer.';
      Exit;
    end;
    Log('Nmap installer finished with exit code ' + IntToStr(ResultCode) + '.');
    RemoveNmapDesktopShortcuts();
  end;

  { Detect/download FFmpeg and yt-dlp. }
  DownloadYtDlp();
  DownloadFfmpeg();

  Log('=== Dependency preparation complete ===');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    ApplyRunAsAdminToShortcuts();
    { Even when Nmap was already present, a previous silent install may
      have left Zenmap on the desktop. Clean it up on every upgrade. }
    RemoveNmapDesktopShortcuts();
  end;
end;