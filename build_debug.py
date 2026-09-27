import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
PyInstaller 调试构建 — 开发期默认构建目标
- 带控制台窗口，可看到错误输出
- 自动归档旧版到 versions/v<旧版本>/dist/
"""
import PyInstaller.__main__
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 自动归档旧版
from build_utils import (
    archive_old_builds, check_ascii_build_path, prune_onedir, read_version,
    write_build_version,
)

CURRENT_VERSION = read_version()
if not check_ascii_build_path():
    sys.exit(1)
ONE_FILE = "--onefile" in sys.argv     # 默认 onedir（启动更快）；--onefile 出单文件便携版
MODE_FLAG = "--onefile" if ONE_FILE else "--onedir"
print(f"[构建] 当前版本: v{CURRENT_VERSION}（模式: {'onefile' if ONE_FILE else 'onedir'}）")
print("[构建] 归档旧版 debug 产物...")
archive_old_builds(CURRENT_VERSION)

script = os.path.join(SCRIPT_DIR, "agent_float.py")
icon   = os.path.join(SCRIPT_DIR, "assets", "agent_float_icon.ico")
res    = os.path.join(SCRIPT_DIR, "assets")
web_dir = os.path.join(SCRIPT_DIR, "web")
add_data = [
    f"{res}{os.pathsep}assets",
    f"{os.path.join(SCRIPT_DIR, 'VERSION')}{os.pathsep}.",
    f"{web_dir}{os.pathsep}web",
]

EXCLUDES = [
    "QtWebEngine", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel",
    "QtMultimedia", "QtMultimediaWidgets",
    "QtSql", "QtXml", "QtTest", "QtNetwork",
    "Qt3D", "QtCharts", "QtDataVisualization",
    "QtSensors", "QtSerialPort", "QtPositioning",
    "QtPrintSupport", "QtQuick", "QtQml", "QtQuickWidgets",
    "QtSvg", "QtSvgWidgets", "QtBluetooth", "QtNfc",
    "QtTextToSpeech", "QtSpeech", "QtLocation",
    "matplotlib", "numpy", "pandas", "scipy", "streamlit",
    "sklearn", "PIL", "IPython", "jupyter", "notebook",
    # P3：跨平台 WebView 后端（Windows 仅用 edgechromium）+ 未用 Qt 组件
    "webview.platforms.android", "webview.platforms.gtk",
    "webview.platforms.qt", "webview.platforms.cocoa",
    "webview.platforms.cef",
    "QtWebSockets", "QtOpenGL", "QtOpenGLWidgets",
    "QtHelp", "QtDesigner", "QtUiTools",
    # tkinter：AgentFloat 使用 Qt，不依赖 tkinter；排除可避免 PyInstaller
    # 的 pyi_rth__tkinter 运行时钩子因 Tk 数据目录不完整而在启动时崩溃
    "tkinter", "_tkinter", "Tkinter", "tcl", "tk",
]

HIDDEN_IMPORTS = [
    # AgentFloat 包内（src 布局）动态/延迟导入兜底；PyInstaller 静态分析已覆盖大部分
    "agentfloat.app",
    "agentfloat.ui.floatball",
    "agentfloat.webshell.window",      # multiprocessing 子进程目标
    "agentfloat.webshell.server",
    "agentfloat.services.dsh",
    "agentfloat.services.installer",   # Web API 延迟导入
    "agentfloat.services.update.updater",
    "agentfloat.services.skills.ai_service",
    # 第三方动态导入
    "fastapi", "uvicorn", "pydantic", "webview", "clr",
]

# P3 裁剪：应用未使用的重量级依赖（onedir/onefile 均生效）
for _mod in ("sqlite3", "cryptography", "setuptools", "pkg_resources"):
    EXCLUDES.append(_mod)

args = [
    script,
    "--paths", os.path.join(SCRIPT_DIR, "src"),
    MODE_FLAG,
    "--console",
    "--name", "AgentFloat_debug",
    f"--icon={icon}",
    *[f"--add-data={a}" for a in add_data],
    "--distpath", os.path.join(SCRIPT_DIR, "dist"),
    "--workpath", os.path.join(SCRIPT_DIR, "build"),
    "--specpath", os.path.join(SCRIPT_DIR, "build"),
    "--noconfirm",
    *[f"--hidden-import={m}" for m in HIDDEN_IMPORTS],
    "--collect-all", "uvicorn",
    "--collect-all", "fastapi",
    *[f"--exclude-module={m}" for m in EXCLUDES],
]

print(f"[构建] 开始构建 DEBUG 版 (v{CURRENT_VERSION}, console) ...")
PyInstaller.__main__.run(args)

# P3：onedir 安全裁剪（未使用的 Qt 组件/插件）
if not ONE_FILE:
    prune_onedir(os.path.join(SCRIPT_DIR, "dist", "AgentFloat_debug"))

# 写入构建版本标记
write_build_version(CURRENT_VERSION)
if ONE_FILE:
    print(f"\n[完成] dist/AgentFloat_debug.exe (v{CURRENT_VERSION}, onefile)")
else:
    print(f"\n[完成] dist/AgentFloat_debug/AgentFloat_debug.exe (v{CURRENT_VERSION}, onedir)")
