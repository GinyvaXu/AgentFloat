# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — DeepSeek Harness（dsh）Web UI 启动器

dsh 官方用法（DeepSeek 2026-08 开源，命令名 `dsh`）：
  npx @deepseek-ai/dsh web              # Web UI，默认 http://127.0.0.1:3080
  dsh --profile web                     # 等价于 dsh web

本模块统一以 Web UI 模式启动：
  1. 若 3080 端口已在监听 → 直接打开浏览器（复用已有服务，避免重复进程）
  2. 优先 which("dsh")；否则回退 npx --yes @deepseek-ai/dsh（自动拉取，无需全局安装）
  3. 后台静默启动（CREATE_NO_WINDOW），stdout/stderr 写入 logs/dsh_<ts>.log
  4. 轮询端口就绪（最多 90 秒）→ 自动打开浏览器；超时/退出则弹窗并给出日志路径
"""
import ctypes
import logging
import os
import socket
import subprocess
import threading
import time

try:
    import shutil
except Exception:  # pragma: no cover
    shutil = None

logger = logging.getLogger("AgentFloat.DSH")

DSH_WEB_HOST = "127.0.0.1"
DSH_WEB_PORT = 3080
DSH_WAIT_SECONDS = 90
DSH_START_TIMEOUT = 120  # npx 首次拉取包可能较慢

_proc = None
_proc_lock = threading.Lock()

# 启动状态机（供 UI 加载指示器轮询）：phase = idle/starting/ready/timeout/exited/error
_status = {"phase": "idle", "message": "", "detail": "", "started_at": 0.0}


def _set_status(phase, message, detail="", keep_start=False):
    global _status
    started = _status.get("started_at") if keep_start else time.time()
    _status = {"phase": phase, "message": message, "detail": detail, "started_at": started}


def status():
    """返回当前启动状态（含已等待秒数），供 UI 轮询。"""
    s = dict(_status)
    if s.get("started_at"):
        s["elapsed"] = max(0.0, time.time() - s["started_at"])
    else:
        s["elapsed"] = 0.0
    return s


def dsh_web_url():
    return "http://%s:%d" % (DSH_WEB_HOST, DSH_WEB_PORT)


def is_running():
    """dsh Web 服务是否在运行（端口监听即视为运行）。"""
    return _port_open(DSH_WEB_PORT)


def stop():
    """停止由本模块启动的 dsh 进程（若端口仍被占用，由用户自行处理）。"""
    global _proc
    with _proc_lock:
        p = _proc
        _proc = None
    if p is not None and p.poll() is None:
        try:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        except Exception:
            pass
        return True
    return False


def _port_open(port, host=DSH_WEB_HOST, timeout=0.6):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _open_url(url):
    import webbrowser
    try:
        webbrowser.open(url)
        logger.info("已打开浏览器: %s", url)
    except Exception as e:
        logger.warning("打开浏览器失败: %s", e)


def _warn_box(text, title="AgentFloat — DeepSeek Harness"):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x00000030)  # MB_ICONWARNING|MB_OK
    except Exception:
        logger.error("dsh 提示框失败: %s", text)


def _log_path(config_dir):
    d = os.path.join(config_dir, "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return os.path.join(d, "dsh_%s.log" % time.strftime("%Y%m%d_%H%M%S"))


def _tail(path, limit=600):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            data = f.read()
        return data[-limit:]
    except Exception:
        return ""


def launch_dsh_web(agent, config=None, config_dir=None):
    """以 Web UI 模式启动 DeepSeek Harness（异步，不阻塞调用线程）。

    立即返回，就绪检查 / 打开浏览器 / 超时提示全部放到后台守护线程执行，
    避免在 Qt 主线程（点击浮窗）或 API 线程里长时间阻塞导致程序未响应。
    """
    global _proc
    if config_dir is None:
        import sys
        if getattr(sys, "frozen", False):
            config_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AgentFloat")
        else:
            config_dir = os.path.dirname(os.path.abspath(__file__))

    if _port_open(DSH_WEB_PORT):
        logger.info("dsh web 已在运行，直接打开浏览器")
        _set_status("ready", "DeepSeek Harness 已在运行", "正在打开浏览器…")
        _open_url(dsh_web_url())
        return "reuse"

    with _proc_lock:
        already_starting = _proc is not None and _proc.poll() is None
    if already_starting:
        logger.info("dsh web 正在启动中，跳过重复启动")
        return "starting"

    working_dir = (agent.get("working_directory") or (config or {}).get("working_directory") or "").strip()
    if not working_dir or not os.path.isdir(working_dir):
        working_dir = os.environ.get("USERPROFILE", config_dir)

    # 构造命令：优先 dsh，否则 npx 按需拉取
    dsh_path = shutil.which("dsh") if shutil else None
    if dsh_path:
        cmd = [dsh_path, "web", "--port", str(DSH_WEB_PORT)]
        launch_note = "dsh"
    else:
        npx_path = shutil.which("npx") if shutil else None
        if not npx_path:
            _set_status("error", "缺少运行环境", "未检测到 dsh / Node.js（npx），请先安装 Node.js")
            _warn_box(
                "未检测到 DeepSeek Harness（dsh）或 Node.js（npx）。\n\n"
                "请先安装 Node.js（https://nodejs.org），然后在终端执行：\n"
                "  npm install -g @deepseek-ai/dsh\n\n"
                "或直接运行：\n"
                "  npx @deepseek-ai/dsh web\n\n"
                "安装完成后重新点击浮窗即可启动。"
            )
            return "missing"
        cmd = [npx_path, "--yes", "@deepseek-ai/dsh", "web", "--port", str(DSH_WEB_PORT)]
        launch_note = "npx @deepseek-ai/dsh"

    logf_path = _log_path(config_dir)
    try:
        logf = open(logf_path, "w", encoding="utf-8")
    except OSError as e:
        logger.error("dsh 日志文件创建失败: %s", e)
        logf = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=working_dir,
            stdin=subprocess.DEVNULL,
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as e:
        if logf is not None:
            try:
                logf.close()
            except Exception:
                pass
        _set_status("error", "启动失败", "无法启动 dsh 进程：%s" % e)
        _warn_box("启动 DeepSeek Harness 失败：\n%s" % e)
        return "error"
    with _proc_lock:
        _proc = proc
    logger.info("dsh web 启动中 pid=%s 方式=%s 日志=%s", proc.pid, launch_note, logf_path)
    _set_status("starting", "正在启动 DeepSeek Harness", "正在拉取并启动 dsh…（首次使用需下载依赖，可能需要几分钟）")

    def _close_log():
        nonlocal logf
        if logf is not None:
            try:
                logf.close()
            except Exception:
                pass
            logf = None

    def _wait_ready():
        """后台线程：轮询端口就绪 → 打开浏览器；超时/退出 → 弹窗提示日志路径。"""
        deadline = time.time() + DSH_START_TIMEOUT
        while time.time() < deadline:
            if _port_open(DSH_WEB_PORT):
                logger.info("dsh web 已就绪，打开浏览器 %s", dsh_web_url())
                _set_status("ready", "DeepSeek Harness 已就绪", "正在打开浏览器…", keep_start=True)
                _open_url(dsh_web_url())
                _close_log()
                return
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        _close_log()
        tail = _tail(logf_path)
        if _port_open(DSH_WEB_PORT):
            _open_url(dsh_web_url())
            return
        if proc.poll() is not None:
            _set_status("exited", "启动进程已退出", (tail or "（无输出，请检查日志）")[:160], keep_start=True)
        else:
            _set_status("timeout", "DeepSeek Harness 启动超时", (tail or "（无输出，请检查网络与 Node 环境）")[:160], keep_start=True)
        logger.warning("dsh web 启动超时或已退出，日志=%s", logf_path)
        _warn_box(
            "DeepSeek Harness 启动超时或已退出。\n\n"
            "日志：%s\n\n%s" % (logf_path, tail or "（无输出，请检查网络与 Node 环境）")
        )

    threading.Thread(target=_wait_ready, daemon=True, name="dsh-wait").start()
    return "starting"
