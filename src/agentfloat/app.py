# -*- coding: utf-8 -*-
"""AgentFloat — 应用引导（QApplication / 托盘 / 生命周期 / 更新链路）"""
import ctypes
import os
import subprocess
import sys

from PyQt5.QtCore import QCoreApplication, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt5.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from agentfloat.core.autostart import is_auto_start_enabled, toggle_auto_start
from agentfloat.core.config import load_config
from agentfloat.core.launcher import launch_agent
from agentfloat.core.logging_setup import (
    _install_error_handlers, _log, _setup_logger,
)
from agentfloat.core.paths import ICO_PATH, _IS_FROZEN, config_dir
from agentfloat.core.registry import default_agents, find_agent, get_primary_agent
from agentfloat.core.sysutil import _open_url, ensure_utf8_stdio
from agentfloat.core.theme import FONT_FAMILY, get_colors
from agentfloat.core.version import VERSION
from agentfloat.services.dsh import status as dsh_status, stop as stop_dsh
from agentfloat.services.skills.ai_service import ensure_translator_skill
from agentfloat.services.update import updater
from agentfloat.services.update.updater import DownloadWorker, UpdateWorker
from agentfloat.ui.dialogs import _update_box
from agentfloat.ui.floatball import FloatingWidget
from agentfloat.ui.loading_indicator import LoadingIndicator
from agentfloat.webshell import window as web_ui
from agentfloat.webshell.bridge import WebBridge
from agentfloat.webshell.handlers import WebAppHandlers
from agentfloat.webshell.server import start_server_thread


def main():
    ensure_utf8_stdio()
    # ── 启动日志 ──
    _setup_logger()
    _log().info("=" * 50)
    _log().info("AgentFloat v%s 启动 | Frozen=%s | PID=%s", VERSION, _IS_FROZEN, os.getpid())

    from datetime import datetime as _dt
    _start_ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    _report_dir = os.path.join(config_dir(), "logs", "reports")
    os.makedirs(_report_dir, exist_ok=True)
    _flush_error_report = _install_error_handlers()
    _session_path = os.path.join(_report_dir, f"v{VERSION}_{_start_ts}_session.txt")

    # 写入会话报告开头
    try:
        with open(_session_path, "w", encoding="utf-8") as _sf:
            _sf.write(f"AgentFloat v{VERSION} 会话报告\n")
            _sf.write(f"启动时间: {_dt.now().isoformat()}\n")
            _sf.write("打包模式: " + ("Frozen" if _IS_FROZEN else "Dev") + "\n")
            _sf.write(f"进程 PID: {os.getpid()}\n")
            _sf.write(f"Python: {sys.version}\n")
            _sf.write("-" * 40 + "\n")
    except Exception:
        pass

    try:
        _main()
        _log().info("AgentFloat 正常退出")
        try:
            with open(_session_path, "a", encoding="utf-8") as _sf:
                _sf.write(f"\n退出时间: {_dt.now().isoformat()}\n")
                _sf.write("状态: 正常退出\n")
        except Exception:
            pass
        _flush = _flush_error_report()
        if _flush:
            _log().info("错误汇总报告已导出: %s", _flush)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        exc_type = type(sys.exc_info()[1]).__name__ if sys.exc_info()[1] else "Unknown"
        _log().critical("未处理异常导致崩溃 [%s]:\n%s", exc_type, tb)

        _crash_path = os.path.join(_report_dir, f"v{VERSION}_{_start_ts}_{exc_type}.txt")
        try:
            with open(_crash_path, "w", encoding="utf-8") as _cf:
                _cf.write(f"AgentFloat v{VERSION} 崩溃报告\n")
                _cf.write(f"启动时间: {_start_ts}\n")
                _cf.write(f"崩溃时间: {_dt.now().isoformat()}\n")
                _cf.write(f"异常类型: {exc_type}\n")
                _cf.write("打包模式: " + ("Frozen" if _IS_FROZEN else "Dev") + "\n")
                _cf.write(f"Python: {sys.version}\n")
                _cf.write("-" * 40 + "\n\n")
                _cf.write(tb)
            _log().info("崩溃报告已写入: %s", _crash_path)
        except Exception:
            pass

        try:
            with open(_session_path, "a", encoding="utf-8") as _sf:
                _sf.write(f"\n退出时间: {_dt.now().isoformat()}\n")
                _sf.write(f"状态: 崩溃 ({exc_type})\n")
                _sf.write(f"详情: {_crash_path}\n")
        except Exception:
            pass
        try:
            sys.excepthook(*sys.exc_info())
        except Exception:
            pass
        _flush = _flush_error_report()
        if _flush:
            _log().info("错误汇总报告已导出: %s", _flush)
        raise


def _main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("agentfloat.launcher")
    except Exception: pass

    # 高分辨屏 DPI 一致性：必须在 QApplication 创建前设置，
    # 否则 QCursor.pos() / event.globalPos() 与 self.pos() 坐标空间不一致，
    # 导致环绕菜单悬停高亮错位、点击失效。
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("AgentFloat")
    app.setFont(QFont(FONT_FAMILY, 9))

    # ── 启动窗口动画：展示启动状态，主窗口就绪后切换「已就绪」并自动关闭 ──
    from agentfloat.ui.startup_splash import StartupSplash
    splash = StartupSplash()
    splash.start("正在启动 AgentFloat…")
    QTimer.singleShot(60, lambda: splash.set_detail("正在加载配置…"))

    config = load_config()

    # 退出时清理孤儿 Claude 进程（可配置，默认不清理）
    def _cleanup_on_quit():
        if config.get("cleanup_on_quit", False):
            primary = get_primary_agent(config.get("agents", default_agents()))
            cmd = (primary or {}).get("command", "")
            if cmd:
                base = os.path.basename(cmd)
                if not base.lower().endswith(".exe"):
                    base += ".exe"
                _log().info("退出清理: taskkill /f /im %s", base)
                subprocess.run(["taskkill", "/f", "/im", base],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    app.aboutToQuit.connect(_cleanup_on_quit)

    def _shutdown():
        # 退出时先取消正在运行的本地 AI / 自动翻译 / 快报服务，再等待线程结束
        for attr in ("_ai_worker", "_auto_worker", "_news_worker"):
            w = getattr(widget, attr, None)
            if w is not None and w.isRunning():
                _log().info("正在取消 %s…", attr)
                w.cancel()
                w.wait(8000)
        # 关闭 Web 壳子进程（如果存在）
        try:
            web_ui.shutdown()
        except Exception as e:  # noqa: BLE001
            _log().debug("Web 壳关闭异常: %s", e)
    app.aboutToQuit.connect(_shutdown)

    widget = FloatingWidget()

    # ── 动画加载指示器（dsh 启动 / Web 壳打开）──
    loading = LoadingIndicator(anchor=widget)
    _prev_dsh_phase = ["idle"]
    _prev_web_pending = [False]
    _web_loading_shown = [False]

    def _poll_loading():
        # 0) Web 壳预热/回收维护（P2：预热窗口空闲回收、关闭后再预热）
        web_ui.tick()
        # 1) dsh 启动状态（dsh 启动期间独占指示器，避免与 Web 壳互相覆盖）
        st = dsh_status()
        ph = st.get("phase") or "idle"
        if ph == "starting":
            if _prev_dsh_phase[0] != "starting":
                _prev_dsh_phase[0] = ph
                loading.show_loading(st.get("message") or "正在启动 DeepSeek Harness", st.get("detail") or "")
            else:
                el = int(st.get("elapsed") or 0)
                base = (st.get("detail") or "").split("（已等待")[0]
                loading.set_detail("%s（已等待 %d 秒）" % (base, el))
        elif ph in ("ready", "timeout", "exited", "error"):
            if _prev_dsh_phase[0] != ph:
                _prev_dsh_phase[0] = ph
                if ph == "ready":
                    loading.show_success(st.get("message") or "DeepSeek Harness 已就绪", st.get("detail") or "")
                    loading.hide_after(1000)  # 成功：显示约 1 秒后自动关闭
                else:
                    loading.show_error(st.get("message") or "启动失败", st.get("detail") or "")
                    loading.hide_after(7000)
        else:
            _prev_dsh_phase[0] = "idle"
        # 2) Web 壳打开等待（dsh 启动中不接管，避免覆盖 dsh 的加载/成功提示）
        if ph != "starting":
            wp = web_ui.has_pending()
            if wp != _prev_web_pending[0]:
                _prev_web_pending[0] = wp
                if wp:
                    _web_loading_shown[0] = True
                    loading.show_loading("正在打开 Web 界面…", "正在启动浏览器内核…")
                elif _web_loading_shown[0] and web_ui.is_ready():
                    _web_loading_shown[0] = False
                    loading.show_success("Web 界面已就绪")
                    loading.hide_after(1000)  # 成功：显示约 1 秒后自动关闭
                elif _web_loading_shown[0]:
                    _web_loading_shown[0] = False
                    loading.hide_now()

    _loading_poll = QTimer()
    _loading_poll.setInterval(300)
    _loading_poll.timeout.connect(_poll_loading)
    _loading_poll.start()

    # ── Web 壳：FastAPI 后端 + 事件桥（设置 / API 用量 / AI 快报）──
    bridge = WebBridge()
    bridge.set_snapshot("version", VERSION)
    widget._web_bridge = bridge
    _web_handlers = WebAppHandlers(widget, bridge)
    _web_thread, _web_port, _web_ok = start_server_thread(bridge, _web_handlers)
    web_ui.set_base_url("http://127.0.0.1:%d" % _web_port)
    if _web_ok:
        _log().info("Web 壳后端已启动: http://127.0.0.1:%d", _web_port)
        # ── Web 壳静默预热（P2）：后台隐藏创建窗口，打开设置/快报秒开；
        #    长时间未使用由 web_ui.tick() 自动回收 ──
        QTimer.singleShot(6000, web_ui.preheat)
    else:
        _log().error("Web 壳后端启动失败（端口 %d 未就绪），设置 / API 用量 / AI 快报 将不可用", _web_port)

    # ── 设置（Web 壳）──
    def open_settings():
        _log().debug("打开 Web 设置窗口")
        web_ui.open_window("#/settings")

    if "--open-web" in sys.argv:
        _log().info("调试参数 --open-web：启动后自动打开 Web 设置窗口")
        QTimer.singleShot(2000, open_settings)

    def do_launch():
        launch_agent(get_primary_agent(widget.config.get("agents", default_agents())), widget.config)

    # ── 自动更新（多源检查 + 下载 + 静默重装重启）──
    update_worker_ref = {}
    download_worker_ref = {}

    def _friendly_update_error(info):
        code = info.get("error", "") if info else ""
        hint = {
            "timeout": "网络超时，请稍后重试。",
            "network": "网络连接失败，可稍后重试，或配置 mirror.json 自建镜像。",
            "unknown": "未知错误。",
        }.get(code, "")
        return "检查更新失败（%s）。%s" % (code, hint)

    def _tray_download_latest(info):
        """后台下载最新安装包，完成后直接安排静默重装重启（打包版）"""
        url = info.get("url") or ""
        if not url:
            _update_box(None, QMessageBox.Information, "更新",
                "最新版本没有可下载的安装包，\n请前往 GitHub Releases 页面手动下载。")
            updater.open_release_page()
            return

        def _on_done(path):
            download_worker_ref.pop("worker", None)
            _log().info("更新包下载完成: %s", path)
            if updater.apply_update(path):
                _update_box(None, QMessageBox.Information, "更新已开始",
                    "更新已开始：程序将退出，安装完成后会自动重启。")
                QTimer.singleShot(800, app.quit)
            else:
                ret = _update_box(None, QMessageBox.Question, "下载完成",
                    f"新版本 {info.get('version')} 安装包已下载：\n{path}\n\n"
                    "是否立即运行安装程序？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if ret == QMessageBox.Yes:
                    try:
                        os.startfile(path)
                    except Exception as e:
                        _update_box(None, QMessageBox.Warning, "启动失败", f"无法启动安装程序:\n{e}")

        def _on_failed(msg):
            download_worker_ref.pop("worker", None)
            _log().warning("更新下载失败: %s", msg)
            box = QMessageBox(QMessageBox.Warning, "下载失败",
                              "下载更新失败：\n%s\n\n"
                              "可前往 GitHub Releases 页面手动下载最新版本。" % msg,
                              QMessageBox.Ok, None)
            box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
            open_btn = box.addButton("打开 Releases 页面", QMessageBox.AcceptRole)
            box.exec_()
            if box.clickedButton() is open_btn:
                updater.open_release_page()

        worker = DownloadWorker(url)
        worker.done.connect(_on_done)
        worker.failed.connect(_on_failed)
        download_worker_ref["worker"] = worker
        worker.start()
        _log().info("开始下载更新: %s", url)

    def _on_update_result(info, manual):
        update_worker_ref.pop("worker", None)
        if info is None or not info.get("available"):
            if manual:
                if info is not None and info.get("error"):
                    _update_box(None, QMessageBox.Warning, "检查更新失败", _friendly_update_error(info))
                else:
                    _update_box(None, QMessageBox.Information, "检查更新", f"当前已是最新版本 v{VERSION}。")
            return
        detail = (info.get("notes_zh") or info.get("notes") or "前往 GitHub Releases 查看更新说明。")[:400]
        ret = _update_box(
            None, QMessageBox.Question, "发现新版本",
            f"发现新版本 {info['version']}（当前 v{VERSION}）。\n\n更新内容:\n{detail}\n\n"
            "是否立即下载并更新？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ret == QMessageBox.Yes:
            _tray_download_latest(info)

    def _on_check_failed(msg, manual):
        update_worker_ref.pop("worker", None)
        if manual:
            _update_box(None, QMessageBox.Warning, "检查更新失败", f"无法连接更新服务器：\n{msg}")

    def _check_update(manual=False):
        if update_worker_ref.get("worker"):
            return  # 正在检查中
        worker = UpdateWorker(VERSION)
        worker.result_ready.connect(lambda info: _on_update_result(info, manual))
        worker.check_failed.connect(lambda msg: _on_check_failed(msg, manual))
        update_worker_ref["worker"] = worker
        worker.start()
        _log().info("检查更新 (手动=%s, 当前 v%s)", manual, VERSION)

    # ── Web 命令分发（uvicorn 线程 → Qt 主线程）──
    def _handle_web_command(kind, payload):
        if kind == "apply":
            widget.apply_settings(payload.get("config") or widget.config, preview_only=False)
            bridge.publish("config_applied", {"changed_keys": payload.get("changed_keys") or []})
        elif kind == "preview":
            widget.apply_settings(payload.get("config") or widget.config, preview_only=True)
        elif kind == "generate_news":
            widget._generate_news(auto=False)
        elif kind == "news_read":
            widget._mark_news_read()
        elif kind == "check_update":
            _check_update(manual=True)
        elif kind == "open_url":
            url = payload.get("url") or ""
            if url:
                _open_url(url)
        elif kind == "launch_agent":
            agent = find_agent(widget.config.get("agents", default_agents()), payload.get("id") or "")
            if agent:
                launch_agent(agent, widget.config)
        elif kind == "run_ai_services":
            widget._run_local_ai_services(auto=bool(payload.get("auto", False)))
        elif kind == "stop_dsh":
            stop_dsh()
        elif kind == "restart_api_monitor":
            widget._restart_api_monitor()

    def _dispatch_web_commands():
        for kind, payload in bridge.drain_commands():
            try:
                _handle_web_command(kind, payload)
            except Exception:
                _log().error("Web 命令处理失败 [%s]", kind, exc_info=True)

    _cmd_timer = QTimer()
    _cmd_timer.setInterval(150)
    _cmd_timer.timeout.connect(_dispatch_web_commands)
    _cmd_timer.start()

    # ── 系统托盘 ──
    def _build_menu_stylesheet(theme):
        tc = get_colors(theme)
        sfc = tc["SURFACE"]
        txt = tc["TEXT"]
        acc = tc["ACCENT"]
        sep = tc["SEPARATOR"]
        return (
            f"QMenu {{ background: rgba({sfc[0]},{sfc[1]},{sfc[2]},0.95);"
            f" border: 1px solid rgba(0,0,0,0.1); border-radius: 10px; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 7px 32px 7px 16px; font-size: 12px;"
            f" color: #{txt[0]:02X}{txt[1]:02X}{txt[2]:02X}; }}"
            f"QMenu::item:selected {{ background: #{acc[0]:02X}{acc[1]:02X}{acc[2]:02X};"
            f" color: #FFF; border-radius: 4px; margin: 1px 6px; }}"
            f"QMenu::separator {{ height: 1px;"
            f" background: #{sep[0]:02X}{sep[1]:02X}{sep[2]:02X}; margin: 4px 8px; }}"
        )

    tray_menu = QMenu()
    tray_menu.setStyleSheet(_build_menu_stylesheet(widget.theme))

    tray_menu.addAction("显示浮窗", widget.show)
    tray_menu.addSeparator()
    tray_primary = get_primary_agent(widget.config.get("agents", default_agents()))
    tray_pname = tray_primary.get("name", "主 Agent") if tray_primary else "主 Agent"
    tray_menu.addAction("启动 %s" % tray_pname, do_launch)
    if len(widget.config.get("agents", [])) > 1:
        tray_sub = tray_menu.addMenu("启动其他 Agent")
        for a in widget.config.get("agents", []):
            if a.get("id") == (tray_primary or {}).get("id"):
                continue
            tray_sub.addAction(a.get("name"), lambda a=a: launch_agent(a, widget.config))
    tray_menu.addAction("Skills 辅助窗", widget._open_skills_panel)
    tray_menu.addAction("AI 快报", widget._open_news_panel)
    tray_menu.addAction("喝水助手", widget._open_water_panel)
    tray_menu.addAction("停止 DSH Web 服务", lambda: stop_dsh())
    tray_menu.addSeparator()
    tray_menu.addAction("设置...", open_settings)
    tray_menu.addSeparator()

    tray_auto = tray_menu.addAction("开机自启")
    tray_auto.setCheckable(True)
    tray_auto.setChecked(is_auto_start_enabled())
    tray_auto.triggered.connect(lambda c: toggle_auto_start(c))

    tray_menu.addSeparator()
    tray_menu.addAction("检查更新...", lambda: _check_update(manual=True))
    tray_menu.addSeparator()
    tray_menu.addAction("退出", app.quit)

    tray_icon = QSystemTrayIcon()
    if os.path.exists(ICO_PATH):
        tray_icon.setIcon(QIcon(ICO_PATH))
    else:
        pix = QPixmap(32, 32)
        tc = get_colors(widget.theme)
        pix.fill(QColor(*tc["ACCENT"]))
        tray_icon.setIcon(QIcon(pix))

    tray_icon.setToolTip("AgentFloat — AI Agent 浮窗助手 | 点击启动主 Agent | 悬停/长按环绕菜单 | Ctrl+Alt+C")
    tray_icon.setContextMenu(tray_menu)
    tray_icon.activated.connect(lambda r: widget.show() if r == QSystemTrayIcon.DoubleClick else None)
    tray_icon.show()
    tray_icon.showMessage("AgentFloat", "AI Agent 浮窗助手已启动", QSystemTrayIcon.Information, 2000)

    # 翻译 skill 自动部署 + 新装 skill 自动触发翻译（延迟执行，避免拖慢启动）
    QTimer.singleShot(
        3000, lambda: (ensure_translator_skill(), widget._auto_translate_new_skills()))

    # AI 快报调度器启动（含启动补生成检查）
    widget._setup_news_scheduler()

    widget.launch_requested.connect(do_launch)
    widget.quit_requested.connect(app.quit)
    widget.settings_requested.connect(open_settings)
    widget.ai_service_done.connect(lambda summary: tray_icon.showMessage(
        "AgentFloat — AI 自检完成", summary, QSystemTrayIcon.Information, 5000))
    widget.ai_service_failed.connect(lambda err: tray_icon.showMessage(
        "AgentFloat — AI 自检失败", str(err), QSystemTrayIcon.Warning, 7000))
    widget.auto_translate_done.connect(lambda msg: tray_icon.showMessage(
        "AgentFloat — 自动翻译", msg, QSystemTrayIcon.Information, 5000))
    widget.auto_translate_failed.connect(lambda err: tray_icon.showMessage(
        "AgentFloat — 自动翻译失败", str(err), QSystemTrayIcon.Warning, 7000))
    widget.news_done.connect(lambda msg: tray_icon.showMessage(
        "AgentFloat — AI 快报", msg, QSystemTrayIcon.Information, 5000))
    widget.water_reminded.connect(lambda msg: tray_icon.showMessage(
        "AgentFloat — 喝水助手", msg, QSystemTrayIcon.Information, 5000))
    widget.news_failed.connect(lambda err: tray_icon.showMessage(
        "AgentFloat — AI 快报失败", str(err), QSystemTrayIcon.Warning, 7000))
    # 主题切换时同步更新托盘菜单样式与 Web 壳
    widget.theme_changed.connect(lambda t: tray_menu.setStyleSheet(_build_menu_stylesheet(t)))
    widget.theme_changed.connect(lambda t: bridge.publish("theme_changed", {"theme": t}))
    widget.show()
    # GUI 就绪后写 boot 标记，供更新批处理确认重装后的启动是否成功
    updater.mark_boot_ok()
    # 主窗口就绪：启动动画切换为「已就绪」并约 1 秒后自动关闭
    QTimer.singleShot(120, lambda: splash.done("启动完成，已就绪"))

    if config.get("auto_start") and not is_auto_start_enabled():
        toggle_auto_start(True)

    # 启动后延迟自动检查更新（不阻塞启动）
    if config.get("check_updates", True):
        QTimer.singleShot(3000, lambda: _check_update(manual=False))

    sys.exit(app.exec_())
