; AgentFloat — Inno Setup 安装脚本
; 编译: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss

#define MyAppName "AgentFloat"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AgentFloat"
#define MyAppExeName "AgentFloat.exe"
#define MyAppURL "https://github.com/GinyvaXu/AgentFloat"

[Setup]
AppId={{AF12A0B1-EE67-491B-B6AF-9C1E4D5F8A02}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\AgentFloat
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=.
OutputBaseFilename=AgentFloat_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=120
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\assets\agent_float_icon.ico
PrivilegesRequired=lowest
SetupIconFile=assets\agent_float_icon.ico
; 安装程序窗口标题
SetupMutex=AgentFloatSetup

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"
Name: "startup"; Description: "开机自动启动 AgentFloat"; GroupDescription: "启动选项:"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\agent_float_icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\agent_float_icon.png"; DestDir: "{app}\assets"; Flags: ignoreversion

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
    Description: "启动 Claude Code 浮窗"; \
    Flags: nowait postinstall skipifsilent unchecked

[UninstallRun]
Filename: "taskkill"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden

[Code]
// 安装完成后的自定义消息
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // 安装完成后自动清理
  end;
end;
