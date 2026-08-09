import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
构建安装包 — Inno Setup 一键打包（参考诺丁汉警长项目）

- 调用 ISCC.exe 编译 setup.iss（per-user 安装、支持静默自动更新）
- 输出 installer/AgentFloat-Setup-<ver>.exe，并复制为 dist/AgentFloat_Setup.exe
- 构建前自动归档旧版 exe 到 versions/v<旧版本>/dist/
"""
import os
import shutil
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))

from build_utils import archive_old_builds, read_version, write_build_version

ISCC = r"C:\Users\zhenl\InnoSetup6\ISCC.exe"


def main():
    version = read_version()
    print(f"[构建] 当前版本: v{version}")

    if not os.path.exists(os.path.join(BASE, "dist", "AgentFloat.exe")):
        print("[ERROR] dist/AgentFloat.exe 不存在，请先运行 build_exe.py")
        return 1

    # 归档旧版 exe（含旧的 Setup.exe）
    print("[构建] 归档旧版 exe...")
    archive_old_builds(version)

    setup_out = os.path.join(BASE, "installer", f"AgentFloat-Setup-{version}.exe")
    if os.path.exists(setup_out):
        os.remove(setup_out)

    print(f"[构建] 运行 Inno Setup: {ISCC}")
    rc = subprocess.call(
        [ISCC, f"/DMyAppVersion={version}", os.path.join(BASE, "setup.iss")],
        cwd=BASE,
    )
    if rc != 0 or not os.path.exists(setup_out):
        print("[ERROR] Inno Setup 编译失败")
        return 1

    dst = os.path.join(BASE, "dist", "AgentFloat_Setup.exe")
    shutil.copy2(setup_out, dst)
    write_build_version(version)
    print(f"[完成] dist/AgentFloat_Setup.exe (v{version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
