# -*- coding: utf-8 -*-
"""Agent 进程面板（PATCH 3.5.1）

鼠标悬停浮球 ~250ms 侧边弹出；**只显示正在运行的 Agent 进程**：
- 运行中：状态点 / PID / 运行时长 / 最近活动 + 「中断」（软中断 Esc / 结束进程树）
- 已中断：中断后进程从运行列表转入「已中断」保留显示，并提供「继续任务」
  - 软中断（进程仍在）：聚焦窗口注入 continue/继续 + 回车
  - 已结束进程：按 Agent 的 resume_args 重新启动并续接上次会话
- 没有任何运行/中断的 Agent 时显示「没有正在进行的 Agent 进程」

视觉：半透明玻璃（与浮球同款圆角/描边），侧向滑入渐入；靠边自动选侧 + 屏幕内钳制。
"""
import subprocess
import time

from PyQt5.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QParallelAnimationGroup, \
    QEasingCurve
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QMenu, QMessageBox)
from PyQt5.QtGui import QFont

from agentfloat.core.launcher import launch_agent
from agentfloat.core.logging_setup import _log
from agentfloat.services import agent_control, agents_monitor

REFRESH_MS = 2000
HIDE_GRACE_MS = 400


def panel_css(theme, opacity=1.0):
    """半透明玻璃样式（与浮球同款观感；深浅色自适应；opacity 只缩放背景/描边）"""
    dark = theme != "light"
    try:
        op = max(0.35, min(1.0, float(opacity)))
    except (TypeError, ValueError):
        op = 1.0

    def rgba(r, g, b, a):
        return "rgba(%d, %d, %d, %.3f)" % (r, g, b, min(1.0, a * op))

    if dark:
        bg = rgba(28, 28, 32, 0.72)
        border = rgba(255, 255, 255, 0.16)
        card = rgba(255, 255, 255, 0.075)
        card_b = rgba(255, 255, 255, 0.12)
        text = "#F2F2F7"
        dim = "#9A9AA0"
        btn_bg = rgba(255, 255, 255, 0.10)
        btn_hover = rgba(255, 255, 255, 0.18)
    else:
        bg = rgba(250, 250, 252, 0.78)
        border = rgba(0, 0, 0, 0.10)
        card = rgba(0, 0, 0, 0.04)
        card_b = rgba(0, 0, 0, 0.07)
        text = "#1C1C1E"
        dim = "#6E6E73"
        btn_bg = rgba(0, 0, 0, 0.05)
        btn_hover = rgba(0, 0, 0, 0.10)
    return """
    QDialog { background: transparent; }
    #panelRoot {
        background: %(bg)s;
        border: 1px solid %(border)s;
        border-radius: 16px;
    }
    QLabel { color: %(text)s; background: transparent; }
    QLabel#title { font-size: 13px; font-weight: 600; }
    QLabel#hint, QLabel#dim { color: %(dim)s; font-size: 11px; }
    QFrame#card {
        background: %(card)s;
        border: 1px solid %(card_b)s;
        border-radius: 12px;
    }
    QPushButton {
        color: %(text)s;
        background: %(btn_bg)s;
        border: 1px solid %(card_b)s;
        border-radius: 8px;
        padding: 4px 10px;
        font-size: 11px;
    }
    QPushButton:hover { background: %(btn_hover)s; }
    QPushButton:disabled { color: %(dim)s; background: rgba(128,128,128,0.10); }
    QMenu { background: %(bg)s; border: 1px solid %(border)s; }
    QMenu::item { color: %(text)s; padding: 6px 18px; }
    QMenu::item:selected { background: %(btn_hover)s; }
    """ % {"bg": bg, "border": border, "card": card, "card_b": card_b,
           "text": text, "dim": dim, "btn_bg": btn_bg, "btn_hover": btn_hover}


class ProcessPanel(QDialog):
    """Agent 进程面板（非模态、非激活，悬停驱动）"""

    def __init__(self, agents_getter, theme="dark", parent=None, on_hide=None, opacity=1.0):
        super().__init__(parent)
        self._agents_getter = agents_getter
        self._theme = theme
        self._on_hide = on_hide
        try:
            self._opacity = max(0.35, min(1.0, float(opacity)))
        except (TypeError, ValueError):
            self._opacity = 1.0
        self._interrupted = {}          # agent_id -> {"ts": 中断时间, "hard": bool}
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
        self.setMinimumWidth(300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        root = QFrame(self)
        root.setObjectName("panelRoot")
        outer.addWidget(root)
        box = QVBoxLayout(root)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        self._title = QLabel("Agent 进程")
        self._title.setObjectName("title")
        box.addWidget(self._title)
        self._body = QVBoxLayout()
        self._body.setSpacing(6)
        box.addLayout(self._body)
        self._hint = QLabel("悬停浮球查看 · 离开自动收起")
        self._hint.setObjectName("hint")
        box.addWidget(self._hint)
        self.setStyleSheet(panel_css(theme, self._opacity))

    def set_theme(self, theme):
        self._theme = theme
        self.setStyleSheet(panel_css(theme, self._opacity))

    # PATCH 3.5.4：不透明度（只影响背景/描边，文字保持清晰）
    def set_opacity(self, opacity):
        try:
            self._opacity = max(0.35, min(1.0, float(opacity)))
        except (TypeError, ValueError):
            self._opacity = 1.0
        self.setStyleSheet(panel_css(self._theme, self._opacity))

    # ── 位置与显隐 ────────────────────────────────
    def show_for(self, anchor, side="auto"):
        """在浮球侧边弹出（自动选侧 + 屏幕内钳制 + 滑入渐入）"""
        self.refresh()
        self.adjustSize()
        ag = anchor.frameGeometry()
        from PyQt5.QtWidgets import QApplication
        screens = []
        for s in QApplication.screens():
            g = s.availableGeometry()
            screens.append((g.left(), g.top(), g.right(), g.bottom()))
        from agentfloat.ui.placement import screen_index_for
        idx = screen_index_for(ag.center().x(), ag.center().y(), screens)
        l, t, r, b = screens[idx] if idx >= 0 else (0, 0, 1920, 1080)
        pw, ph = max(300, self.width()), self.height()
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
        by_id = {str(a.get("id")): a for a in agents}
        running = agents_monitor.match_agents(agents)
        run_by_id = {str((m["agent"] or {}).get("id")): m for m in running}

        # 已恢复的标记自动清除（进程启动时间晚于中断时间 → 新会话）
        for aid, info in list(self._interrupted.items()):
            m = run_by_id.get(aid)
            if m and m.get("start_ts") and m["start_ts"] > info.get("ts", 0):
                del self._interrupted[aid]

        if not running and not self._interrupted:
            empty = QLabel("没有正在进行的 Agent 进程")
            empty.setObjectName("dim")
            self._body.addWidget(empty)
        for m in running:
            self._body.addWidget(self._card(m["agent"], m))
        for aid in list(self._interrupted.keys()):
            if aid not in run_by_id and aid in by_id:
                self._body.addWidget(self._card(by_id[aid], None))
        self.adjustSize()

    def _card(self, agent, match):
        aid = str(agent.get("id"))
        run = match is not None
        marked = aid in self._interrupted
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(4)
        head = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet("color: %s; font-size: 11px;" % ("#FF9F0A" if marked else "#34C759"))
        name = QLabel(str(agent.get("name") or aid))
        name.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        head.addWidget(dot)
        head.addWidget(name)
        if marked:
            tag = QLabel("已中断")
            tag.setObjectName("dim")
            head.addWidget(tag)
        head.addStretch()
        v.addLayout(head)

        if run:
            pids = match["pids"]
            meta = "PID %s · 运行 %s" % (
                pids[0] if pids else "--",
                agents_monitor.format_runtime(match.get("runtime_s")))
            lbl = QLabel(meta)
            lbl.setObjectName("dim")
            v.addWidget(lbl)
            act = agents_monitor.recent_activity(agent.get("id"))
            if act:
                al = QLabel("最近活动：%s" % act)
                al.setWordWrap(True)
                al.setObjectName("dim")
                v.addWidget(al)
        elif marked:
            lbl = QLabel("进程已结束" + ("（中断时结束）" if self._interrupted[aid].get("hard") else ""))
            lbl.setObjectName("dim")
            v.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(6)
        if run:
            btn_stop = QPushButton("中断")
            menu = QMenu(btn_stop)
            menu.addAction("软中断（发送 Esc，不结束进程）",
                           lambda a=agent, m=match: self._soft_interrupt(a, m))
            menu.addAction("结束进程…（终止进程树）",
                           lambda a=agent, m=match: self._hard_kill(a, m))
            btn_stop.setMenu(menu)
            row.addWidget(btn_stop)
            if marked:
                # 仅在「已中断」后提供继续任务（用户确认的交互）
                btn_go = QPushButton("继续任务")
                btn_go.clicked.connect(lambda _=False, a=agent, m=match: self._continue(a, m))
                row.addWidget(btn_go)
            btn_open = QPushButton("打开窗口")
            btn_open.clicked.connect(lambda _=False, a=agent, m=match: self._focus(a, m))
            row.addWidget(btn_open)
        elif marked:
            resume = list(agent.get("resume_args") or [])
            btn_go = QPushButton("继续任务")
            btn_go.clicked.connect(lambda _=False, a=agent: self._continue(a, None))
            if not resume:
                btn_go.setEnabled(False)
                btn_go.setToolTip("该 Agent 未配置 resume_args，无法自动恢复会话")
            else:
                btn_go.setToolTip("重新启动并续接上次会话：%s" % " ".join(resume))
            row.addWidget(btn_go)
        row.addStretch()
        v.addLayout(row)
        return card

    # ── 操作 ─────────────────────────────────────
    def _tokens(self, agent):
        return [str(agent.get("name") or ""), str(agent.get("command") or "")] + \
            list(agent.get("cmd_tokens") or [])

    def _soft_interrupt(self, agent, match):
        aid = str(agent.get("id"))
        ok, msg = agent_control.send_interrupt(agent, match["pids"], self._tokens(agent))
        if ok:
            self._interrupted[aid] = {"ts": time.time(), "hard": False}
        _log().info("[进程面板] 软中断 %s: %s (%s)", agent.get("name"), ok, msg)
        self._hint.setText(("✓ " if ok else "✗ ") + msg)
        self.refresh()

    def _hard_kill(self, agent, match):
        name = str(agent.get("name"))
        ret = QMessageBox.question(
            self, "结束进程", "确定结束「%s」的进程树吗？\n（会话可能丢失；之后可用「继续任务」自动续接）" % name,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        for pid in match["pids"]:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:  # noqa: BLE001
                pass
        self._interrupted[str(agent.get("id"))] = {"ts": time.time(), "hard": True}
        _log().info("[进程面板] 已结束进程树 %s: %s", name, match["pids"])
        self._hint.setText("✓ 已结束进程（继续任务可续接会话）")
        self.refresh()

    def _continue(self, agent, match):
        aid = str(agent.get("id"))
        if match is not None:
            ok, msg = agent_control.send_continue(agent, match["pids"], self._tokens(agent))
        else:
            resume = list(agent.get("resume_args") or [])
            if not resume:
                self._hint.setText("✗ 该 Agent 未配置 resume_args，无法自动恢复")
                return
            relaunch = dict(agent)
            relaunch["args"] = list(agent.get("args") or []) + resume
            launch_agent(relaunch)
            ok, msg = True, "已重新启动并续接上次会话（%s）" % " ".join(resume)
        if ok:
            self._interrupted.pop(aid, None)
        _log().info("[进程面板] 继续任务 %s: %s (%s)", agent.get("name"), ok, msg)
        self._hint.setText(("✓ " if ok else "✗ ") + msg)
        self.refresh()

    def _focus(self, agent, match):
        w = agent_control.find_agent_window(agent, match["pids"], self._tokens(agent))
        if w and agent_control.focus_window(w["hwnd"]):
            self._hint.setText("✓ 已聚焦窗口")
        else:
            self._hint.setText("✗ 未找到可聚焦窗口")
