# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — pywebview Web 壳窗口管理（独立子进程承载）

pywebview 要求 webview.start() 在进程主线程运行，而 AgentFloat 主进程的主线程被
Qt 事件循环（FloatingWidget 悬浮球）占用，无法让出。
因此 Web 壳窗口改由 multiprocessing 子进程承载：子进程的主线程运行 pywebview，
主进程通过 multiprocessing.Queue 下发命令（route/show/close），
通过 multiprocessing.Event 感知窗口关闭，实现窗口复用与聚焦路由。

安全回退：若 pywebview 或 WebView2 运行时不可用，子进程自动改用系统默认浏览器打开。
"""
import json
import logging
import multiprocessing
import threading

logger = logging.getLogger("AgentFloat.WebUI")

_base_url = "http://127.0.0.1:3087"
_worker = None
_cmd_q = None
_closed_evt = None
_ready_evt = None
_lock = threading.Lock()


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


def _worker_main(url, route, width, height, cmd_q, closed_evt, ready_evt):
    """子进程主线程：创建并运行 pywebview 窗口。"""
    try:
        import webview
    except Exception as e:  # noqa: BLE001
        logger.warning("pywebview 不可用，改用系统浏览器打开: %s", e)
        _open_browser(url)
        return
    try:
        w = webview.create_window(
            "AgentFloat", url, width=width, height=height, min_size=(880, 620)
        )
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
    """Web 壳窗口是否已就绪（子进程已创建窗口）。"""
    return _ready_evt is not None and _ready_evt.is_set()


def has_pending():
    """是否有正在启动但尚未就绪的 Web 壳窗口（用于加载指示）。"""
    with _lock:
        w = _worker
    return w is not None and w.is_alive() and not is_ready()


def open_window(route="#/settings", title="AgentFloat", width=1120, height=780):
    """打开（或聚焦并路由到）Web 壳窗口。route 形如 '#/settings' / '#/api' / '#/news'。

    窗口存在时：复用并聚焦，同时通过 JS 切换 hash 路由；
    窗口不存在或已关闭：启动一个新的子进程承载 pywebview。
    """
    if not route.startswith("#"):
        route = "#" + route
    url = "%s/%s" % (_base_url, route)
    global _worker, _cmd_q, _closed_evt
    with _lock:
        alive = (
            _worker is not None
            and _worker.is_alive()
            and (_closed_evt is None or not _closed_evt.is_set())
        )
        if alive and _cmd_q is not None:
            try:
                _cmd_q.put({"cmd": "route", "route": route})
                _cmd_q.put({"cmd": "show"})
            except Exception:  # noqa: BLE001
                pass
            return True
        _cmd_q = multiprocessing.Queue()
        _closed_evt = multiprocessing.Event()
        _ready_evt = multiprocessing.Event()
        _worker = multiprocessing.Process(
            target=_worker_main,
            args=(url, route, width, height, _cmd_q, _closed_evt, _ready_evt),
            name="AgentFloatWebShell",
            daemon=True,
        )
        try:
            _worker.start()
        except Exception as e:  # noqa: BLE001
            logger.error("启动 Web 壳子进程失败，改用系统浏览器打开: %s", e)
            _open_browser(url)
        return True


def shutdown():
    """程序退出时尽力关闭 Web 壳窗口（守护子进程随主进程结束）。"""
    global _worker, _cmd_q
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
