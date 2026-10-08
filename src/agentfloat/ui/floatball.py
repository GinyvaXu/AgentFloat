# -*- coding: utf-8 -*-
"""AgentFloat — 浮球主窗口（绘制 / 交互 / 环绕菜单托管 / 面板调度）

P2：交互裁决已抽到 ui/interaction.py（状态机）；绘制走三态 pixmap
预渲染 + 固定窗口位图缩放（悬停/按压动画不重建掩码与缓存）。
"""
import copy
import ctypes
import math
import os
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
from agentfloat.services import webagent
from agentfloat.services.water.reminder import (
    DEFAULT_WATER, WaterTimerManager, is_exempt_process,
)
from agentfloat.ui.panels.clipboard import ClipboardHistory, ClipboardPanel
from agentfloat.ui.panels.command import CommandPanel
from agentfloat.ui.panels.skills import SkillsPanel
from agentfloat.ui.panels.water import WaterPanel, WaterReminderPopup
from agentfloat.core.single_instance import activate_message_id
from agentfloat.core.qtutil import release_thread_later, track
from agentfloat.core.sysutil import _open_url, process_running
from agentfloat.ui.interaction import Actions as InteractionActions, BallInteraction
from agentfloat.ui.motion import Tokens as MotionTokens, motion, spring
from agentfloat.ui.placement import (
    EDGE_MARGIN, VALID_EDGES, clamp_visible, edge_position, normalize_edge,
    ring_room_position, screen_index_for,
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

        # 显示器热插拔 / 分辨率与 DPI 变化（v3.8.0）：防浮窗跑到屏幕外
        self._display_timer = QTimer(self)
        self._display_timer.setSingleShot(True)
        self._display_timer.timeout.connect(self._apply_display_change)
        self._bind_display_signals()

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
        from agentfloat.ui import ball_render
        s = self.current_size
        off = self._ball_offset()
        m = 5.0
        rad = ball_render.ball_radius(s) + m
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
        self._pixmap_dpr = dpr
        cache = {"side": side, "accent": accent}
        for name, hovered in (("idle", False), ("hover", True)):
            pm = QPixmap(int(side * dpr), int(side * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            self._render_ball_pixmap(pm, hovered, accent, side)
            cache[name] = pm
        # 球体路径（涟漪裁剪用）
        from agentfloat.ui import ball_render
        off = self._ball_offset()
        s = self.current_size
        rad = ball_render.ball_radius(s)
        path = QPainterPath()
        path.addRoundedRect(QRectF(off, off, s, s), rad, rad)
        cache["ball_path"] = path
        self._cache = cache

    def _render_ball_pixmap(self, pm, hovered, accent, side):
        """品牌渐变底 + 白色旋涡 glyph（v3.7.0 新图标）

        v3.6.2：实现抽到 ``ui.ball_render``（主浮球与启动动画共用，避免视觉分叉）
        """
        from agentfloat.ui import ball_render
        ball_render.render_into(pm, side, float(self.current_size), accent, hovered)


    def _check_claude_process(self):
        """检测主 Agent 进程是否在运行，更新指示灯状态

        v3.8.0 性能：改用 CreateToolhelp32Snapshot 进程快照（与单实例守卫同源），
        不再每 3 秒 spawn 一次 tasklist.exe —— 实测省掉一次进程创建 + 控制台管道，
        也避免杀软对高频 tasklist 的误报。
        """
        try:
            primary = get_primary_agent(self._agents)
            cmd = (primary or {}).get("command", "")
            base = os.path.basename(cmd) if cmd else ""
            if not base:
                self._claude_running = False
                return
            if not base.lower().endswith(".exe"):
                base += ".exe"
            running = process_running(base)
            was_running = self._claude_running
            self._claude_running = running
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

        self._api_badge = ApiBalanceBadge(parent_float=self,
                                          on_offset_changed=self._on_badge_moved,
                                          on_style_changed=self._on_badge_style)
        self._api_badge.set_theme(self.theme)
        self._api_badge.set_warn_threshold(am_config.get("low_balance_warn", 5.0))
        self._api_badge.set_position_mode(am_config.get("badge_position", "top"))
        self._api_badge.set_offset(am_config.get("badge_dx", 0), am_config.get("badge_dy", 0))
        self._api_badge.set_scale(am_config.get("badge_scale", 1.0))
        self._api_badge.set_opacity(am_config.get("badge_opacity", 0.88))
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

    def refresh_api_monitor(self):
        """PATCH 3.5.2：手动立即拉取一次（未启动时按当前配置启动）"""
        w = getattr(self, "_api_worker", None)
        if w is None or not w.isRunning():
            self._restart_api_monitor()
            w = getattr(self, "_api_worker", None)
        if w is None:
            _log().info("[API] 手动拉取失败：监控未启用或未配置端点")
            return False
        w.request_refresh()
        return True

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
        # PATCH 3.5.1：模块化显示行（设置中自定义行数与每行内容/显示方式）
        from agentfloat.services.api_monitor.badge_rows import build_badge_rows
        api_cfg = self.config.get("api_monitor") or {}
        rows, is_low, is_error = build_badge_rows(results, api_cfg)
        self._api_badge.set_rows(rows, is_low=is_low, is_error=is_error)

    def _on_badge_moved(self, dx, dy):
        """余额显示框被拖动 → 保存自由偏移（api_monitor.badge_dx / badge_dy）"""
        am = self.config.setdefault("api_monitor", {})
        am["badge_dx"] = int(dx)
        am["badge_dy"] = int(dy)
        save_config(self.config)
        _log().info("[API] 余额显示框位置已保存: dx=%s dy=%s", dx, dy)

    def _on_badge_style(self, scale, opacity):
        """PATCH 3.5.4：显示框大小/不透明度变化（滚轮连续触发 → 去抖保存）"""
        am = self.config.setdefault("api_monitor", {})
        am["badge_scale"] = round(float(scale), 3)
        am["badge_opacity"] = round(float(opacity), 3)
        self._debounced_save("显示框样式 scale=%.2f opacity=%.2f" % (scale, opacity))

    def _on_panel_style(self, scale, opacity):
        """PATCH 3.6.1：进程面板大小/不透明度变化（去抖保存）"""
        pp = self.config.setdefault("process_panel", {})
        pp["scale"] = round(float(scale), 3)
        pp["opacity"] = round(float(opacity), 3)
        self._debounced_save("面板样式 scale=%.2f opacity=%.2f" % (scale, opacity))

    def _debounced_save(self, note=""):
        """连续调整（滚轮）时延迟落盘，避免频繁写文件"""
        timer = getattr(self, "_style_save_timer", None)
        if timer is None:
            from PyQt5.QtCore import QTimer as _QTimer
            timer = self._style_save_timer = _QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: save_config(self.config))
        timer.start(500)
        _log().debug("[样式] %s", note)

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
        # PATCH 3.2.1：悬停检测 100ms → 16ms（60fps）
        # 100ms 下「进入/离开」最多迟半拍，是「菜单不跟手/有延迟」的主因之一
        self._hover_timer.setInterval(16)
        self._hover_timer.timeout.connect(self._check_hover)
        self._hover_timer.start()

        # 按住启动（PATCH 3.3.0）；悬停唤出已在 3.3.1 取消（定时器与入口一并移除，避免死代码）
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(16)
        self._hold_timer.timeout.connect(self._on_hold_tick)
        self._hold_progress = 0.0

        # PATCH 3.3.1：移动浮窗模式（由轮盘「移动浮窗」扇区进入）
        self._move_mode = False
        self._move_origin = QPoint()
        self._wheel_open_pending = False
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(16)
        self._move_timer.timeout.connect(self._on_move_tick)

        # PATCH 3.5.0：进程面板（悬停浮球 250ms 弹出）
        self._proc_panel = None
        self._proc_panel_timer = QTimer(self)
        self._proc_panel_timer.setSingleShot(True)
        self._proc_panel_timer.timeout.connect(self._show_proc_panel)

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
            if msg.message == WM_HOTKEY and msg.wParam == 2 and self._move_mode:
                # PATCH 3.3.1：移动模式下 Esc = 取消（回原位）
                self._exit_move_mode(place=False)
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
        self._ensure_dpr()         # PATCH 3.4.0：跨屏 DPR 变化重建位图
        _log().debug("浮窗显示")
        if not self._hover_timer.isActive():
            self._hover_timer.start()
        # 同步余额角标
        self._sync_api_panel_position()
        if self._api_badge:
            self._api_badge.show()

    def moveEvent(self, event):
        """移动时同步余额角标位置（PATCH 3.4.0：跨屏时重建位图）"""
        super().moveEvent(event)
        self._ensure_dpr()
        self._sync_api_panel_position()

    def hideEvent(self, event):
        """隐藏时停止 hover 检测以节省 CPU"""
        super().hideEvent(event)
        _log().debug("浮窗隐藏")
        self._hover_timer.stop()
        self._hold_timer.stop()
        self._hold_progress = 0.0
        if self._move_mode:
            self._exit_move_mode(place=False)             # PATCH 3.3.1：隐藏即退出移动模式（回原位）
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
        # PATCH 3.5.0：同步进程面板主题
        if self._proc_panel is not None:
            try:
                self._proc_panel.set_theme(theme)
            except Exception:  # noqa: BLE001
                pass
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

    def _bind_display_signals(self):
        """绑定显示器变化信号（增删屏 / 分辨率 / DPI 缩放）——v3.8.0

        改造前只在启动时收敛一次：拔掉显示器或改分辨率后，浮窗可能停在
        已不存在的屏幕坐标上，用户「找不到小球」。
        """
        try:
            app = QApplication.instance()
            if app is not None:
                for sig in ("screenAdded", "screenRemoved", "primaryScreenChanged"):
                    s = getattr(app, sig, None)
                    if s is not None:
                        try:
                            s.connect(self._on_display_changed)
                        except TypeError:
                            pass        # 已连接过（Qt 会忽略重复连接的普通槽）
            for screen in QApplication.screens():
                for sig in ("geometryChanged", "logicalDotsPerInchChanged"):
                    s = getattr(screen, sig, None)
                    if s is not None:
                        try:
                            s.connect(self._on_display_changed)
                        except TypeError:
                            pass
        except Exception as e:  # noqa: BLE001
            _log().debug("显示器信号绑定失败（不影响使用）: %s", e)

    def _on_display_changed(self, *_args):
        """显示器变化 → 防抖 400ms 后统一收敛（切换分辨率时信号会连发）"""
        try:
            self._display_timer.start(400)
        except Exception:  # noqa: BLE001
            pass

    def _apply_display_change(self):
        """收敛浮窗：拉回可见区 + 维持贴边 + 按新 DPI 重建位图"""
        try:
            self._bind_display_signals()     # 屏幕增删后重新绑定新屏幕的信号
            self._ensure_on_screen()
            # 贴边状态在分辨率变化后需要重新贴回边缘（否则会留在旧坐标）
            if self._snapped and self._snap_edge:
                screens = self._screen_rects()
                if screens:
                    off = int(self._ball_offset())
                    size = self.current_size
                    x = self.pos().x() + off
                    y = self.pos().y() + off
                    idx = screen_index_for(x + size / 2.0, y + size / 2.0, screens)
                    nx, ny = edge_position(self._snap_edge, x, y, size, screens[idx])
                    self.move(int(nx - off), int(ny - off))
            self._render_pixmaps()           # DPI 变化 → 重建球体位图
            self._update_mask()
            self.update()
            _log().info("显示器变化：浮窗已收敛到 (%d, %d)", self.pos().x(), self.pos().y())
        except Exception as e:  # noqa: BLE001
            _log().warning("显示器变化收敛失败: %s", e)

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

        SNAP_THRESHOLD = 36                    # PATCH 3.4.0：25→36「足够近就吸附」
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
        self._animate_slide(target, edge, bounce=True)   # PATCH 3.4.0：贴边弹出回弹
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

    def _reveal_now(self, animated=False):
        """吸附隐藏状态下：弹出到完全可见位置（供按压 / 打开菜单前调用）。

        PATCH 3.4.0：animated=True 时用 OutBack 回弹动效（贴边唤出/轮盘前更顺滑）。
        """
        if not (self._snapped and self._hidden_now):
            return
        g = self._screen_geometry()
        s = self.current_size
        edge = self._snap_edge
        off = self._ball_offset()
        target = None
        if edge == "right":
            target = QPoint(int(g.right() - s - 2 - off), self.pos().y())
        elif edge == "left":
            target = QPoint(int(g.left() + 2 - off), self.pos().y())
        elif edge == "top":
            target = QPoint(self.pos().x(), int(g.top() + 2 - off))
        else:  # bottom
            target = QPoint(self.pos().x(), int(g.bottom() - s - 2 - off))
        if target is not None:
            if animated:
                self._animate_move_to(target, duration=170)
            else:
                self.move(target)
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

    def _animate_slide(self, target, edge, bounce=False):
        """滑动动画（PATCH 3.4.0：bounce=True 用 OutBack 呈现贴边「弹出」回弹）"""
        anim = QPropertyAnimation(self, b"slide_pos")
        anim.setDuration(150 if bounce else 120)
        anim.setEasingCurve(QEasingCurve.OutBack if bounce else QEasingCurve.InOutCubic)
        anim.setStartValue(self.pos().x() if edge in ("left", "right") else self.pos().y())
        anim.setEndValue(target)
        anim.start()
        # 保持引用防止被垃圾回收
        self._slide_anim = anim

    def _animate_move_to(self, target, duration=170):
        """通用位置动画（PATCH 3.4.0：贴边弹出/贴边让位，OutBack 回弹）"""
        if self._slide_anim is not None:
            self._slide_anim.stop()
        anim = QPropertyAnimation(self, b"pos")
        anim.setDuration(int(duration))
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(int(target.x()), int(target.y())))
        anim.setEasingCurve(QEasingCurve.OutBack)
        anim.start()
        self._slide_anim = anim

    def _ensure_ring_room(self, animated=True):
        """PATCH 3.4.0：贴边时把浮窗让到「环形菜单可完整展开」的位置。

        返回是否发生了移动（供调用方决定是否等动画结束后再打开轮盘）。
        """
        screens = self._screen_rects()
        if not screens:
            return False
        menu = self._radial_menu
        need = 150
        if menu is not None:
            need = int(getattr(menu, "_outer", 120) + getattr(menu, "_pad", 30))
        off = int(self._ball_offset())
        size = self.current_size
        cx = self.pos().x() + off + size / 2.0
        cy = self.pos().y() + off + size / 2.0
        nx, ny = ring_room_position(cx, cy, need, screens)
        if abs(nx - cx) <= 1 and abs(ny - cy) <= 1:
            return False
        self._snap_menu_restore = self.pos()        # 菜单关闭后恢复（复用既有机制）
        tx = int(nx - size / 2.0 - off)
        ty = int(ny - size / 2.0 - off)
        if animated:
            self._animate_move_to(QPoint(tx, ty), duration=170)
        else:
            self.move(tx, ty)
        _log().debug("贴边让位: (%d,%d) → (%d,%d)（环形菜单完整展开）", cx, cy, nx, ny)
        return True

    def _ensure_dpr(self):
        """PATCH 3.4.0：跨屏（不同 DPI/分辨率）时重建位图与掩码，避免副屏绘制错乱"""
        try:
            dpr = max(1.0, float(self.devicePixelRatioF()))
        except Exception:  # noqa: BLE001
            return
        if abs(dpr - getattr(self, "_pixmap_dpr", 0.0)) > 0.01:
            self._render_pixmaps()
            self._update_mask()
            self.update()
            _log().debug("屏幕 DPR 变化 → 重建浮球位图: %.2f", dpr)

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
        if self._quitting or self._move_mode:
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
            # PATCH 3.3.1：悬停不再唤出菜单（只做视觉反馈）；唤出仅剩「按住外滑轮盘」
            # PATCH 3.5.0：悬停 ~250ms 弹出进程面板
            if self._proc_panel_enabled():
                self._proc_panel_timer.start(int(self._proc_panel_cfg().get("hover_delay_ms", 250)))
        elif not self.is_hovered and was:
            _log().debug("悬停离开")
            self._interaction.hover_leave(now)
            self._animate_scale(1.0, MotionTokens.SPEED)
            self._proc_panel_timer.stop()
            if self._proc_panel is not None and self._proc_panel.isVisible():
                self._proc_panel.hide_soon()      # 留给鼠标移动到面板上（400ms 宽限）
            # 环绕菜单打开时不立即关闭：由菜单自身的宽限/点击外部逻辑处理
            if self._radial_menu is None or not self._radial_menu.isVisible():
                self._close_radial_menu()

    # ── 环绕菜单（按住外滑 / 长按确认，状态机裁决）────────
    def _on_hold_tick(self):
        """按住启动进度（PATCH 3.3.0）：环形进度实时更新，满 → 默认启动"""
        if self._move_mode:
            return
        now = time.monotonic()
        acts = self._interaction.hold_tick(now)
        self._hold_progress = self._interaction.hold_progress(now)
        self.update()
        if InteractionActions.LAUNCH_HOLD in acts:
            self._hold_timer.stop()
            self._hold_progress = 0.0
            self.update()
            _log().info("按住启动完成 → 启动主 Agent")
            self.launch_requested.emit()

    def _open_radial_menu(self, source):
        """打开菜单入口（PATCH 3.4.0：轮盘在贴边时先「让位」再打开，方向映射才准确）"""
        if self._move_mode:
            return                                        # 移动模式：只可移动浮窗
        if source == "wheel":
            moved = False
            if self._snapped and self._hidden_now:
                self._reveal_now(animated=True)
                moved = True
            if self._ensure_ring_room(animated=True):
                moved = True
            if moved:
                self._wheel_open_pending = True
                QTimer.singleShot(200, self._open_wheel_delayed)
                return
        self._open_radial_menu_now(source)

    def _open_wheel_delayed(self):
        """贴边让位动画结束后再打开轮盘（期间松手则取消）"""
        if not self._wheel_open_pending:
            return
        self._wheel_open_pending = False
        self._open_radial_menu_now("wheel")

    # ── 进程面板（PATCH 3.5.0）────────────────────
    def _proc_panel_cfg(self):
        return self.config.get("process_panel") or {}

    def _proc_panel_enabled(self):
        return bool(self._proc_panel_cfg().get("enabled", True))

    def _show_proc_panel(self):
        if not self._proc_panel_enabled() or self._move_mode or self._quitting:
            return
        if self._drag_active or self._interaction.state != "idle":
            return
        if self._radial_menu is not None and self._radial_menu.isVisible():
            return
        try:
            panel_opacity = float(self._proc_panel_cfg().get("opacity", 1.0))
        except (TypeError, ValueError):
            panel_opacity = 1.0
        try:
            panel_scale = float(self._proc_panel_cfg().get("scale", 1.0))
        except (TypeError, ValueError):
            panel_scale = 1.0
        try:
            if self._proc_panel is None:
                from agentfloat.ui.process_panel import ProcessPanel
                self._proc_panel = ProcessPanel(lambda: self._agents, theme=self.theme,
                                                parent=self, opacity=panel_opacity,
                                                scale=panel_scale,
                                                on_style_changed=self._on_panel_style)
            else:
                self._proc_panel.set_opacity(panel_opacity)
                self._proc_panel.set_scale(panel_scale)
            self._proc_panel.show_for(self)
        except Exception:  # noqa: BLE001
            _log().warning("进程面板显示失败", exc_info=True)

    def _hide_proc_panel(self):
        self._proc_panel_timer.stop()
        if self._proc_panel is not None and self._proc_panel.isVisible():
            self._proc_panel.hide_panel()

    def _open_radial_menu_now(self, source):
        self._hide_proc_panel()                           # 开环前收起进程面板
        self._hold_timer.stop()
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
        self._radial_menu.set_hold_mode(self._interaction.hold_select)
        self._radial_menu.open_at(
            center,
            anchor_rect=QRect(self.pos(), self.size()))
        if source in ("long_press", "wheel"):
            # PATCH 3.2.0/3.3.0：按住选环——弹出后不松手，滑到扇区松手即执行
            self._radial_menu.begin_hold()
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
        items.append(RadialMenuItem("move", "移动浮窗", "拖动放置", "#0EA5E9", "移"))
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
            "move": ("移动浮窗", "拖动放置", "#0EA5E9", "移"),
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
        elif action_id == "move":
            self._enter_move_mode()
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

    def refresh_news_unread(self):
        """按已读状态重算未读（v3.9.0：单条已读后同步角标）"""
        try:
            from agentfloat.services.news import fetcher as _nf
            report = _nf.load_latest()
            unread = 0
            if isinstance(report, dict):
                _nf.apply_state(report)
                unread = int(report.get("unread") or 0)
            self._news_unread = unread
            self._news_cfg["unread_count"] = unread
            self.config["news"] = self._news_cfg
            save_config(self.config)
            self.update()
            _log().debug("AI 快报未读数更新: %d", unread)
        except Exception as e:  # noqa: BLE001
            _log().debug("刷新快报未读数失败: %s", e)

    def news_unread_count(self):
        """当前未读数（供托盘提示与菜单展示）"""
        return int(getattr(self, "_news_unread", 0) or 0)

    def news_next_run(self):
        """下次自动生成时间（人类可读；供托盘提示）"""
        try:
            from agentfloat.services.news import fetcher as _nf
            return _nf.next_run_time(self._news_cfg)
        except Exception:  # noqa: BLE001
            return ""

    def cancel_news(self):
        """取消正在进行的快报生成（v3.9.0）"""
        w = getattr(self, "_news_worker", None)
        if w is None or not w.isRunning():
            return False
        try:
            w.cancel()
            _log().info("AI 快报：已请求取消生成")
            _bridge = getattr(self, "_web_bridge", None)
            if _bridge is not None:
                _bridge.publish("news_cancelling", {})
            return True
        except Exception as e:  # noqa: BLE001
            _log().warning("取消快报失败: %s", e)
            return False

    def _on_news_progress(self, phase, done, total, label):
        """生成阶段进度 → Web 桥（SSE）与面板"""
        info = {"phase": phase, "done": int(done), "total": int(total), "label": label}
        _bridge = getattr(self, "_web_bridge", None)
        if _bridge is not None:
            _bridge.set_snapshot("news_phase", label or "")
            _bridge.set_snapshot("news_progress", info)
            _bridge.publish("news_progress", info)
        if self._news_panel is not None and self._news_panel.isVisible():
            try:
                self._news_panel.set_progress(info)
            except Exception:  # noqa: BLE001
                pass

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
        worker.progress.connect(self._on_news_progress)
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
        self._news_cfg = cfg
        self.config["news"] = cfg
        save_config(self.config)
        # v3.9.0：未读数按「条目已读状态」重算（而非简单 +1），并同步角标
        self.refresh_news_unread()
        _bridge = getattr(self, "_web_bridge", None)
        if _bridge is not None:
            _bridge.set_snapshot("news_report", payload)
            _bridge.set_snapshot("news_generating", False)
            _bridge.set_snapshot("news_progress", {})
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
            _bridge.set_snapshot("news_progress", {})
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
        self._hold_timer.stop()
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

        # PATCH 3.3.0：按住启动环形进度（品牌渐变 + 微光，实时提醒）
        if self._hold_progress > 0.01:
            rp = max(0.0, min(1.0, self._hold_progress))
            radius = s / 2.0 + 5.5
            cx = off + s / 2.0
            cy = off + s / 2.0
            rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 55), 3.6,
                                Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(rect, 90 * 16, -360 * 16)
            grad2 = QLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius)
            grad2.setColorAt(0.0, accent)
            grad2.setColorAt(1.0, QColor(0xAF, 0x52, 0xDE))
            glow = QColor(accent)
            glow.setAlpha(70)
            painter.setPen(QPen(glow, 6.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * rp))
            painter.setPen(QPen(QBrush(grad2), 3.2, Qt.SolidLine, Qt.RoundCap))
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * rp))

        # PATCH 3.3.1：移动浮窗模式视觉（虚线环 + 品牌光晕）
        if self._move_mode:
            radius = s / 2.0 + 6.5
            cx = off + s / 2.0
            cy = off + s / 2.0
            rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            glow = QColor(accent)
            glow.setAlpha(46)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(glow, 6.0))
            painter.drawEllipse(rect)
            pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), 210), 2.0,
                       Qt.DashLine, Qt.RoundCap)
            pen.setDashPattern([3, 3])
            painter.setPen(pen)
            painter.drawEllipse(rect)

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
        self._hide_proc_panel()                           # PATCH 3.5.0：按压即收进程面板
        if self._move_mode:
            # PATCH 3.3.1：移动模式——左键放置 / 右键取消（只可移动）
            if event.button() == Qt.LeftButton:
                self._exit_move_mode(place=True)
            elif event.button() == Qt.RightButton:
                self._exit_move_mode(place=False)
            event.accept()
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
            self._interaction.press(now)
            # 按压反馈
            self.is_pressed = True
            self._animate_scale(PRESS_SCALE, MotionTokens.PRESS)
        elif event.button() == Qt.RightButton:
            self._context_menu()
            return

        # PATCH 3.3.0：按住启动进度（中心区不动 → 2s 默认启动；立即外滑 → 轮盘）
        self._hold_progress = 0.0
        self._hold_timer.start()

    # ── 移动浮窗模式（PATCH 3.3.1：由轮盘「移动浮窗」扇区进入）──
    def _enter_move_mode(self):
        """进入移动模式：浮窗跟随光标；左键放置 / 右键或 Esc 取消（只可移动）"""
        if self._move_mode:
            return
        self._move_mode = True
        self._move_origin = self.pos()
        self._hold_timer.stop()
        self._hold_progress = 0.0
        self._hide_proc_panel()                           # PATCH 3.5.0：移动模式只可移动
        self._interaction.cancel()
        self._close_radial_menu()
        self._register_move_hotkey()
        self._move_timer.start()
        if self._launch_toast is None:
            self._launch_toast = LaunchToast()
        self._launch_toast.show_for(self, "移动模式：左键放置 · 右键/Esc 取消",
                                    self.theme, duration_ms=600000)
        _log().info("进入移动浮窗模式")
        self.update()

    def _exit_move_mode(self, place=True):
        """退出移动模式：place=True 放置（吸附+保存）；False 取消（回原位）"""
        if not self._move_mode:
            return
        self._move_mode = False
        self._move_timer.stop()
        self._unregister_move_hotkey()
        if not place:
            self.move(self._move_origin)
        else:
            self._check_snap()
            off = int(self._ball_offset())
            self.config["window_x"] = self.pos().x() + off
            self.config["window_y"] = self.pos().y() + off
            save_config(self.config)
        if self._launch_toast is not None:
            self._launch_toast.hide()
        _log().info("退出移动模式: %s", "放置" if place else "取消")
        self.update()

    def _on_move_tick(self):
        """移动模式：浮窗居中跟随光标（只响应移动）"""
        if not self._move_mode:
            return
        cur = QCursor.pos()
        side = self._window_side()
        self.move(int(cur.x() - side / 2.0), int(cur.y() - side / 2.0))

    def _register_move_hotkey(self):
        """移动模式临时注册全局 Esc（退出即注销）"""
        try:
            MOD_NOREPEAT = 0x4000
            VK_ESCAPE = 0x1B
            ctypes.windll.user32.RegisterHotKey(
                int(self.winId()), 2, MOD_NOREPEAT, VK_ESCAPE)
        except Exception:  # noqa: BLE001
            pass

    def _unregister_move_hotkey(self):
        try:
            ctypes.windll.user32.UnregisterHotKey(int(self.winId()), 2)
        except Exception:  # noqa: BLE001
            pass

    def mouseMoveEvent(self, event):
        if self._move_mode:
            return                                        # 移动模式：只由定时器跟随光标
        if self._quitting or not (event.buttons() & Qt.LeftButton):
            return
        # PATCH 3.2.1：菜单可见（按住选环）时把鼠标位置直接转发给菜单 → 高亮零延迟跟手
        if self._radial_menu is not None and self._radial_menu.isVisible():
            self._radial_menu.update_hold_pos(event.globalPos())
        delta = (event.globalPos() - self._drag_origin).manhattanLength()
        acts = self._interaction.move(delta, time.monotonic())
        if InteractionActions.BEGIN_WHEEL in acts:
            # PATCH 3.3.0：按住外滑 → 打开轮盘菜单（游戏式，松手执行）
            self._hold_timer.stop()
            self._hold_progress = 0.0
            self.update()
            self._open_radial_menu("wheel")
        if InteractionActions.BEGIN_DRAG in acts:
            self._drag_active = True
            self._hold_timer.stop()
            self._hold_progress = 0.0
            self.update()
            # 拖拽开始：取消悬停展开，并关闭已打开的环绕菜单
            if self._slide_anim is not None:
                self._slide_anim.stop()
            if self._radial_menu is not None and self._radial_menu.isVisible():
                self._close_radial_menu()
        if self._drag_active:
            new_pos = self._window_origin + (event.globalPos() - self._drag_origin)
            self.move(new_pos)

    def mouseReleaseEvent(self, event):
        if self._quitting or self._move_mode:
            return
        if event.button() == Qt.LeftButton:
            # PATCH 3.3.0/3.4.0：松手即取消「按住启动」进度与待打开的轮盘
            self._hold_timer.stop()
            self._wheel_open_pending = False
            if self._hold_progress > 0.01:
                self._hold_progress = 0.0
                self.update()
            if (self._interaction.state in ("menu_held", "wheel")
                    and self._radial_menu is not None and self._radial_menu.isVisible()):
                # PATCH 3.2.0/3.3.0：按住选环/轮盘松手 → 命中扇区执行，空白/中心取消
                self._radial_menu.end_hold(event.globalPos())
                self._interaction.release(time.monotonic())   # 退出菜单状态，不触发 CLICK
                self._drag_active = False
                self.is_pressed = False
                self._sync_api_panel_position()
                self._animate_scale(HOVER_SCALE if self.is_hovered else 1.0, MotionTokens.PRESS)
                return
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

        # Web Agent 启动/终止（PATCH 3.1.0：浮球右键菜单入口）
        web_agents = webagent.list_web_agents(self._agents)
        if web_agents:
            web_menu = menu.addMenu("Web Agent")
            for agent, spec in web_agents:
                st = webagent.status(agent)
                wname = agent.get("name") or agent.get("id")
                if st.get("running"):
                    web_menu.addAction("终止 %s（:%d）" % (wname, spec["port"]),
                                       lambda a=agent: self._toggle_web_agent(a))
                    web_menu.addAction("打开 %s 页面" % wname,
                                       lambda u=spec["url"]: _open_url(u))
                else:
                    web_menu.addAction("启动 %s" % wname,
                                       lambda a=agent: self._toggle_web_agent(a))
                web_menu.addSeparator()

        menu.addSeparator()
        menu.addAction("设置...", self.settings_requested.emit)
        menu.addAction("使用教程", lambda: self.start_onboarding(force=True))
        menu.addAction("复制 Web 控制台令牌", self._copy_web_token)
        menu.addSeparator()

        auto = menu.addAction("开机自启")
        auto.setCheckable(True)
        auto.setChecked(is_auto_start_enabled())
        auto.triggered.connect(lambda checked: toggle_auto_start(checked))

        menu.addSeparator()
        menu.addAction("退出", self.quit_requested.emit)

        menu.exec_(QCursor.pos())

    def _copy_web_token(self):
        """复制本地 Web 控制台访问令牌（v3.8.0：浏览器手动打开控制台时粘贴）"""
        try:
            from agentfloat.webshell.server import _current_token as _tok
            token = _tok()
        except Exception:  # noqa: BLE001
            token = ""
        if not token:
            self._show_launch_toast("Web 控制台未启动，暂无令牌")
            return
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(token)
            self._show_launch_toast("已复制 Web 控制台令牌（本次运行内有效）")
        except Exception:  # noqa: BLE001
            self._show_launch_toast("复制失败，请稍后重试")

    def _show_launch_toast(self, text):
        """浮球旁的一句话提示（复用启动提示气泡）"""
        if self._launch_toast is None:
            self._launch_toast = LaunchToast()
        self._launch_toast.show_for(self, text, self.theme)

    # ── 新用户引导（v3.9.0）────────────────────────
    def _ball_rect_global(self):
        """浮球本体的全局矩形（引导聚光灯对准它，而非含阴影的窗口）"""
        off = int(self._ball_offset())
        s = int(self.current_size)
        return QRect(self.pos().x() + off, self.pos().y() + off, s, s)

    def start_onboarding(self, force=False):
        """播放浮窗聚光灯引导；force=False 时已在播放则忽略"""
        if getattr(self, "_onboarding", None) is not None:
            if not force:
                return False
            try:
                self._onboarding.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            from agentfloat.ui.onboarding import OnboardingOverlay
            ball = self._ball_rect_global()
            screen = QApplication.screenAt(ball.center()) or QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
            overlay = OnboardingOverlay(ball, geo, theme=self.theme)
            overlay.finished.connect(self._on_onboarding_finished)
            self._onboarding = overlay
            overlay.show()
            _log().info("新用户引导已开始（共 6 步）")
            return True
        except Exception as e:  # noqa: BLE001
            _log().warning("引导启动失败: %s", e)
            return False

    def _on_onboarding_finished(self, completed):
        self._onboarding = None
        cfg = dict(self.config or {})
        cfg["onboarding_done"] = True
        if completed:
            cfg["onboarding_version"] = 1
        self.config = cfg
        try:
            save_config(cfg)
        except Exception as e:  # noqa: BLE001
            _log().debug("保存引导状态失败: %s", e)
        if completed:
            self._show_launch_toast("引导完成 · 右键可重看")
        _log().info("新用户引导结束（completed=%s）", completed)

    def maybe_start_onboarding(self):
        """首次运行自动播放引导（延迟到启动动画结束后由 app.py 调用）"""
        try:
            if bool((self.config or {}).get("onboarding_done")):
                return False
            return self.start_onboarding()
        except Exception as e:  # noqa: BLE001
            _log().debug("引导自检失败: %s", e)
            return False

    def _toggle_web_agent(self, agent):
        """Web Agent 启动/终止（浮球右键菜单入口，PATCH 3.1.0）"""
        st = webagent.status(agent)
        name = (agent or {}).get("name") or (agent or {}).get("id")
        if st.get("running"):
            ok = webagent.stop(agent)
            _log().info("Web Agent 终止请求: %s -> %s", name, ok)
        else:
            ok = webagent.start(agent, self.config)
            _log().info("Web Agent 启动请求: %s -> %s", name, ok)

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
                # PATCH 3.5.1：同步余额显示框位置（上/下 + 拖动偏移）；3.5.4：大小与不透明度
                if self._api_badge is not None:
                    self._api_badge.set_position_mode(new_api_config.get("badge_position", "top"))
                    self._api_badge.set_offset(new_api_config.get("badge_dx", 0),
                                               new_api_config.get("badge_dy", 0))
                    self._api_badge.set_scale(new_api_config.get("badge_scale", 1.0))
                    self._api_badge.set_opacity(new_api_config.get("badge_opacity", 0.88))
                if new_api_config != old_api_config:
                    _log().info("API 监控配置已变更，重启监控")
                    self._restart_api_monitor()

            # PATCH 3.6.1：进程面板配置（开关/悬停延迟/不透明度/大小）
            # 此前未合并 → 收尾 save_config 会把面板设置写回旧值（表现为「改了存不住」）
            new_panel_cfg = new_cfg.get("process_panel")
            if new_panel_cfg is not None:
                self.config["process_panel"] = new_panel_cfg
                if self._proc_panel is not None:
                    try:
                        self._proc_panel.set_opacity(new_panel_cfg.get("opacity", 1.0))
                        self._proc_panel.set_scale(new_panel_cfg.get("scale", 1.0))
                    except Exception:  # noqa: BLE001
                        _log().debug("同步进程面板样式失败", exc_info=True)

            # v3.6.2：启动动画配置（仅影响下次启动；不合并会被写回旧值 → 表现为「改了存不住」）
            new_intro_cfg = new_cfg.get("intro")
            if new_intro_cfg is not None:
                self.config["intro"] = new_intro_cfg

            # PATCH 3.1.1：补齐此前被忽略的顶层键——它们不在上面任何分支里，
            # 收尾 save_config(self.config) 会把它们写回旧值（表现为「改了存不住」）
            try:
                self.config["hide_delay_ms"] = max(200, min(3000, int(
                    new_cfg.get("hide_delay_ms", self.config.get("hide_delay_ms", 800)))))
            except (TypeError, ValueError):
                self.config["hide_delay_ms"] = self.config.get("hide_delay_ms", 800)
            self.config["check_updates"] = bool(
                new_cfg.get("check_updates", self.config.get("check_updates", True)))
            new_auto = bool(new_cfg.get("auto_start", self.config.get("auto_start", False)))
            if new_auto != bool(self.config.get("auto_start")):
                self.config["auto_start"] = new_auto
                try:
                    toggle_auto_start(new_auto)
                except Exception:  # noqa: BLE001
                    _log().warning("开机自启切换失败", exc_info=True)

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
