import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
构建安装包 — 确认正式版后执行
- 将 SetupWizard + AgentFloat.exe + 图标打包为一个 Setup.exe
- 自动归档旧版到 versions/v<旧版本>/dist/
"""
import PyInstaller.__main__
import os, shutil

BASE = os.path.dirname(os.path.abspath(__file__))

from build_utils import archive_old_builds, read_version, write_build_version

CURRENT_VERSION = read_version()
print(f"[构建] 当前版本: v{CURRENT_VERSION}")

# 先归档旧的 setup exe
print("[构建] 归档旧版 setup exe...")
old_setup = os.path.join(BASE, "dist", "AgentFloat_Setup.exe")
if os.path.exists(old_setup):
    archive_old_builds(CURRENT_VERSION)

SETUP_PY = os.path.join(BASE, "installer", "setup_wizard_tk.py")
DIST    = os.path.join(BASE, "dist")
APP_EXE = os.path.join(DIST, "AgentFloat.exe")
ICON    = os.path.join(BASE, "assets", "agent_float_icon.ico")
RES_DIR = os.path.join(BASE, "assets")
OUT_DIR = os.path.join(DIST, "SetupPackage")

# 1. 确保 AgentFloat.exe 存在
if not os.path.exists(APP_EXE):
    print("[ERROR] AgentFloat.exe not found. Run build_exe.py first.")
    exit(1)

# 2. 创建打包目录
os.makedirs(OUT_DIR, exist_ok=True)

# 3. 复制文件到打包目录
setup_py_temp = os.path.join(OUT_DIR, "setup_wizard_tk.py")
shutil.copy2(SETUP_PY, setup_py_temp)
shutil.copy2(APP_EXE, os.path.join(OUT_DIR, "AgentFloat.exe"))
version_file = os.path.join(BASE, "VERSION")
if os.path.exists(version_file):
    shutil.copy2(version_file, os.path.join(OUT_DIR, "VERSION"))
for f in ["agent_float_icon.ico", "agent_float_icon.png"]:
    src = os.path.join(RES_DIR, f)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(OUT_DIR, f))

# 4. PyInstaller 打包 — 嵌入 AgentFloat.exe、VERSION 和图标
add_data = [
    f"{os.path.join(OUT_DIR, 'AgentFloat.exe')}{os.pathsep}.",
    f"{os.path.join(OUT_DIR, 'agent_float_icon.ico')}{os.pathsep}.",
    f"{os.path.join(OUT_DIR, 'agent_float_icon.png')}{os.pathsep}.",
]
if os.path.exists(os.path.join(OUT_DIR, "VERSION")):
    add_data.append(f"{os.path.join(OUT_DIR, 'VERSION')}{os.pathsep}.")

args = [
    setup_py_temp,
    "--onefile",
    "--windowed",
    "--name", "AgentFloat_Setup",
    f"--icon={ICON}",
    "--distpath", OUT_DIR,
    "--workpath", os.path.join(BASE, "build_setup"),
    "--specpath", os.path.join(BASE, "build_setup"),
    "--noconfirm",
    "--hidden-import", "PIL._tkinter_finder",
    *[f"--add-data={a}" for a in add_data],
]

print(f"[构建] 开始构建 Setup 版 (v{CURRENT_VERSION}) ...")
PyInstaller.__main__.run(args)

# 5. 把 Setup.exe 移回 dist/ 根目录
setup_exe = os.path.join(OUT_DIR, "AgentFloat_Setup.exe")
if os.path.exists(setup_exe):
    shutil.move(setup_exe, os.path.join(DIST, "AgentFloat_Setup.exe"))
    print(f"[完成] dist/AgentFloat_Setup.exe (v{CURRENT_VERSION})")

write_build_version(CURRENT_VERSION)
