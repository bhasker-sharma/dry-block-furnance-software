; Inno Setup script for Dry Block Calibrator.
;
; Compiles dist\DryBlockCalibrator.exe (built by build_exe.bat) into a
; guided installer with a Start Menu shortcut, optional Desktop shortcut,
; and an uninstaller registered in Add/Remove Programs.
;
; Installs per-user, no admin rights required (PrivilegesRequired=lowest) -
; the default location is the current user's own AppData\Local\Programs
; folder, which every normal Windows process can write to. This matters
; because the app itself stores data\settings.json and reports\ right next
; to wherever DryBlockCalibrator.exe is installed (see db/settings_store.py
; and db/report_store.py) - installing into the protected Program Files
; folder would break that for any user without admin rights.

#define MyAppName "Dry Block Calibrator"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "TIPL"
#define MyAppExeName "DryBlockCalibrator.exe"

[Setup]
; Fixed GUID - do not change between releases, or re-running the installer
; will create a second, duplicate install instead of upgrading this one.
AppId={{B4A1F9C2-6E3D-4A7B-9F2E-1D8C5A3B7E60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_dist
OutputBaseFilename=DryBlockCalibrator_Setup
SetupIconFile=asset\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\DryBlockCalibrator.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
