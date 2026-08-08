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
from build_utils import archive_old_builds, read_version, write_build_version

CURRENT_VERSION = read_version()
print(f"[构建] 当前版本: v{CURRENT_VERSION}")
print("[构建] 归档旧版 debug exe...")
archive_old_builds(CURRENT_VERSION)

script = os.path.join(SCRIPT_DIR, "agent_float.py")
icon   = os.path.join(SCRIPT_DIR, "assets", "agent_float_icon.ico")
res    = os.path.join(SCRIPT_DIR, "assets")
add_data = f"{res}{os.pathsep}assets"

EXCLUDES = [
    "QtWebEngine", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel",
    "QtMultimedia", "QtMultimediaWidgets",
    "QtSql", "QtXml", "QtTest", "QtNetwork",
    "Qt3D", "QtCharts", "QtDataVisualization",
    "QtSensors", "QtSerialPort", "QtPositioning",
    "QtPrintSupport", "QtQuick", "QtQml", "QtQuickWidgets",
    "QtSvg", "QtSvgWidgets", "QtBluetooth", "QtNfc",
    "QtTextToSpeech", "QtSpeech", "QtLocation",
]

HIDDEN_IMPORTS = [
    "api_monitor_config", "api_fetcher", "api_monitor_worker",
    "api_balance_badge", "api_monitor_settings", "updater",
    "af_theme", "agent_registry", "radial_menu",
    "skills_scanner", "skills_panel", "agent_manager",
]

args = [
    script,
    "--onefile",
    "--console",
    "--name", "AgentFloat_debug",
    f"--icon={icon}",
    "--add-data", add_data,
    "--distpath", os.path.join(SCRIPT_DIR, "dist"),
    "--workpath", os.path.join(SCRIPT_DIR, "build"),
    "--specpath", os.path.join(SCRIPT_DIR, "build"),
    "--noconfirm",
    *[f"--hidden-import={m}" for m in HIDDEN_IMPORTS],
    *[f"--exclude-module={m}" for m in EXCLUDES],
]

print(f"[构建] 开始构建 DEBUG 版 (v{CURRENT_VERSION}, console) ...")
PyInstaller.__main__.run(args)

# 写入构建版本标记
write_build_version(CURRENT_VERSION)
print(f"\n[完成] dist/AgentFloat_debug.exe (v{CURRENT_VERSION})")
