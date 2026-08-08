import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
PyInstaller 正式版构建 — 确认稳定后执行
- 无控制台窗口 (--windowed)
- 自动归档旧版到 versions/v<旧版本>/dist/
"""
import PyInstaller.__main__
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

from build_utils import archive_old_builds, read_version, write_build_version

CURRENT_VERSION = read_version()
print(f"[构建] 当前版本: v{CURRENT_VERSION}")
print("[构建] 归档旧版 release exe...")
archive_old_builds(CURRENT_VERSION)

script = os.path.join(SCRIPT_DIR, "agent_float.py")
icon   = os.path.join(SCRIPT_DIR, "assets", "agent_float_icon.ico")
res    = os.path.join(SCRIPT_DIR, "assets")
add_data = f"{res}{os.pathsep}assets"

EXCLUDES = [
    "QtWebEngine", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel",
    "QtMultimedia", "QtMultimediaWidgets",
    "QtSql", "QtXml", "QtTest",
    "QtNetwork", "Qt3D", "Qt3DCore", "Qt3DRender", "Qt3DInput", "Qt3DLogic",
    "QtCharts", "QtDataVisualization",
    "QtSensors", "QtSerialPort", "QtPositioning",
    "QtPrintSupport", "QtQuick", "QtQml", "QtQmlModels", "QtQuickWidgets",
    "QtSvg", "QtSvgWidgets", "QtBluetooth", "QtNfc",
    "QtTextToSpeech", "QtSpeech", "QtLocation",
]

HIDDEN_IMPORTS = [
    "api_monitor_config", "api_fetcher", "api_monitor_worker",
    "api_balance_badge", "api_monitor_settings", "updater",
    "af_theme", "agent_registry", "radial_menu",
    "skills_scanner", "skills_panel", "agent_manager",
    "local_ai_service",
]

args = [
    script,
    "--onefile",
    "--windowed",
    "--name", "AgentFloat",
    f"--icon={icon}",
    "--add-data", add_data,
    "--distpath", os.path.join(SCRIPT_DIR, "dist"),
    "--workpath", os.path.join(SCRIPT_DIR, "build"),
    "--specpath", os.path.join(SCRIPT_DIR, "build"),
    "--noconfirm",
    *[f"--hidden-import={m}" for m in HIDDEN_IMPORTS],
    *[f"--exclude-module={m}" for m in EXCLUDES],
]

print(f"[构建] 开始构建正式版 (v{CURRENT_VERSION}, windowed) ...")
PyInstaller.__main__.run(args)

write_build_version(CURRENT_VERSION)
print(f"\n[完成] dist/AgentFloat.exe (v{CURRENT_VERSION})")
