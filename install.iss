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
#define MyAppVersion "4.0.0"
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
; Program Files install needs admin rights. Switch to
; PrivilegesRequired=lowest + DefaultDirName={localappdata}\Programs\{#MyAppName}
; if you'd rather install per-user with no UAC prompt.
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startupicon"; Description: "Launch {#MyAppName} at Windows startup"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "runasadmin"; Description: "Always run {#MyAppName} as administrator (needed for the Network Auditor module's packet capture)"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "npcaptask"; Description: "Download and install Npcap (required for the Network Auditor module's packet capture)"; GroupDescription: "Network Auditor dependencies:"
Name: "nmaptask"; Description: "Download and install Nmap (required for the Network Auditor module)"; GroupDescription: "Network Auditor dependencies:"
Name: "webview2task"; Description: "Install Microsoft Edge WebView2 Runtime if missing (required for Brick Breaker in-app play)"; GroupDescription: "Brick Breaker dependencies:"; Flags: checkedonce

[Files]
; The onefile PyInstaller build - everything (modules/core/pages/assets/
; settings.json) is already bundled inside this single exe.
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; VLC runtime, needed by media_center and music_player (python-vlc loads
; libvlc.dll at runtime - PyInstaller can't bundle this into the exe
; itself). build.bat copies these into dist\ automatically if it finds a
; local VLC install; if dist\libvlc.dll doesn't exist when you compile
; this script, re-run build.bat with VLC installed first.
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
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent shellexec

; Npcap/Nmap: downloaded (if needed) by DownloadNetTools in [Code] above.
; Neither installer's free edition supports a silent switch, so these
; still open their own installer windows - Check: only launches one if
; the download actually succeeded and it wasn't already installed.
Filename: "{tmp}\npcap-setup.exe"; StatusMsg: "Launching the Npcap installer (a few clicks needed - the free edition can't install silently)..."; Flags: postinstall skipifsilent shellexec; Check: ShouldRunNpcapInstaller
Filename: "{tmp}\nmap-setup.exe"; StatusMsg: "Launching the Nmap installer..."; Flags: postinstall skipifsilent shellexec; Check: ShouldRunNmapInstaller
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime (Brick Breaker)..."; Flags: postinstall skipifsilent waituntilterminated; Check: ShouldRunWebView2Installer

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
  DownloadedNpcap, DownloadedNmap, DownloadedWebView2, DownloadedYtDlp: Boolean;

const
  WebView2ClientGuid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2BootstrapperUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
  YtDlpUrl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe';
  FfmpegUrl = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip';

procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel2.Caption :=
    WizardForm.WelcomeLabel2.Caption + #13#10#13#10 +
    'Note: the Network Auditor module needs Npcap and Nmap. If the ' +
    'tasks below are checked, this installer will download the ' +
    'official installers for you and launch them once setup finishes ' +
    '- but neither one''s free edition supports a fully silent install, ' +
    'so you''ll still need to click through each of their installer ' +
    'windows once.' + #13#10#13#10 +
    'Brick Breaker in-app play needs the Microsoft Edge WebView2 Runtime. ' +
    'If that task is checked and WebView2 is missing, the installer will ' +
    'download and install it silently.';
end;

function IsNpcapInstalled(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Npcap') or
            RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Npcap');
end;

function IsNmapInstalled(): Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Nmap') or
            RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Nmap');
end;

function IsWebView2Installed(): Boolean;
begin
  Result :=
    RegKeyExists(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid) or
    RegKeyExists(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid) or
    RegKeyExists(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + WebView2ClientGuid);
end;

function RunHidden(const Exe, Params, WorkDir: String; var ResultCode: Integer): Boolean;
begin
  Result := Exec(Exe, Params, WorkDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// Looks up the current Npcap/Nmap installer URLs (resolve_net_tools.ps1),
// then downloads whichever ones are needed with curl.exe (bundled in
// Windows 10 1803+ / Windows 11). Sets DownloadedNpcap/DownloadedNmap so
// the matching [Run] entries below know whether there's actually
// anything to launch.
procedure DownloadWebView2Bootstrapper();
var
  CurlExe: String;
  ResultCode: Integer;
begin
  if not IsTaskSelected('webview2task') then
    Exit;
  if IsWebView2Installed() then
  begin
    Log('WebView2 runtime already installed.');
    Exit;
  end;

  CurlExe := ExpandConstant('{sys}\curl.exe');
  if not FileExists(CurlExe) then
  begin
    Log('DownloadWebView2: curl.exe not found.');
    Exit;
  end;

  if RunHidden(CurlExe,
       '-L --fail -o "' + ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe') + '" "' + WebView2BootstrapperUrl + '"',
       ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0) then
    DownloadedWebView2 := True
  else
    Log('WebView2 bootstrapper download failed, ResultCode=' + IntToStr(ResultCode));
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
    AddToSystemPath(BinDir);
    Exit;
  end;

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
       '-L --fail -o "' + ZipFile + '" "' + FfmpegUrl + '"',
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
    Exit;

  CurlExe := ExpandConstant('{sys}\curl.exe');
  if not FileExists(CurlExe) then
  begin
    Log('DownloadYtDlp: curl.exe not found, skipping yt-dlp auto-download.');
    Exit;
  end;

  ForceDirectories(TargetDir);
  TempFile := ExpandConstant('{tmp}\yt-dlp.exe');
  if RunHidden(CurlExe,
       '-L --fail -o "' + TempFile + '" "' + YtDlpUrl + '"',
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
  ScriptPath, ListFile, Line, Url, PowerShellExe, CurlExe: String;
  Lines: TArrayOfString;
  I, ResultCode: Integer;
begin
  DownloadedNpcap := False;
  DownloadedNmap := False;
  DownloadedWebView2 := False;

  if IsTaskSelected('npcaptask') or IsTaskSelected('nmaptask') then
  begin
    PowerShellExe := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    CurlExe := ExpandConstant('{sys}\curl.exe');

    if FileExists(PowerShellExe) and FileExists(CurlExe) then
    begin
      ExtractTemporaryFile('resolve_net_tools.ps1');
      ScriptPath := ExpandConstant('{tmp}\resolve_net_tools.ps1');
      ListFile := ExpandConstant('{tmp}\net_tools.txt');

      if RunHidden(PowerShellExe,
           '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '" -OutFile "' + ListFile + '"',
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
              if (Url <> '') and IsTaskSelected('npcaptask') and (not IsNpcapInstalled()) then
              begin
                if RunHidden(CurlExe,
                     '-L --fail -o "' + ExpandConstant('{tmp}\npcap-setup.exe') + '" "' + Url + '"',
                     ExpandConstant('{tmp}'), ResultCode) and (ResultCode = 0) then
                  DownloadedNpcap := True
                else
                  Log('Npcap download failed, ResultCode=' + IntToStr(ResultCode));
              end;
            end
            else if (Pos('NMAP_URL=', Line) = 1) then
            begin
              Url := Copy(Line, Length('NMAP_URL=') + 1, MaxInt);
              if (Url <> '') and IsTaskSelected('nmaptask') and (not IsNmapInstalled()) then
              begin
                if RunHidden(CurlExe,
                     '-L --fail -o "' + ExpandConstant('{tmp}\nmap-setup.exe') + '" "' + Url + '"',
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

  DownloadWebView2Bootstrapper();
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

function ShouldRunNpcapInstaller(): Boolean;
begin
  Result := DownloadedNpcap;
end;

function ShouldRunNmapInstaller(): Boolean;
begin
  Result := DownloadedNmap;
end;

function ShouldRunWebView2Installer(): Boolean;
begin
  Result := DownloadedWebView2;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    DownloadNetTools();
    DownloadYtDlp();
    DownloadFfmpeg();
    ApplyRunAsAdminToShortcuts();
  end;
end;