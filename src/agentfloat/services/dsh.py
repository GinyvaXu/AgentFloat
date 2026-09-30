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
from agentfloat.core.paths import config_dir as _app_config_dir

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


# ── web profile 插件链接缺失的自动修复 ──────────────
_PLUGIN_MISSING_MARKERS = (
    "ERR_MODULE_NOT_FOUND",
    "plugin tree failed to load",
    "failed to import loader entry",
    "Cannot find package",
)


def _is_plugin_missing_error(tail):
    """判断 dsh 日志是否为 web profile 插件链接缺失错误。"""
    return any(m in (tail or "") for m in _PLUGIN_MISSING_MARKERS)


def _dsh_install_anchor():
    """定位 dsh 安装的 package.json（全局 npm 安装路径）。"""
    for candidate in (
        os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "@deepseek-ai", "dsh", "package.json"),
        os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "dsh", "package.json"),
    ):
        if os.path.isfile(candidate):
            return candidate
    # 兜底：从 dsh 命令解析
    p = shutil.which("dsh") if shutil else None
    if p:
        base = os.path.dirname(os.path.dirname(p)) if p.lower().endswith((".ps1", ".cmd")) else os.path.dirname(p)
        for cand in (
            os.path.join(base, "node_modules", "@deepseek-ai", "dsh", "package.json"),
            os.path.join(base, "@deepseek-ai", "dsh", "package.json"),
        ):
            if os.path.isfile(cand):
                return cand
    return None


def _repair_web_profile_links(anchor):
    """调用 dsh 的 healProfilesModuleFallback 重建 $DSH_HOME/profiles/node_modules 链接。

    返回 (ok, message)。healProfiles 是 dsh-app-boot 的导出函数，BFS 遍历 dsh 安装
    的依赖闭包，为每个包在 profiles/node_modules 下建 junction 链接，使 profile
    无需 pnpm 即可解析所有 in-box 插件。幂等：已有链接保留。
    """
    try:
        import subprocess
        # dsh-app-boot 是 ESM 模块，用 Node 执行 healProfilesModuleFallback 最可靠
        boot_index = os.path.join(
            os.path.dirname(anchor), "node_modules", "@deepseek-ai", "dsh-app-boot", "lib", "index.js"
        )
        if not os.path.isfile(boot_index):
            return False, "未找到 dsh-app-boot: %s" % boot_index
        node = shutil.which("node") if shutil else None
        if not node:
            return False, "未检测到 Node.js"
        script = (
            "import { healProfilesModuleFallback } from %r;"
            "healProfilesModuleFallback(%r);"
            % ("file:///" + boot_index.replace("\\", "/"), anchor.replace("\\", "/"))
        )
        r = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True, text=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r.returncode != 0:
            logger.error("healProfiles 执行失败: %s", (r.stderr or "")[-300:])
            return False, "执行失败: %s" % ((r.stderr or "")[-200:])
        return True, "已重建插件链接"
    except Exception as e:  # noqa: BLE001
        logger.error("重建 dsh profile 插件链接失败: %s", e)
        return False, "重建失败: %s" % e


def _repair_and_retry(agent, config, config_dir, logf_path):
    """重建插件链接后重启 dsh；仍失败则弹窗。"""
    _set_status("starting", "正在修复 DeepSeek Harness", "检测到插件缺失，正在重建链接…")
    logger.info("dsh 插件缺失，尝试自动修复（重建 profiles/node_modules 链接）")
    anchor = _dsh_install_anchor()
    ok, msg = _repair_web_profile_links(anchor) if anchor else (False, "未定位 dsh 安装")
    if not ok:
        _set_status("error", "修复失败", msg, keep_start=True)
        _warn_box("DeepSeek Harness 插件修复失败：\n%s\n\n请尝试重新安装 DSH。" % msg)
        return
    logger.info("dsh 插件链接已重建，重新启动")
    if _port_open(DSH_WEB_PORT):
        _set_status("ready", "DeepSeek Harness 已就绪", "正在打开浏览器…", keep_start=True)
        _open_url(dsh_web_url())
        return
    # 启动新进程（复用命令构造逻辑：dsh / npx）
    dsh_path = shutil.which("dsh") if shutil else None
    if dsh_path:
        cmd = [dsh_path, "web", "--port", str(DSH_WEB_PORT)]
        note = "dsh"
    else:
        npx_path = shutil.which("npx") if shutil else None
        if not npx_path:
            _set_status("error", "缺少运行环境", "未检测到 dsh / Node.js（npx）", keep_start=True)
            return
        cmd = [npx_path, "--yes", "@deepseek-ai/dsh", "web", "--port", str(DSH_WEB_PORT)]
        note = "npx @deepseek-ai/dsh"
    working_dir = (agent or {}).get("working_directory") or (config or {}).get("working_directory") or ""
    if not working_dir or not os.path.isdir(working_dir):
        working_dir = os.environ.get("USERPROFILE", config_dir)
    _start_dsh_process(cmd, note, working_dir, config_dir, repair_retry=True,
                       repair_ctx=(agent, config))


def launch_dsh_web(agent, config=None, config_dir=None):
    """以 Web UI 模式启动 DeepSeek Harness（异步，不阻塞调用线程）。

    立即返回，就绪检查 / 打开浏览器 / 超时提示全部放到后台守护线程执行，
    避免在 Qt 主线程（点击浮窗）或 API 线程里长时间阻塞导致程序未响应。
    """
    if config_dir is None:
        config_dir = _app_config_dir()

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

    return _start_dsh_process(cmd, launch_note, working_dir, config_dir)


def _start_dsh_process(cmd, launch_note, working_dir, config_dir, repair_retry=False, repair_ctx=None):
    """启动 dsh 进程并开启就绪轮询线程。repair_retry=True 表示自动修复后的重试；
    repair_ctx 为自动修复所需的 (agent, config) 上下文。"""
    global _proc
    agent, config = (repair_ctx if repair_ctx else (None, None))
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
    if repair_retry:
        _set_status("starting", "正在重新启动 DeepSeek Harness", "插件链接已重建，正在启动…")
    else:
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
        """后台线程：轮询端口就绪 → 打开浏览器；超时/退出 → 自动修复并重试，再失败弹窗提示日志路径。"""
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
            # 自动修复：日志含 ERR_MODULE_NOT_FOUND / plugin tree failed to load
            # （web profile 插件链接缺失，dsh 0.1.0-rc 在 Windows 首次运行常见），
            # 重建 $DSH_HOME/profiles/node_modules 链接后重试一次。
            if _is_plugin_missing_error(tail):
                _repair_and_retry(agent, config, config_dir, logf_path)
                return
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
