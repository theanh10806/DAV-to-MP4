#define MyAppName "DAV sang MP4"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Võ Thế Anh"
#define MyAppExeName "DAVtoMP4.exe"

[Setup]
AppId={{A7B6E8C2-57C8-4E91-9B61-74E5D9A7B120}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\DAV sang MP4
DefaultGroupName={#MyAppName}
OutputDir=installer_output
OutputBaseFilename=DAV_sang_MP4_Setup_v12
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
; Use the built-in English message file so compilation also works when Vietnamese.isl is not installed.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng ngoài Desktop"; GroupDescription: "Tùy chọn:"; Flags: unchecked

[Files]
Source: "dist\DAVtoMP4.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "update_config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "app_icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\FFmpeg-LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists(ExpandConstant('{src}\dist\FFmpeg-LICENSE.txt'))

[Icons]
Name: "{group}\DAV sang MP4"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\DAV sang MP4"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Mở DAV sang MP4"; Flags: postinstall nowait skipifsilent
