# -*- coding: utf-8 -*-
"""AgentFloat — pywebview Web 壳窗口管理（独立子进程承载 + 静默预热）

pywebview 要求 webview.start() 在进程主线程运行，而 AgentFloat 主进程的主线程被
Qt 事件循环（FloatingWidget 悬浮球）占用，无法让出。
因此 Web 壳窗口改由 multiprocessing 子进程承载：子进程的主线程运行 pywebview，
主进程通过 multiprocessing.Queue 下发命令（route/show/close），
通过 multiprocessing.Event 感知窗口关闭，实现窗口复用与聚焦路由。

P2 新增「静默预热」：启动后台静默（隐藏）创建窗口，打开设置/快报时秒开；
预热窗口长时间未使用自动回收（WebView2 常驻约百兆内存）；
用户关闭窗口后空闲一段时间会自动再次预热。均由 `tick()` 驱动（主程序定时调用）。

安全回退：若 pywebview 或 WebView2 运行时不可用，子进程自动改用系统默认浏览器打开。
"""
import json
import logging
import multiprocessing
import threading
import time

logger = logging.getLogger("AgentFloat.WebUI")

PREHEAT_TTL_S = 600        # 预热窗口空闲回收（秒）
REPREHEAT_DELAY_S = 60     # 用户关闭窗口后再预热延迟（秒）

_base_url = "http://127.0.0.1:3087"
_worker = None
_cmd_q = None
_closed_evt = None
_ready_evt = None
_lock = threading.Lock()

# 预热 / 生命周期状态
_pending_kind = None       # None / "preheat" / "open"
_preheated = False         # 本会话已请求过预热
_preheat_disabled = False  # 预热失败或被回收后不再自动预热
_shown = False             # 窗口是否曾对用户显示
_spawn_ts = 0.0
_closed_ts = 0.0


def set_base_url(url):
    global _base_url
    _base_url = (url or _base_url).rstrip("/")


def base_url():
    return _base_url


def _open_browser(url):
    import webbrowser
    try:
        webbrowser.open(url)
    except Exception as e:  # noqa: BLE001
        logger.error("打开浏览器失败: %s", e)


def _drain_commands(w, q):
    """子进程内：监听主进程命令，转发给 pywebview 窗口（线程安全）。"""
    while True:
        try:
            cmd = q.get()
        except Exception:  # noqa: BLE001
            return
        try:
            c = cmd.get("cmd")
            if c == "route":
                route = str(cmd.get("route", "#/settings"))
                if not route.startswith("#"):
                    route = "#" + route
                w.evaluate_js("window.location.hash = %s" % json.dumps(route))
            elif c == "show":
                w.show()
                w.restore()
            elif c == "close":
                w.destroy()
                return
        except Exception:  # noqa: BLE001
            pass


def _worker_main(url, route, width, height, cmd_q, closed_evt, ready_evt, hidden=False):
    """子进程主线程：创建并运行 pywebview 窗口。"""
    try:
        import webview
    except Exception as e:  # noqa: BLE001
        logger.warning("pywebview 不可用，改用系统浏览器打开: %s", e)
        _open_browser(url)
        return
    try:
        w = webview.create_window(
            "AgentFloat", url, width=width, height=height, min_size=(880, 620),
            hidden=bool(hidden),
        )
    except TypeError:
        # 旧版 pywebview 不支持 hidden 参数：仅影响预热（放弃），不影响正常打开
        logger.info("当前 pywebview 不支持隐藏创建，跳过预热")
        return
    except Exception as e:  # noqa: BLE001
        logger.warning("创建 Web 窗口失败，改用系统浏览器打开: %s", e)
        _open_browser(url)
        return
    try:
        w.events.closed += (lambda: closed_evt.set())
    except Exception:  # noqa: BLE001
        pass
    threading.Thread(
        target=_drain_commands, args=(w, cmd_q), daemon=True, name="webui-cmd"
    ).start()
    try:
        ready_evt.set()  # 窗口已创建，通知主进程可以隐藏加载指示
    except Exception:
        pass
    try:
        webview.start(gui="edgechromium", debug=False)
    except Exception as e:  # noqa: BLE001
        logger.error("webview.start 失败: %s", e)
        _open_browser(url)
    finally:
        try:
            closed_evt.set()
        except Exception:  # noqa: BLE001
            pass


def is_ready():
    """Web 壳窗口是否已就绪（子进程已创建窗口）"""
    return _ready_evt is not None and _ready_evt.is_set()


def _alive_locked():
    w = _worker
    return (w is not None and w.is_alive()
            and (_closed_evt is None or not _closed_evt.is_set()))


def has_pending():
    """是否有「用户主动打开」但尚未就绪的 Web 壳窗口（用于加载指示）"""
    with _lock:
        w = _worker
        kind = _pending_kind
    return w is not None and w.is_alive() and kind == "open" and not is_ready()


def _spawn(route, width, height, hidden, kind):
    global _worker, _cmd_q, _closed_evt, _ready_evt, _pending_kind, _spawn_ts
    _pending_kind = kind
    _spawn_ts = time.time()
    _cmd_q = multiprocessing.Queue()
    _closed_evt = multiprocessing.Event()
    _ready_evt = multiprocessing.Event()
    url = "%s/%s" % (_base_url, route)
    _worker = multiprocessing.Process(
        target=_worker_main,
        args=(url, route, width, height, _cmd_q, _closed_evt, _ready_evt, hidden),
        name="AgentFloatWebShell",
        daemon=True,
    )
    try:
        _worker.start()
    except Exception as e:  # noqa: BLE001
        logger.error("启动 Web 壳子进程失败，改用系统浏览器打开: %s", e)
        _open_browser(url)


def open_window(route="#/settings", title="AgentFloat", width=1120, height=780):
    """打开（或聚焦并路由到）Web 壳窗口。route 形如 '#/settings' / '#/api' / '#/news'。

    窗口存在时：复用并聚焦，同时通过 JS 切换 hash 路由；
    窗口不存在或已关闭：启动一个新的子进程承载 pywebview。
    """
    if not route.startswith("#"):
        route = "#" + route
    global _pending_kind, _shown
    with _lock:
        alive = _alive_locked()
        if alive and _cmd_q is not None:
            _shown = True
            if not is_ready():
                _pending_kind = "open"      # 仍在启动 → 显示加载指示
            try:
                _cmd_q.put({"cmd": "route", "route": route})
                _cmd_q.put({"cmd": "show"})
            except Exception:  # noqa: BLE001
                pass
            return True
        _shown = True
    _spawn(route, width, height, hidden=False, kind="open")
    return True


def preheat():
    """静默预热：隐藏创建窗口，打开设置/快报时秒开（失败静默降级）"""
    global _preheated
    with _lock:
        if _preheated or _preheat_disabled or _alive_locked():
            return
        _preheated = True
    logger.info("Web 壳静默预热中（打开设置/快报将秒开）…")
    _spawn("#/settings", 1120, 780, hidden=True, kind="preheat")


def tick():
    """主程序定时调用：预热窗口空闲回收 + 关闭后再预热 + 僵死状态清理"""
    global _worker, _pending_kind, _shown, _preheated, _preheat_disabled, _closed_ts
    now = time.time()
    with _lock:
        alive = _alive_locked()
        kind, shown, ts = _pending_kind, _shown, _spawn_ts
        zombie = _worker is not None and not alive
        if zombie:
            _worker = None
            _pending_kind = None
            _shown = False
            if shown:
                _closed_ts = now           # 用户用过的窗口被关闭 → 稍后再预热
            else:
                _preheat_disabled = True   # 预热自身失败/被回收 → 不再自动预热
                _preheated = False
        closed_ts = _closed_ts
    if alive:
        if kind == "preheat" and not shown and now - ts > PREHEAT_TTL_S:
            logger.info("Web 壳预热 %d 秒未被使用，回收释放内存", PREHEAT_TTL_S)
            _preheat_disabled = True
            shutdown()
        return
    if (not _preheat_disabled) and (not _preheated) and closed_ts \
            and now - closed_ts > REPREHEAT_DELAY_S:
        preheat()


def shutdown():
    """尽力关闭 Web 壳窗口（守护子进程随主进程结束）"""
    global _worker, _cmd_q, _pending_kind, _shown
    with _lock:
        w = _worker
        q = _cmd_q
    if w is not None and w.is_alive() and q is not None:
        try:
            q.put({"cmd": "close"})
        except Exception:  # noqa: BLE001
            pass
        try:
            w.join(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass
        if w.is_alive():
            try:
                w.terminate()
            except Exception:  # noqa: BLE001
                pass
    with _lock:
        _worker = None
        _cmd_q = None
        _pending_kind = None
        _shown = False
