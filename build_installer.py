# -*- coding: utf-8 -*-
"""AgentFloat — 构建 Windows 安装包（Inno Setup）

用法::

    python build_installer.py            # 版本取根目录 VERSION
    python build_installer.py 3.6.2      # 指定版本

前置：先运行 ``build_exe.py`` 生成 ``dist/AgentFloat``（正式版 onedir）。
输出：``versions/v<版本>/dist/AgentFloat-Setup-<版本>.exe``
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_SRC = os.path.join(ROOT, "dist", "AgentFloat")
ICO_SRC = os.path.join(ROOT, "assets", "agent_float_icon.ico")
WORK_DIR = os.path.join(ROOT, "build", "installer")

ISCC_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]

APP_ID = "{{7F3C2E9A-6B21-4D5E-9A3C-AF6B1D8E4C50}"


def read_version():
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def find_iscc():
    for path in ISCC_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def find_chinese_isl(iscc):
    """Inno 安装目录下若有简体中文语言文件则启用"""
    base = os.path.dirname(iscc)
    candidate = os.path.join(base, "Languages", "ChineseSimplified.isl")
    return candidate if os.path.isfile(candidate) else None


def write_iss(version, out_dir, chinese_isl):
    languages = ['Name: "english"; MessagesFile: "compiler:Default.isl"']
    if chinese_isl:
        languages.append('Name: "chinesesimplified"; MessagesFile: "%s"' % chinese_isl)
    iss = r'''
; AgentFloat 安装脚本（由 build_installer.py 自动生成，请勿手改）
[Setup]
AppId=%(app_id)s
AppName=AgentFloat
AppVersion=%(version)s
AppVerName=AgentFloat %(version)s
AppPublisher=GinyvaXu
AppPublisherURL=https://github.com/GinyvaXu/AgentFloat
AppSupportURL=https://github.com/GinyvaXu/AgentFloat
SetupIconFile=%(ico)s
DefaultDirName={localappdata}\Programs\AgentFloat
DefaultGroupName=AgentFloat
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=%(out_dir)s
OutputBaseFilename=AgentFloat-Setup-%(version)s
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=AgentFloat
UninstallDisplayIcon={app}\AgentFloat.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
%(languages)s

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "%(src)s\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AgentFloat"; Filename: "{app}\AgentFloat.exe"; WorkingDir: "{app}"
Name: "{group}\卸载 AgentFloat"; Filename: "{uninstallexe}"
Name: "{autodesktop}\AgentFloat"; Filename: "{app}\AgentFloat.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AgentFloat.exe"; Description: "立即启动 AgentFloat"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\*.log"
''' % {
        "app_id": APP_ID,
        "version": version,
        "out_dir": out_dir,
        "src": APP_SRC,
        "ico": ICO_SRC,
        "languages": "\n".join(languages),
    }
    os.makedirs(WORK_DIR, exist_ok=True)
    iss_path = os.path.join(WORK_DIR, "AgentFloat.iss")
    with open(iss_path, "w", encoding="utf-8-sig") as f:   # Inno 需要 BOM 才能正确处理中文
        f.write(iss)
    return iss_path


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else read_version()
    if not os.path.isdir(APP_SRC) or not os.path.isfile(os.path.join(APP_SRC, "AgentFloat.exe")):
        print("[安装包] 未找到 dist/AgentFloat/AgentFloat.exe，请先运行 build_exe.py")
        return 1
    iscc = find_iscc()
    if not iscc:
        print("[安装包] 未找到 ISCC.exe（Inno Setup 6）；可 winget install -e --id JRSoftware.InnoSetup")
        return 1
    out_dir = os.path.join(ROOT, "versions", "v" + version, "dist")
    os.makedirs(out_dir, exist_ok=True)
    iss_path = write_iss(version, out_dir, find_chinese_isl(iscc))
    print("[安装包] 版本 v%s" % version)
    print("[安装包] 源目录 %s" % APP_SRC)
    print("[安装包] 输出目录 %s" % out_dir)
    print("[安装包] 使用 %s" % iscc)
    proc = subprocess.run([iscc, "/Qp", iss_path], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        print("   ", line)
    if proc.returncode != 0:
        print("[安装包] 构建失败（exit=%s）" % proc.returncode)
        print((proc.stdout or "")[-2000:])
        return proc.returncode
    out_exe = os.path.join(out_dir, "AgentFloat-Setup-%s.exe" % version)
    if os.path.isfile(out_exe):
        size_mb = os.path.getsize(out_exe) / 1024.0 / 1024.0
        print("[安装包] 完成: %s (%.1f MB)" % (out_exe, size_mb))
    else:
        print("[安装包] 未找到预期输出: %s" % out_exe)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
