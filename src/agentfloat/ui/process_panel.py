# -*- coding: utf-8 -*-
"""Agent 进程面板（PATCH 3.5.0）

鼠标悬停浮球 ~250ms 侧边弹出；展示当前在线的 Agent 进程（状态 / PID / 运行时长 /
最近活动），并提供：分级中断（软中断 Esc / 结束进程树）、继续任务（聚焦 + 注入
continue/继续）、打开窗口、启动（未运行时）。

- 视觉：统一玻璃新风格（panel_style）+ 侧向滑入渐入动效
- 边缘兼容：自动选侧（左/右）并做屏幕内钳制；贴边隐藏的浮球会先回弹唤出
"""
import subprocess

from PyQt5.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QParallelAnimationGroup, \
    QEasingCurve
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QMenu, QMessageBox)
from PyQt5.QtGui import QFont

from agentfloat.core.launcher import launch_agent
from agentfloat.core.logging_setup import _log
from agentfloat.core.theme import get_colors
from agentfloat.services import agent_control, agents_monitor
from agentfloat.ui.panel_style import panel_css

REFRESH_MS = 2000
HIDE_GRACE_MS = 400


class ProcessPanel(QDialog):
    """Agent 进程面板（非模态、非激活，悬停驱动）"""

    def __init__(self, agents_getter, theme="dark", parent=None, on_hide=None):
        super().__init__(parent)
        self._agents_getter = agents_getter
        self._theme = theme
        self._on_hide = on_hide
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_panel)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_MS)
        self._refresh_timer.timeout.connect(self.refresh)

        self.setWindowTitle("AgentFloat — 进程")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumWidth(320)
        self.setStyleSheet(panel_css(theme))

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        self._title = QLabel("Agent 进程")
        f = QFont("Microsoft YaHei", 12, QFont.Bold)
        self._title.setFont(f)
        root.addWidget(self._title)
        self._body = QVBoxLayout()
        self._body.setSpacing(6)
        root.addLayout(self._body)
        self._hint = QLabel("悬停浮球查看 · 离开自动收起")
        self._hint.setStyleSheet("color: #8E8E93; font-size: 10px;")
        root.addWidget(self._hint)

    # ── 位置与显隐 ────────────────────────────────
    def show_for(self, anchor, side="auto"):
        """在浮球侧边弹出（自动选侧 + 屏幕内钳制 + 滑入渐入）"""
        self.refresh()
        self.adjustSize()
        ag = anchor.frameGeometry()
        from agentfloat.ui.placement import screen_index_for
        screens = []
        from PyQt5.QtWidgets import QApplication
        for s in QApplication.screens():
            g = s.availableGeometry()
            screens.append((g.left(), g.top(), g.right(), g.bottom()))
        cx, cy = ag.center().x(), ag.center().y()
        idx = screen_index_for(cx, cy, screens)
        l, t, r, b = screens[idx] if idx >= 0 else (0, 0, 1920, 1080)
        pw, ph = max(320, self.width()), self.height()
        gap = 12
        if side == "auto":
            side = "right" if (r - ag.right()) >= (pw + gap) else "left"
        x = ag.right() + gap if side == "right" else ag.left() - pw - gap
        x = max(l + 6, min(x, r - pw - 6))
        y = max(t + 6, min(ag.center().y() - ph // 2, b - ph - 6))
        self._side = side
        self._hide_timer.stop()
        self.setWindowOpacity(0.0)
        self.move(int(x + (12 if side == "right" else -12)), int(y))
        self.show()
        self.raise_()
        group = QParallelAnimationGroup(self)
        pa = QPropertyAnimation(self, b"pos", self)
        pa.setDuration(180)
        pa.setStartValue(self.pos())
        pa.setEndValue(QPoint(int(x), int(y)))
        pa.setEasingCurve(QEasingCurve.OutCubic)
        oa = QPropertyAnimation(self, b"windowOpacity", self)
        oa.setDuration(180)
        oa.setStartValue(0.0)
        oa.setEndValue(1.0)
        oa.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(pa)
        group.addAnimation(oa)
        self._anim = group
        group.start()
        self._refresh_timer.start()

    def hide_soon(self, delay_ms=HIDE_GRACE_MS):
        self._hide_timer.start(int(delay_ms))

    def cancel_hide(self):
        self._hide_timer.stop()

    def hide_panel(self):
        self._refresh_timer.stop()
        self._hide_timer.stop()
        if not self.isVisible():
            return
        from agentfloat.ui.anim import fade_out
        fade_out(self, duration=140)
        if self._on_hide:
            self._on_hide()

    def enterEvent(self, event):
        self.cancel_hide()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hide_soon()
        super().leaveEvent(event)

    # ── 刷新与卡片 ────────────────────────────────
    def refresh(self):
        while self._body.count():
            item = self._body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        agents = list(self._agents_getter() or [])
        running = agents_monitor.match_agents(agents)
        by_id = {str((m["agent"] or {}).get("id")): m for m in running}
        for a in agents:
            aid = str(a.get("id"))
            m = by_id.get(aid)
            self._body.addWidget(self._card(a, m))
        if not agents:
            self._body.addWidget(QLabel("未配置 Agent"))
        self.adjustSize()

    def _card(self, agent, match):
        c = get_colors(self._theme)
        accent = "#%02X%02X%02X" % c["ACCENT"]
        run = match is not None
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: rgba(255,255,255,0.06); border: 1px solid rgba(128,128,128,0.25);"
            " border-radius: 12px; }")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        head = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet("color: %s; font-size: 11px;" % ("#34C759" if run else "#8E8E93"))
        name = QLabel(str(agent.get("name") or agent.get("id")))
        name.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        head.addWidget(dot)
        head.addWidget(name)
        head.addStretch()
        v.addLayout(head)

        if run:
            pids = match["pids"]
            meta = "PID %s · 运行 %s" % (
                pids[0] if pids else "--",
                agents_monitor.format_runtime(match.get("runtime_s")))
            lbl = QLabel(meta)
            lbl.setStyleSheet("color: %s; font-size: 10px;" % accent)
            v.addWidget(lbl)
            act = agents_monitor.recent_activity(agent.get("id"))
            if act:
                al = QLabel("最近活动：%s" % act)
                al.setWordWrap(True)
                al.setStyleSheet("color: #8E8E93; font-size: 10px;")
                v.addWidget(al)
            row = QHBoxLayout()
            row.setSpacing(6)

            def _tokens(a=agent):
                return str(a.get("name") or a.get("id")), \
                    [str(a.get("command") or "")] + list(a.get("cmd_tokens") or [])

            btn_stop = QPushButton("中断")
            menu = QMenu(btn_stop)
            menu.addAction("软中断（发送 Esc，不结束进程）",
                           lambda a=agent, p=pids: self._soft_interrupt(a, p))
            menu.addAction("结束进程…（终止进程树）",
                           lambda a=agent, p=pids: self._hard_kill(a, p))
            btn_stop.setMenu(menu)
            btn_go = QPushButton("继续任务")
            btn_go.clicked.connect(lambda _=False, a=agent, p=pids: self._continue(a, p))
            btn_open = QPushButton("打开窗口")
            btn_open.clicked.connect(lambda _=False, a=agent, p=pids: self._focus(a, p))
            row.addWidget(btn_stop)
            row.addWidget(btn_go)
            row.addWidget(btn_open)
            row.addStretch()
            v.addLayout(row)
        else:
            s = QLabel("未运行")
            s.setStyleSheet("color: #8E8E93; font-size: 10px;")
            v.addWidget(s)
            row = QHBoxLayout()
            row.addStretch()
            btn_start = QPushButton("启动")
            btn_start.setObjectName("primary")
            btn_start.clicked.connect(lambda _=False, a=agent: launch_agent(a))
            row.addWidget(btn_start)
            v.addLayout(row)
        return card

    # ── 操作 ─────────────────────────────────────
    def _soft_interrupt(self, agent, pids):
        name, tokens = str(agent.get("name")), [str(agent.get("command") or "")] + \
            list(agent.get("cmd_tokens") or [])
        ok, msg = agent_control.send_interrupt(agent, pids, tokens)
        _log().info("[进程面板] 软中断 %s: %s (%s)", name, ok, msg)
        self.refresh()

    def _hard_kill(self, agent, pids):
        name = str(agent.get("name"))
        ret = QMessageBox.question(
            self, "结束进程", "确定结束「%s」的进程树吗？\n（会话可能丢失；可在窗口内用「继续任务」恢复）" % name,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:  # noqa: BLE001
                pass
        _log().info("[进程面板] 已结束进程树 %s: %s", name, pids)
        self.refresh()

    def _continue(self, agent, pids):
        tokens = [str(agent.get("command") or "")] + list(agent.get("cmd_tokens") or [])
        ok, msg = agent_control.send_continue(agent, pids, tokens)
        _log().info("[进程面板] 继续任务 %s: %s (%s)", agent.get("name"), ok, msg)
        self._hint.setText(("✓ " if ok else "✗ ") + msg)

    def _focus(self, agent, pids):
        tokens = [str(agent.get("command") or "")] + list(agent.get("cmd_tokens") or [])
        w = agent_control.find_agent_window(agent, pids, tokens)
        if w and agent_control.focus_window(w["hwnd"]):
            self._hint.setText("✓ 已聚焦窗口")
        else:
            self._hint.setText("✗ 未找到可聚焦窗口")
