; AgentFloat — Inno Setup 安装脚本（按用户级安装，支持静默自动更新）
; 编译: "C:\Users\zhenl\InnoSetup6\ISCC.exe" /DMyAppVersion=1.3.0 setup.iss

#define MyAppName "AgentFloat"
#ifndef MyAppVersion
#define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "AgentFloat"
#define MyAppExeName "AgentFloat.exe"
#define MyAppURL "https://github.com/GinyvaXu/AgentFloat"

[Setup]
AppId={{AF11F0A1-F6A5-4901-BCDE-2A9E5C7D8B01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
SetupIconFile=assets\agent_float_icon.ico
; 按用户级安装到本地 AppData：静默自动更新永不弹 UAC
DefaultDirName={localappdata}\AgentFloat
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer
OutputBaseFilename=AgentFloat-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=120
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\assets\agent_float_icon.ico
ChangesAssociations=no
SetupMutex=AgentFloatSetup

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"; Flags: unchecked
Name: "startup"; Description: "开机自动启动 AgentFloat"; GroupDescription: "启动选项:"

[Files]
Source: "dist\AgentFloat.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\agent_float_icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\agent_float_icon.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "VERSION"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\assets\agent_float_icon.ico"; \
    Comment: "AI Agent 浮窗助手"
Name: "{group}\卸载 AgentFloat"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\assets\agent_float_icon.ico"; \
    Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    IconFilename: "{app}\assets\agent_float_icon.ico"; \
    Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "启动 AgentFloat"; \
    Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden

