# -*- coding: utf-8 -*-
"""AgentFloat — 浮球主窗口（绘制 / 交互 / 环绕菜单托管 / 面板调度）

P2：交互裁决已抽到 ui/interaction.py（状态机）；绘制走三态 pixmap
预渲染 + 固定窗口位图缩放（悬停/按压动画不重建掩码与缓存）。
"""
import copy
import ctypes
import math
import os
import subprocess
import time
from ctypes import wintypes

from PyQt5.QtCore import (
    Qt, QPoint, QPointF, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, pyqtProperty, QRect, QRectF,
)
from PyQt5.QtGui import (
    QPainter, QBrush, QColor, QRadialGradient, QLinearGradient, QPen,
    QPixmap, QRegion, QCursor, QPainterPath,
)
from PyQt5.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

from agentfloat.core.config import load_config, save_config
from agentfloat.core.launcher import launch_agent
from agentfloat.core.logging_setup import _log
from agentfloat.core.registry import (
    DEFAULT_RADIAL_MENU, DEFAULT_SKILLS, find_agent, get_primary_agent,
    normalize_agents,
)
from agentfloat.core.theme import DEFAULT_SIZE, HOVER_SCALE, PRESS_SCALE, get_colors
from agentfloat.services.api_monitor.badge import ApiBalanceBadge
from agentfloat.services.api_monitor.config import DEFAULTS as API_MONITOR_DEFAULTS
from agentfloat.services.api_monitor.fetcher import serialize_results
from agentfloat.services.api_monitor.worker import ApiMonitorWorker
from agentfloat.services.news.fetcher import DEFAULT_NEWS as _NEWS_DEFAULTS
from agentfloat.services.news.worker import NewsWorker, today_news_exists
from agentfloat.services.skills.ai_service import (
    AutoTranslateWorker, LocalAiWorker, _ensure_platform_url, find_new_skills,
)
from agentfloat.services.skills.scanner import default_skill_roots
from agentfloat.services.water.reminder import (
    DEFAULT_WATER, WaterTimerManager, is_exempt_process,
)
from agentfloat.ui.panels.clipboard import ClipboardHistory, ClipboardPanel
from agentfloat.ui.panels.command import CommandPanel
from agentfloat.ui.panels.skills import SkillsPanel
from agentfloat.ui.panels.water import WaterPanel, WaterReminderPopup
from agentfloat.core.single_instance import activate_message_id
from agentfloat.core.qtutil import release_thread_later, track
from agentfloat.ui.interaction import Actions as InteractionActions, BallInteraction
from agentfloat.ui.motion import Tokens as MotionTokens, motion, spring
from agentfloat.ui.placement import (
    EDGE_MARGIN, VALID_EDGES, clamp_visible, edge_position, normalize_edge,
    screen_index_for,
)
from agentfloat.ui.toast import LaunchToast
from agentfloat.ui.radial_menu import RadialMenu, RadialMenuItem, RADIAL_PAD
from agentfloat.core.autostart import is_auto_start_enabled, toggle_auto_start
from agentfloat.webshell import window as web_ui

# ── 浮球窗口几何（P2：固定窗口 + 位图缩放）──
BALL_PAD = 9          # 窗口四周留白（容纳阴影与微光）


class FloatingWidget(QWidget):
    launch_requested  = pyqtSignal()
    quit_requested    = pyqtSignal()
    settings_requested = pyqtSignal()
    theme_changed     = pyqtSignal(str)
    ai_service_done   = pyqtSignal(str)
    ai_service_failed = pyqtSignal(str)
    auto_translate_done   = pyqtSignal(str)
    auto_translate_failed = pyqtSignal(str)
    news_done   = pyqtSignal(str)
    news_failed = pyqtSignal(str)
    water_reminded = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.theme = self.config.get("theme", "light")
        _log().info("浮窗初始化: size=%s, opacity=%.2f, theme=%s",
                     self.config.get("widget_size", DEFAULT_SIZE),
                     self.config.get("opacity", 0.88),
                     self.theme)
        self.is_hovered = False
        self.is_pressed = False
        self.base_size = self.config.get("widget_size", DEFAULT_SIZE)
        self.current_size = self.base_size

        # ── 多 Agent / 环绕菜单 ──
        self._agents = normalize_agents(self.config.get("agents"))
        self._radial_cfg = copy.deepcopy(self.config.get("radial_menu") or DEFAULT_RADIAL_MENU)
        self._skills_cfg = copy.deepcopy(self.config.get("skills") or DEFAULT_SKILLS)
        self._radial_menu = None
        self._api_last_results = []

        # 拖拽状态
        self._drag_active = False
        self._drag_origin = QPoint()
        self._window_origin = QPoint()
        # 交互状态机（P2）：单击/悬停/长按/拖拽/贴边统一裁决
        self._interaction = BallInteraction(self._radial_cfg)
        # 启动反馈气泡（P2 点按即时反馈）
        self._launch_toast = None
        self.launch_requested.connect(self._show_launch_feedback)
        # 退出动画中，拒绝所有交互
        self._quitting = False

        # 按压缩放视觉（P2：弹簧驱动，仅重绘不改变窗口几何）
        self._visual_scale = 1.0
        self._scale_state = spring(1.0, MotionTokens.PRESS)
        self._scale_cancel = None
        # 涟漪 (0.0 ~ 1.0)
        self._ripple_progress = 0.0
        self._ripple_pos = QPoint()
        self._ripple_timer = QTimer(self)
        self._ripple_timer.setInterval(16)
        self._ripple_timer.timeout.connect(self._tick_ripple)

        # 吸附状态
        self._snapped = False
        self._snap_edge = ""
        self._snap_menu_restore = None   # 打开环绕菜单时的临时移位（关闭菜单后恢复）
        self._hidden_now = False   # 当前是否处于“滑出屏幕外”的隐藏位
        self._hidden_offset = 0   # 隐藏时的偏移
        self._slide_anim = None   # 滑动动画引用（防 GC + 可中断）
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._auto_hide)
        # 边缘检测条（透明窗口，用于检测鼠标靠近屏幕边缘）
        self._edge_detector = None

        # Claude 进程检测（绿色指示灯）
        self._claude_running = False
        self._proc_timer = QTimer(self)
        self._proc_timer.setInterval(3000)  # 每 3 秒检测一次
        self._proc_timer.timeout.connect(self._check_claude_process)
        self._proc_timer.start()

        # API 余额角标（极简独立小窗，跟随浮窗）
        self._api_badge = None
        self._api_worker = None
        self._init_api_monitor()

        # 本地 AI 服务（仅手动触发；翻译任务由本地 skill 完成）
        self._ai_worker = None
        self._auto_worker = None

        # 剪贴板历史 + 自定义命令
        self._clipboard = ClipboardHistory(self.config)
        try:
            self._last_clip_text = QApplication.clipboard().text()
        except Exception:
            self._last_clip_text = ""
        self._clip_timer = QTimer(self)
        self._clip_timer.setInterval(1000)
        self._clip_timer.timeout.connect(self._clipboard_tick)
        self._clip_timer.start()
        self._commands = [dict(c) for c in (self.config.get("commands") or [])]

        # ── AI 快报 ──
        self._news_cfg = copy.deepcopy(self.config.get("news") or _NEWS_DEFAULTS)
        # —— 喝水助手 ——
        self._water_cfg = copy.deepcopy(self.config.get("water") or DEFAULT_WATER)
        self._water_mgr = WaterTimerManager(self._water_cfg, parent=self)
        self._water_mgr.timer_finished.connect(self._on_water_timer_finished)
        self._water_popups = {}
        self._news_worker = None
        self._news_panel = None
        self._news_generating = False
        self._news_pop_after = False
        self._news_unread = int(self._news_cfg.get("unread_count") or 0)
        self._news_check_timer = QTimer(self)
        self._news_check_timer.setInterval(60000)
        self._news_check_timer.timeout.connect(self._news_timer_tick)
        if self._news_cfg.get("enabled"):
            self._news_check_timer.start()

        # 预缓存绘制资源（三态位图 + 几何）
        self._cache = {}

        self._setup_ui()
        self._apply_opacity()
        self._restore_position()
        self._render_pixmaps()

    # ── 窗口几何（P2：固定窗口 + 位图缩放，动画不再重建掩码/缓存）──
    def _window_side(self):
        """窗口边长 = 悬停最大球径 + 两侧留白（容纳阴影与微光）"""
        return int(math.ceil(self.current_size * max(HOVER_SCALE, 1.0))) + BALL_PAD * 2

    def _ball_offset(self):
        """球体（基准尺寸）在窗口内的左上偏移"""
        return (self._window_side() - self.current_size) / 2.0

    def _ball_rect(self):
        off = self._ball_offset()
        return QRectF(off, off, self.current_size, self.current_size)

    def _update_mask(self):
        """掩码：球体范围 + 少量余量（拖动/点击命中区域）"""
        s = self.current_size
        off = self._ball_offset()
        m = 5.0
        rad = max(6.0, s * 0.30) + m
        path = QPainterPath()
        path.addRoundedRect(QRectF(off - m, off - m, s + 2 * m, s + 2 * m), rad, rad)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)

    def _render_pixmaps(self):
        """预渲染球体位图（idle / hover）：固定窗口 + 位图缩放，动画零重建

        P2 性能方案：悬停/按压动画只绘制缩放后的位图，不再每帧
        重建渐变缓存/掩码/窗口尺寸（旧实现的掉帧根因）。
        """
        c = get_colors(self.theme)
        accent = QColor(*c["ACCENT"])
        side = self._window_side()
        try:
            dpr = max(1.0, float(self.devicePixelRatioF()))
        except Exception:
            dpr = 1.0
        cache = {"side": side, "accent": accent}
        for name, hovered in (("idle", False), ("hover", True)):
            pm = QPixmap(int(side * dpr), int(side * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            self._render_ball_pixmap(pm, hovered, accent, side)
            cache[name] = pm
        # 球体路径（涟漪裁剪用）
        off = self._ball_offset()
        s = self.current_size
        rad = max(6.0, s * 0.30)
        path = QPainterPath()
        path.addRoundedRect(QRectF(off, off, s, s), rad, rad)
        cache["ball_path"] = path
        self._cache = cache

    def _render_ball_pixmap(self, pm, hovered, accent, side):
        """方案 C：深色玻璃 + 品牌渐变描边 + 内部光晕 + 白色旋涡"""
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = float(self.current_size)
        cx = cy = side / 2.0
        rad = max(6.0, s * 0.30)
        rect = QRectF(cx - s / 2.0, cy - s / 2.0, s, s)

        # 阴影（悬停加深 / P2 弹性放大有阴影托底更立体）
        p.setPen(Qt.NoPen)
        base_a = 64 if hovered else 46
        for off, k in ((0.0, 0.45), (2.2, 0.28), (4.2, 0.15)):
            p.setBrush(QColor(0, 0, 0, int(base_a * k)))
            p.drawRoundedRect(rect.adjusted(off, off + 1.2, off, off + 1.2), rad, rad)

        # 深色玻璃底
        p.setBrush(QColor(30, 30, 34, 240))
        p.drawRoundedRect(rect, rad, rad)

        # 内部光晕（品牌色，悬停更亮）
        glow = QRadialGradient(QPointF(cx, rect.y() + s * 0.40), s * 0.55)
        ga = 64 if hovered else 46
        glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), ga))
        glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        p.setBrush(QBrush(glow))
        p.drawRoundedRect(rect, rad, rad)

        # 品牌渐变描边（135°：#0a84ff → #af52de）
        lg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        ba = 250 if hovered else 220
        lg.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), ba))
        lg.setColorAt(1.0, QColor(175, 82, 222, ba))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QBrush(lg), 1.8))
        p.drawRoundedRect(rect.adjusted(0.9, 0.9, -0.9, -0.9), rad, rad)

        # 白色旋涡 glyph（品牌延续）
        self._draw_spiral(p, cx, cy, s / 52.0)
        p.end()

    @staticmethod
    def _draw_spiral(p, cx, cy, k=1.0):
        """白色旋涡：从中心向外 2.35 圈的螺旋线"""
        path = QPainterPath()
        n = 56
        for i in range(n + 1):
            t = i / n
            ang = t * math.pi * 2.35 - math.pi * 0.5
            rad = (1.2 + 7.3 * t) * k
            x = cx + math.cos(ang) * rad
            y = cy + math.sin(ang) * rad
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.setPen(QPen(QColor(255, 255, 255, 238), max(1.6, 3.2 * k),
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


    def _check_claude_process(self):
        """检测主 Agent 进程是否在运行，更新指示灯状态"""
        try:
            primary = get_primary_agent(self._agents)
            cmd = (primary or {}).get("command", "")
            base = os.path.basename(cmd) if cmd else ""
            if not base:
                self._claude_running = False
                return
            if not base.lower().endswith(".exe"):
                base += ".exe"
            result = subprocess.run(
                ["tasklist", "/fi", "imagename eq %s" % base, "/nh"],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
            )
            was_running = self._claude_running
            self._claude_running = base.lower() in result.stdout.lower()
            if was_running != self._claude_running:
                _log().debug("Agent 进程状态变化: running=%s", self._claude_running)
                self.update()  # 状态变化时重绘
        except Exception:
            self._claude_running = False

    # ── API 用量监控 ─────────────────────────────
    def _init_api_monitor(self):
        """初始化余额角标和轮询线程（先建角标再连信号，避免竞态）"""
        am_config = self.config.get("api_monitor", API_MONITOR_DEFAULTS)
        if not am_config.get("enabled") or not am_config.get("endpoints"):
            return

        self._api_badge = ApiBalanceBadge(parent_float=self)
        self._api_badge.set_theme(self.theme)
        self._api_badge.set_warn_threshold(am_config.get("low_balance_warn", 5.0))
        self._api_badge.update_balance("--")
        if self.isVisible():
            self._api_badge.show()

        self._api_worker = ApiMonitorWorker(
            endpoints=am_config.get("endpoints", []),
            interval_seconds=am_config.get("poll_interval_seconds", 60),
        )
        track(self._api_worker, "ApiMonitorWorker")
        self._api_worker.data_ready.connect(self._on_api_data_ready)
        self._api_worker.start()
        _log().info("API 用量监控已启动: %d 端点", len(am_config.get("endpoints", [])))

    def _stop_api_monitor(self):
        """停止 API 用量监控"""
        if self._api_worker and self._api_worker.isRunning():
            self._api_worker.stop()
            self._api_worker.wait(2000)
        if self._api_badge:
            self._api_badge.hide()
            self._api_badge.deleteLater()
            self._api_badge = None
        self._api_worker = None
        _log().info("API 用量监控已停止")

    def _restart_api_monitor(self):
        """重启 API 用量监控（配置变更后调用）"""
        self._stop_api_monitor()
        self._init_api_monitor()

    # ── 本地 AI 服务（手动：API 余额配置 / Skills 翻译）──────────
    def _release_worker_attr(self, attr):
        """worker 线程结束后再清空引用（PATCH 3.0.2：防运行中析构 qFatal）"""
        w = getattr(self, attr, None)

        def _clear_if_current():
            if getattr(self, attr, None) is w:   # 期间若已换新 worker，不能误清
                setattr(self, attr, None)

        release_thread_later(w, _clear_if_current)

    def _run_local_ai_services(self, auto=False):
        """后台线程运行本地 AI 服务；auto=True 用托盘通知，False 弹窗"""
        if self._ai_worker is not None and self._ai_worker.isRunning():
            _log().info("本地 AI 服务已在运行中，忽略重复触发")
            return
        agent = get_primary_agent(self._agents)
        if not agent:
            _log().warning("本地 AI 服务：未配置主 Agent")
            if not auto:
                QMessageBox.warning(None, "AI 自检服务", "未配置主 Agent，请先在「设置 → Agent 管理」中配置。")
            return
        self._ai_worker = LocalAiWorker(self.config, agent, parent=self)
        track(self._ai_worker, "LocalAiWorker")
        self._ai_worker.finished_ok.connect(lambda res: self._on_ai_service_done(res, auto))
        self._ai_worker.failed.connect(lambda err: self._on_ai_service_failed(err, auto))
        self._ai_worker.start()
        _log().info("本地 AI 服务已启动 (auto=%s, agent=%s)", auto, agent.get("name"))

    def _on_ai_service_done(self, res, auto):
        self._release_worker_attr("_ai_worker")
        api = res.get("api") or {}
        if api.get("api_config") is not None:
            self.config["api_monitor"] = api["api_config"]
            self._restart_api_monitor()
        svc = dict(self.config.get("services") or {})
        from datetime import datetime
        svc["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        svc["ai_first_run_done"] = True
        self.config["services"] = svc
        save_config(self.config)
        summary = res.get("summary", "完成")
        _log().info("本地 AI 服务完成:\n%s", summary)
        if auto:
            self.ai_service_done.emit(summary)
        else:
            QMessageBox.information(None, "AI 自检服务", summary)

    def _on_ai_service_failed(self, err, auto):
        self._release_worker_attr("_ai_worker")
        _log().warning("本地 AI 服务失败: %s", err)
        if auto:
            self.ai_service_failed.emit(str(err))
        else:
            QMessageBox.warning(None, "AI 自检服务", "运行失败：\n%s" % err)

    # ── 新装 skill 自动触发翻译（装完新 skill 后自动补译，不跑完整流程）──
    def _auto_translate_new_skills(self):
        """检测新安装且缺少中文翻译的 skill，自动调用本地 Agent 补译。"""
        cfg = self.config.get("skills") or {}
        if not cfg.get("auto_translate_new_skills", True):
            _log().debug("自动翻译已关闭，跳过检测")
            return
        if self._ai_worker is not None and self._ai_worker.isRunning():
            return
        if self._auto_worker is not None and self._auto_worker.isRunning():
            return
        agent = get_primary_agent(self._agents)
        if not agent:
            _log().debug("自动翻译：未配置主 Agent，跳过")
            return
        roots = cfg.get("roots") or default_skill_roots()
        try:
            new_skills = find_new_skills(roots)
        except Exception:
            _log().warning("自动翻译：检测新 skill 异常", exc_info=True)
            return
        if not new_skills:
            _log().info("自动翻译：未检测到需要翻译的新 skill")
            return
        _log().info("自动翻译：检测到 %d 个新 skill，调用 %s 补译",
                    len(new_skills), agent.get("name"))
        worker = AutoTranslateWorker(self.config, agent, new_skills, parent=self)
        track(worker, "AutoTranslateWorker")
        worker.done.connect(self._on_auto_translate_done)
        worker.failed.connect(self._on_auto_translate_failed)
        self._auto_worker = worker
        worker.start()

    def _on_auto_translate_done(self, added, names):
        self._release_worker_attr("_auto_worker")
        _log().info("自动翻译完成：新增 %d 条（%s）", added, ", ".join(names[:5]))
        self.auto_translate_done.emit(
            "检测到 %d 个新 skill，自动翻译完成：新增 %d 条中文翻译" % (len(names), added))

    def _on_auto_translate_failed(self, err):
        self._release_worker_attr("_auto_worker")
        _log().warning("自动翻译失败: %s", err)
        self.auto_translate_failed.emit(str(err))

    def _on_api_data_ready(self, results):
        """轮询数据就绪，更新余额角标（只显示剩余额度）"""
        self._api_last_results = results or []
        _bridge = getattr(self, "_web_bridge", None)
        if _bridge is not None:
            _bridge.set_snapshot("api_results", serialize_results(results))
            _bridge.publish("api_updated", {"count": len(results or [])})
        if not results or not self._api_badge:
            return
        # 监控启用时保持角标常显（数据就绪即补显，避免时有时无）
        if self.isVisible() and not self._api_badge.isVisible():
            self._api_badge.show()
        r = results[0]
        if not r.fields:
            return

        # worker 请求失败时产生错误伪字段
        first = r.fields[0]
        if first.get("label") == "错误":
            self._api_badge.update_balance("查询失败", is_error=True)
            return

        # 优先按标签匹配剩余额度，否则取第一个字段
        field = next((f for f in r.fields if f.get("label") == "剩余额度"), first)
        val, unit = field.get("value"), field.get("unit", "")
        if val is None:
            _log().warning("[API] 字段 ""%s"" 返回 None，原始响应前200字符: %s",
                           field.get("label", "?"), r.raw_response[:200])
            self._api_badge.update_balance("N/A", is_error=True)
            return
        try:
            num = float(val)
            text = f"{num:.2f}{unit}"
        except (TypeError, ValueError):
            _log().warning("[API] 字段 ""%s"" 值无法转为数字: %s", field.get("label", "?"), val)
            self._api_badge.update_balance(str(val)[:20] + (unit if unit else ""), num=None)
            return
        self._api_badge.update_balance(text, num)

    def _sync_api_panel_position(self):
        """同步余额角标位置"""
        if self._api_badge:
            self._api_badge.sync_position()

    def _setup_ui(self):
        side = self._window_side()
        self.setFixedSize(side, side)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._update_mask()

        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(100)
        self._hover_timer.timeout.connect(self._check_hover)
        self._hover_timer.start()

        # 环绕菜单触发定时器（悬停 / 长按双通道）
        self._hover_open_timer = QTimer(self)
        self._hover_open_timer.setSingleShot(True)
        self._hover_open_timer.timeout.connect(self._on_hover_open_fired)
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._on_long_press_fired)

        # 全局快捷键
        self._hotkey_id = 1
        self._hotkey_registered = False
        self._register_hotkey()

    # ── 全局快捷键 ────────────────────────────────
    def _register_hotkey(self):
        """注册 Ctrl+Alt+C 全局快捷键"""
        if self._hotkey_registered:
            return
        try:
            MOD_ALT = 0x0001
            MOD_CONTROL = 0x0002
            VK_C = 0x43
            result = ctypes.windll.user32.RegisterHotKey(
                int(self.winId()), self._hotkey_id, MOD_CONTROL | MOD_ALT, VK_C
            )
            self._hotkey_registered = (result != 0)
            if self._hotkey_registered:
                _log().debug("全局快捷键 Ctrl+Alt+C 注册成功")
            else:
                _log().warning("全局快捷键注册失败（可能被其他程序占用）")
        except Exception:
            self._hotkey_registered = False
            _log().warning("全局快捷键注册异常")

    def _unregister_hotkey(self):
        """注销全局快捷键"""
        if self._hotkey_registered:
            try:
                ctypes.windll.user32.UnregisterHotKey(int(self.winId()), self._hotkey_id)
            except Exception:
                pass
            self._hotkey_registered = False

    def nativeEvent(self, eventType, message):
        """处理 Windows 原生消息（WM_HOTKEY）"""
        WM_HOTKEY = 0x0312
        if eventType == "windows_generic_MSG":
            # message 是 sip.voidptr，需要用 ctypes 解析 MSG 结构体
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt", POINT),
                ]
            msg = MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                if self.isVisible():
                    self.hide()
                else:
                    self.show()
                return True, 0
            if msg.message == activate_message_id():
                # 重复启动（第二实例）请求唤出浮窗（PATCH 3.0.1）
                self._ensure_on_screen()
                if self._snapped:
                    self._show_full()
                self.show()
                self.raise_()
                return True, 0
        return super().nativeEvent(eventType, message)

    def showEvent(self, event):
        """显示时启动 hover 检测"""
        super().showEvent(event)
        self._ensure_on_screen()   # PATCH 3.0.1：兜底收回屏幕外浮窗
        _log().debug("浮窗显示")
        if not self._hover_timer.isActive():
            self._hover_timer.start()
        # 同步余额角标
        self._sync_api_panel_position()
        if self._api_badge:
            self._api_badge.show()

    def moveEvent(self, event):
        """移动时同步余额角标位置"""
        super().moveEvent(event)
        self._sync_api_panel_position()

    def hideEvent(self, event):
        """隐藏时停止 hover 检测以节省 CPU"""
        super().hideEvent(event)
        _log().debug("浮窗隐藏")
        self._hover_timer.stop()
        self._hover_open_timer.stop()
        self._long_press_timer.stop()
        self._close_radial_menu()
        # 重置 hover 状态
        if self.is_hovered:
            self.is_hovered = False
            self._animate_scale(1.0, MotionTokens.SPEED)
        if self._api_badge:
            self._api_badge.hide()

    # ── 按压 + 涟漪属性 ────────────────────────────
    def _tick_ripple(self):
        self._ripple_progress += 0.04
        if self._ripple_progress >= 1.0:
            self._ripple_progress = 0.0
            self._ripple_timer.stop()
        self.update()


    def _apply_opacity(self):
        self.setWindowOpacity(max(0.3, min(1.0, self.config.get("opacity", 0.88))))

    def rebuild_theme(self, theme):
        """切换主题：更新配色缓存 → 重建绘制资源 → 重绘"""
        self.theme = theme
        self.config["theme"] = theme
        self._render_pixmaps()
        self.update()
        self.theme_changed.emit(theme)
        # 同步余额角标主题
        if self._api_badge:
            self._api_badge.set_theme(theme)
        _log().info("主题切换为: %s", theme)


    def _animate_scale(self, target, params=None):
        """悬停/按压视觉缩放（弹簧驱动；仅重绘，不改变窗口几何）"""
        if self._scale_cancel is not None:
            self._scale_cancel()
            self._scale_cancel = None
        self._scale_state.set_params(*(params or MotionTokens.SPEED))
        self._scale_cancel = motion().animate_to(
            self._scale_state, float(target), self._on_scale_change)

    def _on_scale_change(self, v):
        self._visual_scale = float(v)
        self.update()

    @pyqtProperty(int)
    def widget_size_prop(self):
        return self.current_size

    @widget_size_prop.setter
    def widget_size_prop(self, v):
        if v == self.current_size:
            return
        old_center = self.geometry().center()
        self.current_size = v
        self.setFixedSize(self._window_side(), self._window_side())
        self._update_mask()
        self._render_pixmaps()
        ng = self.frameGeometry()
        ng.moveCenter(old_center)
        self.move(ng.topLeft())
        self.update()

    def _screen_rects(self):
        """所有屏幕的可用区域（逻辑坐标，右下为闭区间，与 QRect 一致）"""
        out = []
        for s in QApplication.screens():
            g = s.availableGeometry()
            out.append((g.left(), g.top(), g.right(), g.bottom()))
        return out

    def _restore_position(self):
        off = int(self._ball_offset())
        size = self.current_size
        screens = self._screen_rects()

        x, y = self.config.get("window_x", -1), self.config.get("window_y", -1)
        # 配置坐标按「球体坐标」解释，换算为窗口坐标（窗口含四周留白）
        if x < 0 or y < 0:
            if screens:
                l, t, r, b = screens[0]
                x = r - size - EDGE_MARGIN
                y = (t + b) // 2 - size // 2
            else:
                x, y = 100, 100

        # PATCH 3.0.1：保存坐标可能因换屏/DPI 缩放越界——先收敛到可见屏幕，
        # 避免浮窗落在屏幕外「失踪」且无法唤出扇形菜单
        x, y = clamp_visible(x, y, size, screens)

        edge = normalize_edge(self.config.get("snap_edge")) \
            if self.config.get("snap_enabled", True) else ""
        if edge and screens:
            idx = screen_index_for(x + size / 2.0, y + size / 2.0, screens)
            x, y = edge_position(edge, x, y, size, screens[idx])

        self.move(int(x - off), int(y - off))

        if edge:
            self._snapped = True
            self._snap_edge = edge
            # 吸附 + 自动隐藏：初始化隐藏状态（滑出后仍留可见小标签）
            if self.config.get("snap_hidden", True):
                self._setup_edge_detector()
                self._do_hide()
        else:
            # 自由位置（含非法 snap_edge）：保持完全可见，不进入吸附隐藏
            self._snapped = False
            self._snap_edge = ""

    def _ensure_on_screen(self):
        """窗口完全落在所有屏幕之外时，收回到可见区域（PATCH 3.0.1 安全网）"""
        screens = self._screen_rects()
        if not screens:
            return
        r = self.geometry()
        visible = 0
        for (l, t, rr, b) in screens:
            w = min(r.right(), rr) - max(r.left(), l) + 1
            h = min(r.bottom(), b) - max(r.top(), t) + 1
            if w > 0 and h > 0:
                visible = max(visible, min(w, h))
        if visible >= 4:
            return
        off = int(self._ball_offset())
        x, y = clamp_visible(self.pos().x() + off, self.pos().y() + off,
                             self.current_size, screens)
        self.move(int(x - off), int(y - off))
        _log().warning("浮窗曾完全处于屏幕外，已收回到可见区域: (%d, %d)", x, y)

    def reset_position(self):
        """应急恢复：移回主屏右边缘中部并保持可见（托盘菜单入口）"""
        screens = self._screen_rects()
        if not screens:
            return
        l, t, r, b = screens[0]
        size = self.current_size
        x = r - size - EDGE_MARGIN
        y = (t + b) // 2 - size // 2
        off = int(self._ball_offset())
        self._snapped = False
        self._snap_edge = ""
        self.config["snap_edge"] = ""
        self.config["window_x"], self.config["window_y"] = int(x), int(y)
        self.move(int(x - off), int(y - off))
        self.show()
        self.raise_()
        save_config(self.config)
        _log().info("浮窗位置已重置: (%d, %d)", x, y)

    # ── 边缘吸附系统 ────────────────────────────────
    def _screen_geometry(self):
        """获取当前屏幕的工作区域"""
        screen = QApplication.screenAt(self.pos()) or QApplication.primaryScreen()
        if screen:
            return screen.availableGeometry()
        return QRect(0, 0, 1920, 1080)

    def _check_snap(self):
        """检测拖拽后是否应吸附到屏幕边缘"""
        if not self.config.get("snap_enabled", True):
            return

        SNAP_THRESHOLD = 25
        g = self._screen_geometry()
        off = self._ball_offset()
        cx = int(self.pos().x() + off + self.current_size // 2)
        cy = int(self.pos().y() + off + self.current_size // 2)

        # 检测距离每个边缘的距离
        dist_left = cx - g.left()
        dist_right = g.right() - cx
        dist_top = cy - g.top()
        dist_bottom = g.bottom() - cy

        nearest = min(
            (dist_left, "left"), (dist_right, "right"),
            (dist_top, "top"), (dist_bottom, "bottom"), key=lambda d: d[0]
        )

        if nearest[0] < SNAP_THRESHOLD + self.current_size // 2:
            edge = nearest[1]
            self._snapped = True
            self._snap_edge = edge
            self.config["snap_edge"] = edge

            # 吸附到边缘
            if edge == "left":
                new_x = g.left() + 2 - off
                new_y = max(g.top(), min(g.bottom() - self.current_size, self.pos().y() + off)) - off
            elif edge == "right":
                new_x = g.right() - self.current_size - 2 - off
                new_y = max(g.top(), min(g.bottom() - self.current_size, self.pos().y() + off)) - off
            elif edge == "top":
                new_x = max(g.left(), min(g.right() - self.current_size, self.pos().x() + off)) - off
                new_y = g.top() + 2 - off
            else:  # bottom
                new_x = max(g.left(), min(g.right() - self.current_size, self.pos().x() + off)) - off
                new_y = g.bottom() - self.current_size - 2 - off

            self.move(int(new_x), int(new_y))
            save_config(self.config)

            # 自动隐藏
            if self.config.get("snap_hidden", True):
                self._setup_edge_detector()
                self._hide_timer.start(600)
        else:
            self._snapped = False
            self._snap_edge = ""
            self._remove_edge_detector()
            self.config["snap_edge"] = ""
            _log().debug("脱离吸附")
            save_config(self.config)

    def _setup_edge_detector(self):
        """创建屏幕边缘的透明检测窗口（吸附边非法时不创建）"""
        self._remove_edge_detector()
        edge = self._snap_edge
        if edge not in VALID_EDGES:
            return
        g = self._screen_geometry()
        sz = self.current_size
        off = int(self._ball_offset())
        ball_x, ball_y = self.pos().x() + off, self.pos().y() + off

        # 必须子类化才能正确重写 C++ 虚函数 enterEvent
        parent_widget = self

        class HoverDetector(QWidget):
            def enterEvent(self_2, event):
                parent_widget._on_edge_detected()

        detector = HoverDetector()
        detector.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        detector.setAttribute(Qt.WA_TranslucentBackground)
        detector.setAttribute(Qt.WA_ShowWithoutActivating)
        detector.setStyleSheet("background: transparent;")
        detector.setMouseTracking(True)

        # 检测条：沿屏幕边缘 10px 宽（P2 由 6px 加宽，命中更容易）
        if edge == "right":
            detector.setGeometry(g.right() - 10, ball_y - 12, 10, sz + 24)
        elif edge == "left":
            detector.setGeometry(g.left(), ball_y - 12, 10, sz + 24)
        elif edge == "top":
            detector.setGeometry(ball_x - 12, g.top(), sz + 24, 10)
        else:  # bottom
            detector.setGeometry(ball_x - 12, g.bottom() - 10, sz + 24, 10)

        detector.show()
        self._edge_detector = detector

    def _remove_edge_detector(self):
        if self._edge_detector:
            try:
                self._edge_detector.close()
                self._edge_detector.deleteLater()
            except Exception:
                pass
            self._edge_detector = None

    def _on_edge_detected(self):
        """鼠标靠近隐藏的吸附边缘，滑出显示"""
        self._hide_timer.stop()
        if self._snapped:
            self._show_full()

    def _do_hide(self):
        """将 widget 滑出屏幕（仅留一小部分可见）"""
        if not self._snapped or self._snap_edge not in VALID_EDGES:
            return
        # 环绕菜单打开 / 拖拽期间绝不缩回
        if self._drag_active:
            return
        if self._radial_menu is not None and self._radial_menu.isVisible():
            return
        g = self._screen_geometry()
        s = self.current_size
        edge = self._snap_edge
        visible_tab = 6  # 留在屏幕内的像素
        off = self._ball_offset()

        if edge == "right":
            target = g.right() - visible_tab - off
        elif edge == "left":
            target = g.left() - s + visible_tab - off
        elif edge == "top":
            target = g.top() - s + visible_tab - off
        else:  # bottom
            target = g.bottom() - visible_tab - off

        self._hidden_offset = target
        self._hidden_now = True
        self._animate_slide(target, edge)
        if self._api_badge:
            self._api_badge.hide()
        # 隐藏后重建边缘检测器（显示时会被移除），供下次鼠标靠近时唤起
        self._setup_edge_detector()

    def _show_full(self):
        """将 widget 完全滑入屏幕"""
        if not self._snapped or self._snap_edge not in VALID_EDGES:
            return
        # 环绕菜单打开时：浮窗已被临时移到环心对齐位置，不能移动它；
        # 只确保不缩回，避免「菜单还开着、浮窗却缩回/错位」。
        if self._radial_menu is not None and self._radial_menu.isVisible():
            self._hide_timer.stop()
            return
        g = self._screen_geometry()
        s = self.current_size
        edge = self._snap_edge
        off = self._ball_offset()

        if edge == "right":
            target = g.right() - s - 2 - off
        elif edge == "left":
            target = g.left() + 2 - off
        elif edge == "top":
            target = g.top() + 2 - off
        else:
            target = g.bottom() - s - 2 - off

        self._hidden_now = False
        self._interaction.notify_reveal(time.monotonic())
        self._animate_slide(target, edge)
        if self._api_badge:
            self._api_badge.show()
        # 弹出后移除边缘检测器：避免它盖住浮窗（尤其贴边的小标签页）拦截点击/拖拽
        self._remove_edge_detector()
        # 拖拽中不调度自动隐藏
        if self._drag_active:
            self._hide_timer.stop()
            return
        # 设置延迟重新隐藏
        self._hide_timer.start(self.config.get("hide_delay_ms", 800))

    def _reveal_now(self):
        """吸附隐藏状态下：立即弹出到完全可见位置（供按压 / 打开菜单前调用）。

        不使用动画，确保后续操作（点击启动、环绕菜单圆心）落在屏幕内。
        """
        if not (self._snapped and self._hidden_now):
            return
        g = self._screen_geometry()
        s = self.current_size
        edge = self._snap_edge
        off = self._ball_offset()
        if edge == "right":
            self.move(int(g.right() - s - 2 - off), self.pos().y())
        elif edge == "left":
            self.move(int(g.left() + 2 - off), self.pos().y())
        elif edge == "top":
            self.move(self.pos().x(), int(g.top() + 2 - off))
        else:  # bottom
            self.move(self.pos().x(), int(g.bottom() - s - 2 - off))
        if self._slide_anim is not None:
            self._slide_anim.stop()
        self._hide_timer.stop()
        self._hidden_now = False
        self._interaction.notify_reveal(time.monotonic())
        # 弹出后移除边缘检测器，避免盖住浮窗拦截按压/拖拽
        self._remove_edge_detector()
        if self._api_badge:
            self._api_badge.show()
        _log().debug("吸附隐藏状态下立即弹出: edge=%s", edge)

    def _auto_hide(self):
        """计时器触发：自动隐藏（菜单打开 / 拖拽中不隐藏）"""
        if not (self._snapped and not self.is_hovered):
            return
        if self._drag_active:
            return
        if self._radial_menu is not None and self._radial_menu.isVisible():
            return
        self._do_hide()

    def _animate_slide(self, target, edge):
        """滑动动画"""
        anim = QPropertyAnimation(self, b"slide_pos")
        anim.setDuration(120)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.setStartValue(self.pos().x() if edge in ("left", "right") else self.pos().y())
        anim.setEndValue(target)
        anim.start()
        # 保持引用防止被垃圾回收
        self._slide_anim = anim

    @pyqtProperty(int)
    def slide_pos(self):
        return self.pos().x() if self._snap_edge in ("left", "right") else self.pos().y()

    @slide_pos.setter
    def slide_pos(self, v):
        if self._snap_edge == "left" or self._snap_edge == "right":
            self.move(int(v), self.pos().y())
        elif self._snap_edge in ("top", "bottom"):
            self.move(self.pos().x(), int(v))

    def _check_hover(self):
        if self._quitting:
            return
        # 高分屏下 mapFromGlobal 可能返回 2 倍偏移坐标，导致悬停检测错乱；
        # 顶层窗口 pos() 即全局坐标，直接用 QCursor.pos() - pos() 计算本地坐标
        local_pos = QCursor.pos() - self.pos()
        was = self.is_hovered
        off = self._ball_offset()
        self.is_hovered = QRectF(off, off, self.current_size, self.current_size).contains(
            QPointF(local_pos))
        now = time.monotonic()

        # 吸附模式下自动管理显示/隐藏
        menu_open = self._radial_menu is not None and self._radial_menu.isVisible()
        if self._snapped and self.config.get("snap_hidden", True):
            if self.is_hovered and not was:
                self._show_full()
            elif not self.is_hovered and was:
                if menu_open or self._drag_active:
                    # 环绕菜单打开 / 拖拽期间不缩回
                    self._hide_timer.stop()
                else:
                    self._hide_timer.start(self.config.get("hide_delay_ms", 800))

        if self.is_hovered and not was:
            _log().debug("悬停进入: local=%s scale=%.2f", local_pos, HOVER_SCALE)
            self._interaction.hover_enter(now)
            self._animate_scale(HOVER_SCALE, MotionTokens.SPEED)
            # 悬停展开（状态机裁决：按压/拖拽/菜单打开期间与三类冷却窗口内均不启动）
            if self._interaction.hover_open_allowed(now):
                self._hover_open_timer.start(self._interaction.hover_delay_ms)
        elif not self.is_hovered and was:
            _log().debug("悬停离开")
            self._interaction.hover_leave(now)
            self._animate_scale(1.0, MotionTokens.SPEED)
            self._hover_open_timer.stop()
            # 环绕菜单打开时不立即关闭：由菜单自身的宽限/点击外部逻辑处理
            if self._radial_menu is None or not self._radial_menu.isVisible():
                self._close_radial_menu()

    # ── 环绕菜单（悬停 / 长按双通道，状态机裁决）────────
    def _on_hover_open_fired(self):
        acts = self._interaction.hover_timer_fired(time.monotonic())
        if InteractionActions.OPEN_MENU in acts:
            self._open_radial_menu("hover")

    def _on_long_press_fired(self):
        acts = self._interaction.long_press_fired(time.monotonic())
        if InteractionActions.OPEN_MENU in acts:
            self._open_radial_menu("long_press")

    def _open_radial_menu(self, source):
        self._hover_open_timer.stop()
        self._long_press_timer.stop()
        if not self._radial_cfg.get("enabled", True):
            return
        # 防御：拖拽中绝不弹菜单（冷却窗口由状态机裁决）
        if self._drag_active:
            return
        # 吸附隐藏状态：先弹出到完全可见位置，避免菜单圆心在屏幕外
        if self._snapped and self._hidden_now:
            self._reveal_now()
        # 菜单打开期间禁止自动缩回
        self._hide_timer.stop()
        items = self._build_radial_items()
        if self._radial_menu is None:
            self._radial_menu = RadialMenu()
            self._radial_menu.action_triggered.connect(self._on_radial_action)
            self._radial_menu.closed.connect(self._on_radial_menu_closed)
            self._radial_menu.center_clicked.connect(self._on_radial_center_clicked)
        if self._radial_menu.isVisible():
            # 已在显示中：避免重复触发导致动画反复重启（抽搐）
            return
        self._radial_menu.set_theme(self.theme)
        radius = int(self._radial_cfg.get("radius", 120))
        self._radial_menu.set_items(items, radius=radius)
        center = self.geometry().center()
        _log().debug("环绕菜单打开: source=%s items=%d center=%s", source, len(items), center)
        # 吸附贴边时：环心受屏幕钳制后可能偏离浮窗中心，先把浮窗临时移到环心，
        # 保证「浮窗位于圆环正中」，菜单关闭后再恢复原吸附位置
        self._snap_menu_restore = None
        if self._snapped:
            side = int((radius + RADIAL_PAD) * 2)
            g = self._screen_geometry()
            cx, cy = center.x(), center.y()
            if side < g.width():
                cx = max(g.left() + side / 2.0, min(cx, g.right() - side / 2.0))
            if side < g.height():
                cy = max(g.top() + side / 2.0, min(cy, g.bottom() - side / 2.0))
            if abs(cx - center.x()) > 1 or abs(cy - center.y()) > 1:
                self._snap_menu_restore = self.pos()
                self.move(int(cx - self.width() / 2.0), int(cy - self.height() / 2.0))
                center = self.geometry().center()
        self._interaction.menu_opened(time.monotonic())
        # 顶层窗口 geometry() 即全局坐标，直接作为菜单圆心（避免 mapToGlobal 高分屏偏移）
        self._radial_menu.open_at(
            center,
            anchor_rect=QRect(self.pos(), self.size()))
        # 环绕菜单打开时隐藏余额角标，避免重叠遮挡
        if self._api_badge:
            self._api_badge.hide()

    def _close_radial_menu(self):
        self._interaction.menu_closed(time.monotonic())
        if self._radial_menu is not None:
            self._radial_menu.close_menu()
        self._restore_snap_position()
        self._maybe_arm_hide()
        self._restore_balance_badge()

    def _on_radial_menu_closed(self):
        # 菜单自行关闭（宽限/点击外部）后恢复余额角标
        self._interaction.menu_closed(time.monotonic())
        self._restore_snap_position()
        self._maybe_arm_hide()
        self._restore_balance_badge()

    def _restore_snap_position(self):
        """环绕菜单关闭后：把临时移位的浮窗恢复到吸附位置"""
        r = getattr(self, "_snap_menu_restore", None)
        self._snap_menu_restore = None
        if r is not None:
            self.move(r)

    def _maybe_arm_hide(self):
        """菜单 / 拖拽结束后：若仍处于吸附隐藏模式且鼠标不在浮窗上，重新调度自动隐藏"""
        if not (self._snapped and self.config.get("snap_hidden", True)):
            return
        if self.is_hovered or self._drag_active:
            return
        if self._radial_menu is not None and self._radial_menu.isVisible():
            return
        self._hide_timer.start(self.config.get("hide_delay_ms", 800))

    def _restore_balance_badge(self):
        if (self._api_badge is not None and self.isVisible()
                and (self.config.get("api_monitor") or {}).get("enabled")):
            self._api_badge.show()

    def _build_radial_items(self):
        """按配置构建扇区菜单项（模块化：用户可自选每个扇区功能）"""
        cfg = self._radial_cfg or {}
        slots = cfg.get("slots") or []
        items = []
        if slots:
            for action in slots:
                it = self._radial_item_for(action)
                if it is not None:
                    items.append(it)
            if items:
                return items
        # 旧配置/空配置回退：所有 Agent + 固定功能
        for a in self._agents:
            items.append(RadialMenuItem(
                "agent:%s" % a.get("id"), a.get("name"),
                a.get("command", ""), a.get("icon_color", "#5B8DEF"),
                a.get("icon_char", "A")))
        items.append(RadialMenuItem("skills", "Skills", "辅助窗", "#8E44AD", "S"))
        items.append(RadialMenuItem("api", "API 用量", "余额监控", "#16A085", "¥"))
        items.append(RadialMenuItem("settings", "设置", "偏好", "#5B8DEF", "⚙"))
        items.append(RadialMenuItem("quit", "退出", "AgentFloat", "#E74C3C", "✕"))
        return items

    def _radial_item_for(self, action):
        """将配置中的动作 id 转换为 RadialMenuItem；无效动作返回 None"""
        if isinstance(action, dict):
            action = action.get("action") or ""
        action = str(action or "").strip()
        if action.startswith("agent:"):
            agent = find_agent(self._agents, action[6:])
            if not agent:
                return None
            return RadialMenuItem(action, agent.get("name") or "Agent",
                                  agent.get("command", ""),
                                  agent.get("icon_color", "#5B8DEF"),
                                  agent.get("icon_char", "A"))
        if action.startswith("launch:"):
            agent = find_agent(self._agents, action[7:])
            if not agent:
                return None
            return RadialMenuItem("agent:%s" % agent.get("id"),
                                  agent.get("name") or "Agent",
                                  agent.get("command", ""),
                                  agent.get("icon_color", "#5B8DEF"),
                                  agent.get("icon_char", "A"))
        labels = {
            "skills": ("Skills", "辅助窗", "#8E44AD", "S"),
            "api": ("API 余额", "用量监控", "#16A085", "¥"),
            "settings": ("设置", "偏好", "#5B8DEF", "⚙"),
            "news": ("AI 快报", "每日资讯", "#2E86C1", "N"),
            "clip": ("剪贴板", "历史记录", "#E67E22", "C"),
            "cmd": ("命令", "命令面板", "#27AE60", "⌘"),
            "water": ("喝水", "喝水助手", "#00A6A6", "水"),
            "quit": ("退出", "AgentFloat", "#E74C3C", "✕"),
        }
        if action in labels:
            label, sub, color, char = labels[action]
            return RadialMenuItem(action, label, sub, color, char)
        return None

    def _on_radial_center_clicked(self):
        """点击环绕菜单中心孔 → 视为点击浮窗，快捷启动主 Agent"""
        self._close_radial_menu()
        self.launch_requested.emit()

    def _on_radial_action(self, action_id):
        if action_id.startswith("agent:"):
            agent = find_agent(self._agents, action_id[6:])
            if agent:
                launch_agent(agent, self.config)
        elif action_id == "skills":
            self._open_skills_panel()
        elif action_id == "api":
            web_ui.open_window("#/api")
        elif action_id == "settings":
            self.settings_requested.emit()
        elif action_id == "news":
            self._open_news_panel()
        elif action_id == "clip":
            self._open_clipboard_panel()
        elif action_id == "cmd":
            self._open_command_panel()
        elif action_id == "water":
            self._open_water_panel()
        elif action_id == "quit":
            self._animate_quit()

    def _open_skills_panel(self):
        """Open Skills panel non-modally so the floating widget stays interactive"""
        panel = getattr(self, "_skills_panel", None)
        if panel is not None and panel.isVisible():
            panel.raise_()
            panel.activateWindow()
            return
        panel = SkillsPanel(self._skills_cfg, theme=self.theme, parent=self)
        panel.finished.connect(lambda _r: self._clear_skills_panel_ref(panel))
        self._skills_panel = panel
        panel.show()

    def _clear_skills_panel_ref(self, panel):
        if getattr(self, "_skills_panel", None) is panel:
            self._skills_panel = None

    # ── 剪贴板历史 ──────────────────────────────────
    def _clipboard_tick(self):
        """轮询剪贴板（QClipboard.dataChanged 在部分环境下不可靠），写入历史"""
        try:
            txt = QApplication.clipboard().text()
        except Exception:
            return
        if txt and txt != self._last_clip_text:
            self._last_clip_text = txt
            self._clipboard.push(txt)
            save_config(self.config)

    def _open_clipboard_panel(self):
        """打开剪贴板历史面板（点击条目复制回剪贴板）"""
        dlg = ClipboardPanel(self._clipboard, theme=self.theme, parent=self)

        def _on_copy(text):
            self._last_clip_text = text
            self._clipboard.push(text)
            save_config(self.config)

        dlg.copied.connect(_on_copy)
        dlg.finished.connect(lambda _r: self._clear_clip_panel_ref(dlg))
        self._clip_panel = dlg
        dlg.show()

    def _clear_clip_panel_ref(self, panel):
        if getattr(self, "_clip_panel", None) is panel:
            self._clip_panel = None

    # ── 自定义命令面板 ──────────────────────────────
    def _open_command_panel(self):
        """打开自定义命令面板（新建/编辑/删除/运行）"""
        dlg = CommandPanel(self._commands, theme=self.theme, parent=self)
        dlg.commands_changed.connect(self._on_commands_changed)
        dlg.finished.connect(lambda _r: self._clear_cmd_panel_ref(dlg))
        self._cmd_panel = dlg
        dlg.show()

    def _clear_cmd_panel_ref(self, panel):
        if getattr(self, "_cmd_panel", None) is panel:
            self._cmd_panel = None

    def _on_commands_changed(self, cmds):
        self._commands = [dict(c) for c in cmds]
        self.config["commands"] = self._commands
        save_config(self.config)

    # ── AI 快报 ────────────────────────────────────
    # —— 喝水助手 ————————————————————————
    def _open_water_panel(self):
        """打开喝水助手面板（环绕菜单 / 托盘入口）"""
        panel = getattr(self, "_water_panel", None)
        if panel is not None and panel.isVisible():
            panel.raise_()
            panel.activateWindow()
            return
        panel = WaterPanel(self._water_mgr, theme=self.theme, parent=self)
        panel.open_settings_requested.connect(self.settings_requested.emit)
        panel.finished.connect(lambda _r: self._clear_water_panel_ref(panel))
        self._water_panel = panel
        panel.show()

    def _clear_water_panel_ref(self, panel):
        """喝水助手面板关闭后清除引用，允许再次打开"""
        if getattr(self, "_water_panel", None) is panel:
            self._water_panel = None

    def _on_water_timer_finished(self, tid):
        """计时结束：按配置选择提醒形态，并支持前台进程豁免"""
        try:
            cfg = self._water_cfg or {}
            if not cfg.get("enabled", True):
                return
            t = self._water_mgr.timer_info(tid)
            if not t:
                return
            message = self._water_mgr.pick_message(tid)
            # 进程豁免：游戏 / 全屏应用进行中不打断
            if is_exempt_process(cfg.get("exempt_processes")):
                behavior = cfg.get("exempt_behavior", "tray")
                self._water_mgr.confirm_timer(tid)
                if behavior != "silent":
                    self.water_reminded.emit("检测到豁免进程，已静默顺延：%s" % t["name"])
                return
            mode = cfg.get("reminder_mode", "fullscreen")
            if mode == "tray":
                self._water_mgr.confirm_timer(tid)
                self.water_reminded.emit("%s时间到：%s" % (t["name"], message))
                return
            popup = WaterReminderPopup(
                t, message, theme=self.theme,
                fullscreen=(mode == "fullscreen"),
                sound=bool(cfg.get("sound", True)), parent=self)
            popup.confirmed.connect(lambda _tid=tid: self._water_mgr.confirm_timer(_tid))
            popup.snoozed.connect(lambda _tid=tid: self._water_mgr.snooze_timer(_tid))
            popup.finished.connect(lambda _p=popup: self._water_popups.pop(id(_p), None))
            self._water_popups[id(popup)] = popup
            popup.show_on_screen(self._screen_for_reminder(cfg))
            _log().info("喝水助手提醒: %s (mode=%s)", tid, mode)
        except Exception:
            _log().warning("喝水助手提醒失败", exc_info=True)

    def _screen_for_reminder(self, cfg):
        """确定提醒弹窗所在屏幕：-1 跟随浮窗，0..n 指定屏幕"""
        try:
            idx = int(cfg.get("screen_index") or -1)
            screens = QApplication.screens()
            if not screens:
                return None
            if idx >= 0 and idx < len(screens):
                return screens[idx]
            for sc in screens:
                if sc.geometry().contains(self.geometry().center()):
                    return sc
            return screens[0]
        except Exception:
            return None

    def _open_news_panel(self):
        """打开 AI 快报（Web 壳页面，清除未读红点）"""
        self._mark_news_read()
        web_ui.open_window("#/news")

    def _place_news_panel(self, panel):
        """把快报面板放到浮窗附近，且完整落在屏幕内"""
        try:
            g = self._screen_geometry()
            pw, ph = panel.width(), panel.height()
            x = self.geometry().left() - pw - 12
            if x < g.left():
                x = self.geometry().right() + 12
            x = max(g.left(), min(x, g.right() - pw))
            y = max(g.top(), min(self.geometry().center().y() - ph // 2, g.bottom() - ph))
            panel.move(x, y)
        except Exception:
            _log().warning("放置快报面板失败", exc_info=True)

    def _clear_news_panel_ref(self, panel):
        if self._news_panel is panel:
            self._news_panel = None

    def _mark_news_read(self):
        if self._news_unread:
            self._news_unread = 0
            self._news_cfg["unread_count"] = 0
            self.config["news"] = self._news_cfg
            save_config(self.config)
            self.update()

    def _generate_news(self, auto=False, pop_panel=False):
        """手动/定时/启动补生成 AI 快报（后台线程，防重入）

        pop_panel: 生成完成后自动弹出快报面板（仅启动补生成时使用）"""
        self._news_pop_after = pop_panel
        if self._news_generating or (self._news_worker is not None and self._news_worker.isRunning()):
            _log().info("AI 快报生成中，忽略重复触发")
            return
        cfg = self._news_cfg or {}
        if not cfg.get("sources"):
            if not auto:
                QMessageBox.warning(None, "AI 快报", "未启用任何数据源，请在「设置 → AI 快报」中勾选。")
            return
        agent = None
        if cfg.get("use_ai", True):
            agent = get_primary_agent(self._agents)
            if not agent:
                if not auto:
                    QMessageBox.warning(None, "AI 快报",
                                        "未配置主 Agent，无法生成 AI 摘要。\n"
                                        "可在设置中关闭「使用本地 AI 生成摘要」改用标题列表。")
                return
        self._news_generating = True
        _bridge = getattr(self, "_web_bridge", None)
        if _bridge is not None:
            _bridge.set_snapshot("news_generating", True)
            _bridge.set_snapshot("news_phase", "抓取数据源…")
            _bridge.publish("news_started", {})
        if self._news_panel is not None and self._news_panel.isVisible():
            self._news_panel.set_generating(True)
        worker = NewsWorker(cfg, self._agents, parent=self)
        track(worker, "NewsWorker")
        worker.done.connect(self._on_news_done)
        worker.failed.connect(self._on_news_failed)
        self._news_worker = worker
        worker.start()
        _log().info("AI 快报生成启动 (auto=%s, sources=%s, ai=%s)",
                     auto, cfg.get("sources"), bool(cfg.get("use_ai", True)))

    def _on_news_done(self, payload):
        self._release_worker_attr("_news_worker")
        self._news_generating = False
        date = payload.get("date", "")
        count = payload.get("count", 0)
        used_ai = payload.get("used_ai", False)
        _log().info("AI 快报生成完成: %s (%d 条, ai=%s)", date, count, used_ai)
        cfg = dict(self._news_cfg or {})
        cfg["last_generated"] = payload.get("generated_at", "")
        cfg["unread_count"] = int(cfg.get("unread_count") or 0) + 1
        self._news_unread = cfg["unread_count"]
        self._news_cfg = cfg
        self.config["news"] = cfg
        save_config(self.config)
        self.update()
        _bridge = getattr(self, "_web_bridge", None)
        if _bridge is not None:
            _bridge.set_snapshot("news_report", payload)
            _bridge.set_snapshot("news_generating", False)
            _bridge.publish("news_done", {"date": date, "count": count, "used_ai": used_ai})
        if self._news_panel is not None and self._news_panel.isVisible():
            self._news_panel.on_generated(payload)
            self._news_panel.set_generating(False)
        if cfg.get("notify", True):
            mode = "AI 摘要" if used_ai else "标题列表"
            self.news_done.emit("今日 AI 快报已生成（%s，%d 条，%s）" % (date, count, mode))
        # 自动弹出快报窗口（默认开启，可在设置关闭）
        pop = bool(getattr(self, "_news_pop_after", False))
        self._news_pop_after = False
        if pop and cfg.get("auto_show_panel", True):
            QTimer.singleShot(500, self._open_news_panel)

    def _on_news_failed(self, err):
        self._release_worker_attr("_news_worker")
        self._news_generating = False
        _log().warning("AI 快报生成失败: %s", err)
        _bridge = getattr(self, "_web_bridge", None)
        if _bridge is not None:
            _bridge.set_snapshot("news_generating", False)
            _bridge.publish("news_failed", {"error": str(err)})
        if self._news_panel is not None and self._news_panel.isVisible():
            self._news_panel.set_generating(False)
        self.news_failed.emit(str(err))

    def _setup_news_scheduler(self):
        """按配置启动/停止定时检查（60s 心跳，到点且当日未生成则触发）"""
        cfg = self._news_cfg or {}
        if cfg.get("enabled"):
            self._news_check_timer.start()
            QTimer.singleShot(8000, self._news_startup_check)
        else:
            self._news_check_timer.stop()

    def _news_startup_check(self):
        """启动补生成：当日未生成且模式含 startup 时自动生成"""
        if not (self._news_cfg or {}).get("enabled"):
            return
        mode = (self._news_cfg or {}).get("schedule_mode", "daily_startup")
        if mode in ("startup", "daily_startup") and not today_news_exists():
            _log().info("启动补生成：今日快报尚未生成，自动触发")
            self._generate_news(auto=True, pop_panel=True)

    def _news_timer_tick(self):
        """每日定时检查（每分钟心跳，命中定时点且当日未生成则触发）"""
        cfg = self._news_cfg or {}
        if not cfg.get("enabled"):
            return
        mode = cfg.get("schedule_mode", "daily_startup")
        if mode not in ("daily", "daily_startup"):
            return
        if today_news_exists():
            return
        try:
            hh, mm = str(cfg.get("schedule_time", "09:00")).split(":")
            target = (int(hh), int(mm))
        except Exception:
            return
        now = time.localtime()
        if (now.tm_hour, now.tm_min) == target:
            _log().info("每日定时触发 AI 快报生成 (%02d:%02d)", target[0], target[1])
            self._generate_news(auto=True, pop_panel=True)

    def _show_api_summary(self):
        results = getattr(self, "_api_last_results", [])
        if not results:
            QMessageBox.information(
                None, "API 用量",
                "暂无用量数据。\n\n请先在「设置 → API 用量监控」中启用监控并等待轮询。")
            return
        lines = ["各 API 用量情况：", ""]
        for r in results:
            name = getattr(r, "endpoint_name", None) or "?"
            fields = getattr(r, "fields", None) or []
            if fields and fields[0].get("label") == "错误":
                lines.append("• %s：查询失败（%s）" % (name, fields[0].get("value", "")))
                continue
            parts = []
            for f in fields:
                v = f.get("value")
                if v is None:
                    continue
                try:
                    vtxt = "%.2f%s" % (float(v), f.get("unit", ""))
                except (TypeError, ValueError):
                    vtxt = "%s%s" % (v, f.get("unit", ""))
                parts.append("%s %s" % (f.get("label", ""), vtxt))
            lines.append("• %s：%s" % (name, "，".join(parts) or "无字段"))
        QMessageBox.information(None, "API 用量", "\n".join(lines))

    def _open_api_platform(self):
        """点击扇形「API 余额」→ 打开对应 API 平台网页（默认浏览器）"""
        import webbrowser
        endpoints = (self.config.get("api_monitor") or {}).get("endpoints") or []
        url = ""
        for ep in endpoints:
            url = (ep.get("platform_url") or "").strip()
            if not url:
                # 旧配置可能没有 platform_url：按已知平台名称自动补上
                url = (_ensure_platform_url(ep).get("platform_url") or "").strip()
            if url:
                break
        if url:
            try:
                from api_monitor_config import resolve_url
                webbrowser.open(resolve_url(url))
                _log().debug("打开 API 平台网页: %s", url)
            except Exception as e:
                _log().warning("打开 API 平台网页失败: %s", e)
        else:
            # 未配置平台网页 → 回退到用量摘要
            self._show_api_summary()

    def _animate_quit(self):
        """点击退出：播放全新收拢动画（缩小 + 淡出）后再退出"""
        if self._quitting:
            return
        self._quitting = True
        _log().info("退出动画开始")
        # 关闭环绕菜单与余额角标，停止各计时器
        self._close_radial_menu()
        if self._api_badge:
            self._api_badge.hide()
        if self._launch_toast is not None:
            self._launch_toast.hide()
        self._hover_timer.stop()
        self._hover_open_timer.stop()
        self._long_press_timer.stop()
        # 弹性收拢：整体缩小 + 窗口淡出（弹簧驱动 + 速度继承，收尾不再生硬）
        base_opacity = self.windowOpacity()

        def _apply(v):
            self._visual_scale = v
            self.update()
            self.setWindowOpacity(max(0.0, base_opacity * min(1.0, v / 0.9)))

        if self._scale_cancel is not None:
            self._scale_cancel()
            self._scale_cancel = None
        self._scale_state.jump(self._visual_scale)
        self._scale_state.set_params(*MotionTokens.QUIT)
        motion().animate_to(self._scale_state, 0.08, _apply,
                            on_done=self.quit_requested.emit)

    # ── 绘制（7 层玻璃 + 涟漪 + 指示灯）─────────────────
    def paintEvent(self, event):
        side = self._cache.get("side") or self._window_side()
        scale = self._visual_scale
        if scale <= 0.02:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # 三态位图：idle / hover 预渲染；按压沿用 hover 位图 + 弹簧缩放
        pm = self._cache.get("hover" if (self.is_hovered or self.is_pressed) else "idle")
        if pm is None:
            self._render_pixmaps()
            pm = self._cache.get("idle")
        if pm is None:
            painter.end()
            return
        if abs(scale - 1.0) > 0.004:
            cx = cy = side / 2.0
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)
        painter.drawPixmap(QPointF(0, 0), pm)

        accent = self._cache.get("accent")
        if accent is None:
            accent = QColor(*get_colors(self.theme)["ACCENT"])
        ball_path = self._cache.get("ball_path")
        off = self._ball_offset()
        s = self.current_size

        # 涟漪（裁剪在球体内）
        if self._ripple_progress > 0 and not self._ripple_pos.isNull() and ball_path is not None:
            rp = self._ripple_progress
            r = s * 0.8 * rp
            grad = QRadialGradient(self._ripple_pos, max(1.0, r))
            grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(),
                                        int(60 * (1.0 - rp))))
            grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setBrush(QBrush(grad))
            painter.setPen(Qt.NoPen)
            painter.drawPath(ball_path)

        # 安全模式指示器：skip-permissions 时右上角红点
        if self.config.get("launch_mode") == "skip_permissions":
            dot_r = max(3.5, s * 0.075)
            margin = s * 0.18
            painter.setBrush(QColor(255, 59, 48, 220))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(off + s - margin, off + margin), dot_r, dot_r)

        # 运行中指示器：左下角绿点
        if self._claude_running:
            dot_r = max(3.5, s * 0.065)
            margin = s * 0.18
            painter.setBrush(QColor(52, 199, 89, 220))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(off + margin, off + s - margin), dot_r, dot_r)

        painter.end()

    # ── 鼠标事件（拖拽修复）─────────────────────────
    def mousePressEvent(self, event):
        if self._quitting:
            return
        now = time.monotonic()
        if event.button() == Qt.LeftButton:
            # 吸附隐藏状态：按压即先弹出，保证点击/拖拽落在可见区域
            if self._snapped and self._hidden_now:
                self._reveal_now()
            self._hide_timer.stop()
            self._drag_origin = event.globalPos()
            self._window_origin = self.pos()
            self._drag_active = False
            # 按住即取消悬停展开，避免拖拽时误弹菜单
            self._hover_open_timer.stop()
            self._interaction.press(now)
            # 按压反馈
            self.is_pressed = True
            self._animate_scale(PRESS_SCALE, MotionTokens.PRESS)
        elif event.button() == Qt.RightButton:
            self._context_menu()
            return

        # 长按唤醒环绕菜单（双通道；是否可用由状态机裁决）
        if self._interaction.should_arm_long_press():
            self._long_press_timer.start(self._interaction.long_press_delay_ms)

    def mouseMoveEvent(self, event):
        if self._quitting or not (event.buttons() & Qt.LeftButton):
            return
        delta = (event.globalPos() - self._drag_origin).manhattanLength()
        acts = self._interaction.move(delta, time.monotonic())
        if InteractionActions.BEGIN_DRAG in acts:
            self._drag_active = True
            self._long_press_timer.stop()
            # 拖拽开始：取消悬停展开，并关闭已打开的环绕菜单
            self._hover_open_timer.stop()
            if self._slide_anim is not None:
                self._slide_anim.stop()
            if self._radial_menu is not None and self._radial_menu.isVisible():
                self._close_radial_menu()
        if self._drag_active:
            new_pos = self._window_origin + (event.globalPos() - self._drag_origin)
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        if self._quitting:
            return
        if event.button() == Qt.LeftButton:
            acts = self._interaction.release(time.monotonic())
            if InteractionActions.END_DRAG in acts:
                # 拖拽结束 → 保存位置（球体坐标）+ 检测吸附（状态机已启动 400ms 悬停冷却）
                off = int(self._ball_offset())
                self.config["window_x"] = self.pos().x() + off
                self.config["window_y"] = self.pos().y() + off
                self._check_snap()
                # 无论是否吸附都保存位置
                self.config["window_x"] = self.pos().x() + off
                self.config["window_y"] = self.pos().y() + off
                save_config(self.config)
                _log().debug("拖拽结束，悬停冷却 400ms")
            elif InteractionActions.CLICK in acts:
                # 点击 → 涟漪 + 启动主 Agent
                self._start_ripple(event.pos())
                self.launch_requested.emit()
            self._drag_active = False
            # 同步 API 面板位置
            self._sync_api_panel_position()
            # 松手回弹（弹簧）
            self._animate_scale(HOVER_SCALE if self.is_hovered else 1.0, MotionTokens.PRESS)
        self.is_pressed = False

    def _show_launch_feedback(self):
        """点按即时反馈：浮球旁弹出「启动中」气泡"""
        try:
            primary = get_primary_agent(self._agents)
            name = primary.get("name", "主 Agent") if primary else "主 Agent"
            if self._launch_toast is None:
                self._launch_toast = LaunchToast()
            self._launch_toast.show_for(self, "启动中 · %s" % name, self.theme)
        except Exception as e:  # noqa: BLE001
            _log().debug("启动反馈气泡显示失败: %s", e)

    def _start_ripple(self, pos):
        self._ripple_pos = pos
        self._ripple_progress = 0.01
        self._ripple_timer.start()

    def _context_menu(self):
        tc = get_colors(self.theme)
        sfc = tc["SURFACE"]
        txt = tc["TEXT"]
        acc = tc["ACCENT"]
        sep = tc["SEPARATOR"]
        menu_css = (
            f"QMenu {{ background: rgba({sfc[0]},{sfc[1]},{sfc[2]},0.95);"
            f" border: 1px solid rgba(0,0,0,0.1); border-radius: 10px; padding: 4px 0; }}"
            f"QMenu::item {{ padding: 7px 32px 7px 16px; font-size: 12px;"
            f" color: #{txt[0]:02X}{txt[1]:02X}{txt[2]:02X}; }}"
            f"QMenu::item:selected {{ background: #{acc[0]:02X}{acc[1]:02X}{acc[2]:02X};"
            f" color: #FFF; border-radius: 4px; margin: 1px 6px; }}"
            f"QMenu::separator {{ height: 1px;"
            f" background: #{sep[0]:02X}{sep[1]:02X}{sep[2]:02X}; margin: 4px 8px; }}"
        )
        menu = QMenu(self)
        menu.setStyleSheet(menu_css)

        primary = get_primary_agent(self._agents)
        pname = primary.get("name", "主 Agent") if primary else "主 Agent"
        menu.addAction("启动 %s" % pname, self.launch_requested.emit)
        if len(self._agents) > 1:
            sub = menu.addMenu("启动其他 Agent")
            for a in self._agents:
                if a.get("id") == (primary or {}).get("id"):
                    continue
                sub.addAction(a.get("name"), lambda a=a: launch_agent(a, self.config))
        menu.addAction("Skills 辅助窗", self._open_skills_panel)
        menu.addSeparator()
        menu.addAction("设置...", self.settings_requested.emit)
        menu.addSeparator()

        auto = menu.addAction("开机自启")
        auto.setCheckable(True)
        auto.setChecked(is_auto_start_enabled())
        auto.triggered.connect(lambda checked: toggle_auto_start(checked))

        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)

        menu.exec_(QCursor.pos())

    def closeEvent(self, event):
        self._unregister_hotkey()
        self._close_radial_menu()
        if self._news_worker is not None and self._news_worker.isRunning():
            self._news_worker.cancel()
            self._news_worker.wait(3000)
        if self._api_badge:
            self._api_badge.close()
        if self._launch_toast is not None:
            self._launch_toast.close()
        off = int(self._ball_offset())
        pos = self.pos()
        self.config["window_x"] = pos.x() + off
        self.config["window_y"] = pos.y() + off
        save_config(self.config)
        super().closeEvent(event)

    # ── 应用设置 ────────────────────────────────────
    def apply_settings(self, new_cfg, preview_only=False):
        changed = False
        ns = new_cfg.get("widget_size", self.base_size)
        if ns != self.base_size:
            self.base_size = ns
            self.widget_size_prop = ns
            changed = True

        self.config["opacity"] = new_cfg.get("opacity", 0.88)
        self._apply_opacity()
        self.config["launch_mode"] = new_cfg.get("launch_mode", "normal")
        self.config["working_directory"] = new_cfg.get("working_directory", "")
        self.config["cleanup_on_quit"] = new_cfg.get("cleanup_on_quit", False)
        if new_cfg.get("agents") is not None:
            self._agents = normalize_agents(new_cfg["agents"])
            self.config["agents"] = self._agents
        if new_cfg.get("radial_menu") is not None:
            self._radial_cfg = copy.deepcopy(new_cfg["radial_menu"])
            self.config["radial_menu"] = self._radial_cfg
            self._interaction.configure(self._radial_cfg)
        if new_cfg.get("skills") is not None:
            self._skills_cfg = copy.deepcopy(new_cfg["skills"])
            self.config["skills"] = self._skills_cfg
        if new_cfg.get("news") is not None:
            new_news = copy.deepcopy(new_cfg["news"])
            new_news["unread_count"] = self._news_unread  # 保留当前未读数
            new_news["last_generated"] = (self._news_cfg or {}).get("last_generated", "")
            self._news_cfg = new_news
            self.config["news"] = self._news_cfg
            self._setup_news_scheduler()
            self.update()

        if new_cfg.get("water") is not None:
            old_water = self.config.get("water") or DEFAULT_WATER
            new_water = copy.deepcopy(new_cfg["water"])
            self._water_cfg = new_water
            self.config["water"] = new_water
            if not preview_only and new_water != old_water:
                self._water_mgr.apply_config(new_water)

        # 主题切换
        new_theme = new_cfg.get("theme", "light")
        if new_theme != self.theme:
            self.rebuild_theme(new_theme)
            changed = True

        _log().info("应用设置 (preview=%s): size=%s, opacity=%.2f, mode=%s, theme=%s",
                     preview_only, ns, self.config["opacity"], self.config["launch_mode"], self.theme)

        # 吸附设置
        old_snap = self.config.get("snap_enabled", True)
        old_hidden = self.config.get("snap_hidden", True)
        self.config["snap_enabled"] = new_cfg.get("snap_enabled", True)
        self.config["snap_hidden"] = new_cfg.get("snap_hidden", True)

        if not preview_only:
            self.config["widget_size"] = ns
            off = int(self._ball_offset())
            self.config["window_x"] = self.pos().x() + off
            self.config["window_y"] = self.pos().y() + off

            # API 用量监控配置变更
            new_api_config = new_cfg.get("api_monitor")
            if new_api_config is not None:
                old_api_config = self.config.get("api_monitor", API_MONITOR_DEFAULTS)
                self.config["api_monitor"] = new_api_config
                if new_api_config != old_api_config:
                    _log().info("API 监控配置已变更，重启监控")
                    self._restart_api_monitor()

            save_config(self.config)

            # 吸附设置变更后重新应用
            if self.config["snap_enabled"] != old_snap or self.config["snap_hidden"] != old_hidden:
                if not self.config["snap_enabled"]:
                    self._snapped = False
                    self._remove_edge_detector()
                elif self.config["snap_hidden"] and self._snapped:
                    self._do_hide()
                else:
                    self._show_full()
        if changed:
            self.update()
