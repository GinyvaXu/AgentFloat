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
    归档 dist/ 中不属于当前版本的 exe 文件。
    移动到 versions/v<旧版本>/dist/ 下。
    """
    last_ver = read_last_build_version()

    if not os.path.isdir(DIST_DIR):
        return

    for fname in os.listdir(DIST_DIR):
        if not fname.endswith(".exe"):
            continue

        src = os.path.join(DIST_DIR, fname)

        # 确定此 exe 的版本：优先用 last_build_version，fallback 读 VERSION 文件
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