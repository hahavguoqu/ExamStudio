#define AppName "试卷工作室"
#ifndef AppVersion
#define AppVersion "0.1.1"
#endif
#ifndef PayloadDir
#error PayloadDir is required
#endif
#ifndef OutputDir
#error OutputDir is required
#endif

[Setup]
AppId={{1B682B5D-03DB-4586-85DD-B5D0E41CA1A4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=试卷工作室
DefaultDirName={localappdata}\Programs\ShijuanStudio
DefaultGroupName={#AppName}
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
OutputDir={#OutputDir}
OutputBaseFilename=ShijuanStudio-Setup-{#AppVersion}-x64
SetupIconFile=..\app\windows\runner\resources\app_icon.ico
UninstallDisplayIcon={app}\ShijuanStudio.exe
AppMutex=Local\ShijuanStudioDesktop
CloseApplications=no
RestartApplications=no
Uninstallable=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ShijuanStudio.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ShijuanStudio.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\ShijuanStudio.exe"; Description: "启动试卷工作室"; Flags: nowait postinstall skipifsilent
