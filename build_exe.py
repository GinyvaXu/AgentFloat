import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
PyInstaller 正式版构建 — 确认稳定后执行
- 无控制台窗口 (--windowed)
- 自动归档旧版到 versions/v<旧版本>/dist/
"""
import PyInstaller.__main__
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

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
print("[构建] 归档旧版 release 产物...")
archive_old_builds(CURRENT_VERSION)

script = os.path.join(SCRIPT_DIR, "agent_float.py")
icon   = os.path.join(SCRIPT_DIR, "assets", "agent_float_icon.ico")
res    = os.path.join(SCRIPT_DIR, "assets")
web_dir = os.path.join(SCRIPT_DIR, "web")
add_data = [
    f"{res}{os.pathsep}assets",
    f"{os.path.join(SCRIPT_DIR, 'VERSION')}{os.pathsep}.",
    f"{web_dir}{os.pathsep}web",
    f"{os.path.join(SCRIPT_DIR, 'skills')}{os.pathsep}skills",
]

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
# v3.6.0：cryptography 已解禁（账户/密钥保险箱 + 口令保护导出需要），不再裁剪
for _mod in ("sqlite3", "setuptools", "pkg_resources"):
    EXCLUDES.append(_mod)

args = [
    script,
    "--paths", os.path.join(SCRIPT_DIR, "src"),
    MODE_FLAG,
    "--windowed",
    "--name", "AgentFloat",
    f"--icon={icon}",
    *[f"--add-data={a}" for a in add_data],
    "--distpath", os.path.join(SCRIPT_DIR, "dist"),
    "--workpath", os.path.join(SCRIPT_DIR, "build"),
    "--specpath", os.path.join(SCRIPT_DIR, "build"),
    "--noconfirm",
    "--clean",              # PATCH 3.5.3：强制清理缓存，避免 PYZ 复用陈旧模块（曾导致修复未进包）
    *[f"--hidden-import={m}" for m in HIDDEN_IMPORTS],
    "--collect-all", "uvicorn",
    "--collect-all", "fastapi",
    *[f"--exclude-module={m}" for m in EXCLUDES],
]

print(f"[构建] 开始构建正式版 (v{CURRENT_VERSION}, windowed) ...")
PyInstaller.__main__.run(args)

# P3：onedir 安全裁剪（未使用的 Qt 组件/插件）
if not ONE_FILE:
    prune_onedir(os.path.join(SCRIPT_DIR, "dist", "AgentFloat"))

# 附带 af-mcp.exe（独立控制台程序，供 MCP 客户端调用）
if not ONE_FILE:
    mcp_dist = os.path.join(SCRIPT_DIR, "dist", "mcp")
    mcp_args = [
        os.path.join(SCRIPT_DIR, "mcp_entry.py"),
        "--paths", os.path.join(SCRIPT_DIR, "src"),
        "--onefile",
        "--console",
        "--name", "af-mcp",
        "--distpath", mcp_dist,
        "--workpath", os.path.join(SCRIPT_DIR, "build", "mcp"),
        "--specpath", os.path.join(SCRIPT_DIR, "build"),
        "--noconfirm",
        "--clean",
        "--exclude-module=PyQt5",
    ]
    print("[构建] 开始构建 af-mcp ...")
    PyInstaller.__main__.run(mcp_args)
    src_exe = os.path.join(mcp_dist, "af-mcp.exe")
    dst_exe = os.path.join(SCRIPT_DIR, "dist", "AgentFloat", "af-mcp.exe")
    if os.path.isfile(src_exe):
        shutil.copy2(src_exe, dst_exe)
        print("[完成] af-mcp.exe ->", dst_exe)
    else:
        print("[警告] af-mcp.exe 未生成")

write_build_version(CURRENT_VERSION)
if ONE_FILE:
    print(f"\n[完成] dist/AgentFloat.exe (v{CURRENT_VERSION}, onefile)")
else:
    print(f"\n[完成] dist/AgentFloat/AgentFloat.exe (v{CURRENT_VERSION}, onedir)")
