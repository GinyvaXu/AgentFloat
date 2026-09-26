# -*- coding: utf-8 -*-
"""AgentFloat 构建产物冒烟测试

用法:
    python smoke_test.py [exe路径] [--seconds 12] [--no-kill]

行为:
    - 使用隔离的临时 APPDATA（不触碰真实配置/状态）
    - 启动 exe，等待指定秒数，检查进程存活
    - 解析会话日志：无 ERROR/Traceback 视为通过；输出启动耗时（进程启动 → 首条日志）
    - 结束时结束进程树

退出码：0 = 通过，1 = 失败
"""
import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def default_exe():
    onedir = os.path.join(ROOT, "dist", "AgentFloat_debug", "AgentFloat_debug.exe")
    if os.path.isfile(onedir):
        return onedir
    return os.path.join(ROOT, "dist", "AgentFloat_debug.exe")


def prepare_isolated_appdata():
    base = os.path.join(tempfile.gettempdir(), "AgentFloatSmoke", time.strftime("%Y%m%d_%H%M%S"))
    cfg_dir = os.path.join(base, "AgentFloat")
    os.makedirs(cfg_dir, exist_ok=True)
    with io.open(os.path.join(cfg_dir, "config.json"), "w", encoding="utf-8") as f:
        f.write('{"skills": {"auto_translate_new_skills": false}, "check_updates": false}')
    return base, cfg_dir


def scan_errors(cfg_dir):
    bad = []
    for sub in ("logs", "debug_logs"):
        d = os.path.join(cfg_dir, sub)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.endswith(".log") and not name.endswith(".txt"):
                continue
            p = os.path.join(d, name)
            if os.path.isdir(p):
                continue
            try:
                with io.open(p, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if ("[ERROR" in line) or ("Traceback" in line) or ("CRITICAL" in line):
                            bad.append("%s: %s" % (name, line.strip()[:120]))
            except OSError:
                pass
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe", nargs="?", default=None, help="被测 exe 路径（默认 dist 下调试版）")
    ap.add_argument("--seconds", type=int, default=12, help="冒烟运行秒数")
    ap.add_argument("--no-kill", action="store_true", help="结束后不结束进程")
    args = ap.parse_args()

    exe = args.exe or default_exe()
    if not os.path.isfile(exe):
        print("[FAIL] 找不到 exe: %s" % exe)
        return 1
    print("[smoke] exe = %s (%.1f MB)" % (exe, os.path.getsize(exe) / 1024.0 / 1024.0))

    appdata, cfg_dir = prepare_isolated_appdata()
    env = dict(os.environ, APPDATA=appdata)
    t0 = time.time()
    proc = subprocess.Popen([exe], env=env, cwd=os.path.dirname(exe),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log_path = os.path.join(cfg_dir, "logs", "AgentFloat.log")
    first_log_s = None
    try:
        deadline = t0 + args.seconds
        while time.time() < deadline:
            if first_log_s is None and os.path.isfile(log_path) \
                    and os.path.getsize(log_path) > 0:
                first_log_s = time.time() - t0
            time.sleep(0.05)
        alive = proc.poll() is None
        print("[smoke] %.0fs 后进程存活: %s" % (args.seconds, alive))

        if first_log_s is not None:
            print("[smoke] 启动耗时（进程启动→首条日志写入）: %.2fs" % first_log_s)
        else:
            print("[smoke] 未读到日志（可能启动失败）")

        errors = scan_errors(cfg_dir)
        if errors:
            print("[smoke] 发现 %d 条错误记录：" % len(errors))
            for e in errors[:8]:
                print("   ", e)
        else:
            print("[smoke] 日志无 ERROR/Traceback")

        ok = alive and not errors
        print("[smoke] %s" % ("PASS" if ok else "FAIL"))
        return 0 if ok else 1
    finally:
        if not args.no_kill:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True)
            except Exception:
                pass
        try:
            shutil.rmtree(appdata, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
