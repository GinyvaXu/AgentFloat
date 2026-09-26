"""
构建工具 — 旧版归档 + 版本追踪
每次构建前自动将旧版 exe 归档到 versions/v<旧版本>/dist/
"""
import os
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(SCRIPT_DIR, "dist")
VERSIONS_DIR = os.path.join(SCRIPT_DIR, "versions")
BUILD_VERSION_FILE = os.path.join(DIST_DIR, ".build_version")


# ── P3 onedir 安全裁剪（conda Qt 附带、AgentFloat 未使用的组件）──
PRUNE_TOP_FILES = [
    "Qt5Pdf_conda.dll",            # PDF 组件（应用不使用）
    "Qt5Quick_conda.dll",          # QML 运行时（应用为 Widgets 技术栈）
    "Qt5Qml_conda.dll",
    "Qt5QmlModels_conda.dll",
    "Qt5VirtualKeyboard_conda.dll",
    "Qt5DBus_conda.dll",
    "Qt5WebSockets_conda.dll",
    "Qt5Network_conda.dll",        # 网络全部走 Python 侧
    "Qt5Svg_conda.dll",            # 图标为 png/ico，无 SVG
]
PRUNE_DIRS = [
    os.path.join("PyQt5", "Qt5", "translations"),   # Qt 内置翻译（界面文案为自有文本）
    os.path.join("PyQt5", "Qt5", "qml"),
]
PRUNE_PLUGIN_FILES = [
    os.path.join("platforms", "qdirect2d.dll"),
    os.path.join("platforms", "qminimal.dll"),
    os.path.join("platforms", "qoffscreen.dll"),
    os.path.join("platforms", "qwebgl.dll"),
    os.path.join("platformthemes", "qxdgdesktopportal.dll"),
    os.path.join("generic", "qtuiotouchplugin.dll"),
    os.path.join("platforminputcontexts", "qtvirtualkeyboardplugin.dll"),
    os.path.join("iconengines", "qsvgicon.dll"),
    os.path.join("imageformats", "qwebp.dll"),
    os.path.join("imageformats", "qtiff.dll"),
    os.path.join("imageformats", "qicns.dll"),
    os.path.join("imageformats", "qgif.dll"),      # 保留 qico（托盘图标）/ qjpeg（兜底）
    os.path.join("imageformats", "qsvg.dll"),
    os.path.join("imageformats", "qtga.dll"),
    os.path.join("imageformats", "qwbmp.dll"),
    os.path.join("imageformats", "qpdf.dll"),
]


def prune_onedir(dist_dir):
    """对 onedir 产物做安全裁剪（未使用的 Qt 组件/插件）；返回释放的 MB 数。

    仅删除确证未使用的组件；保守原则：opengl32sw.dll（软件 OpenGL 兜底）与
    ICU（Qt5Core 链接依赖）保留，避免在虚拟机/远程桌面等环境启动失败。
    """
    internal = os.path.join(dist_dir, "_internal")
    base = internal if os.path.isdir(internal) else dist_dir
    plugins = os.path.join(base, "PyQt5", "Qt5", "plugins")

    removed, freed = 0, 0
    targets = [os.path.join(base, name) for name in PRUNE_TOP_FILES]
    targets += [os.path.join(base, rel) for rel in PRUNE_DIRS]
    targets += [os.path.join(plugins, rel) for rel in PRUNE_PLUGIN_FILES]
    for t in targets:
        try:
            if os.path.isdir(t):
                size = sum(os.path.getsize(os.path.join(r, f))
                           for r, _d, fs in os.walk(t) for f in fs)
                shutil.rmtree(t)
            elif os.path.isfile(t):
                size = os.path.getsize(t)
                os.remove(t)
            else:
                continue
            removed += 1
            freed += size
        except OSError:
            pass
    print(f"[裁剪] 移除 {removed} 项未使用组件，释放 {freed / 1024 / 1024:.1f} MB")
    return freed / 1024 / 1024


def read_version():
    """读取当前 VERSION 文件"""
    path = os.path.join(SCRIPT_DIR, "VERSION")
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def read_last_build_version():
    """读取上次构建时的版本号"""
    try:
        with open(BUILD_VERSION_FILE, "r", encoding="utf-8-sig") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def write_build_version(version):
    """写入当前构建版本号"""
    os.makedirs(DIST_DIR, exist_ok=True)
    with open(BUILD_VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(version)


def archive_old_builds(current_version: str):
    """
    归档 dist/ 中不属于当前版本的构建产物到 versions/v<旧版本>/dist/。
    支持单文件 exe 与 onedir 目录（AgentFloat* 目录）。
    """
    last_ver = read_last_build_version()

    if not os.path.isdir(DIST_DIR):
        return

    for fname in os.listdir(DIST_DIR):
        src = os.path.join(DIST_DIR, fname)
        is_dir = os.path.isdir(src)
        if not fname.endswith(".exe") and not (is_dir and fname.startswith("AgentFloat")):
            continue

        # 确定此产物的版本：优先用 last_build_version，fallback 读 VERSION 文件
        archive_ver = last_ver or read_version()
        if archive_ver == current_version:
            continue  # 同版本不归档

        dest_dir = os.path.join(VERSIONS_DIR, f"v{archive_ver}", "dist")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, fname)

        if os.path.exists(dest):
            # 目标已存在，加时间戳
            import time
            ts = time.strftime("%Y%m%d_%H%M%S")
            name, ext = os.path.splitext(fname)
            dest = os.path.join(dest_dir, f"{name}_{ts}{ext}")

        shutil.move(src, dest)
        print(f"[归档] {fname} → versions/v{archive_ver}/dist/{os.path.basename(dest)}")

    # 归档完成后，把 .build_version 也清理掉（下次构建会重新写入）
    if os.path.exists(BUILD_VERSION_FILE) and last_ver != current_version:
        os.remove(BUILD_VERSION_FILE)