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
#define MyAppVersion "3.0.0"
#define MyAppPublisher "Z"
#define MyAppExeName "Z's Multi Tool.exe"
#define MyAppIcon "assets\icon.ico"

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

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Removes the exe/shortcuts installed above. Deliberately NOT touching
; %APPDATA%\ZsMultiTool here - that's where the Security Vault's
; master.key/vault.json, save-manager backups, and notes live, and
; silently wiping that on every uninstall would be a good way to lose
; someone's vault. Uncomment below if you ever want a "delete all my
; data" style uninstall instead:
; Type: filesandordirs; Name: "{userappdata}\ZsMultiTool"

[Code]
procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel2.Caption :=
    WizardForm.WelcomeLabel2.Caption + #13#10#13#10 +
    'Note: the Network Auditor module needs Npcap + Nmap installed ' +
    'separately. This installer does not bundle those - see the app''s ' +
    'Readme for links.';
end;
