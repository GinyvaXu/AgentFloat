# -*- coding: utf-8 -*-
"""D 线 L2 驾驶舱：项目列表 + 步骤耗时 + 简易回放。"""
from __future__ import annotations

from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, QSettings
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget,
                             QListWidgetItem, QMainWindow, QProgressBar,
                             QPushButton, QScrollArea, QSplitter, QVBoxLayout,
                             QWidget)

from agentfloat.core.theme import FONT_FAMILY, get_colors
from agentfloat.core.window_focus import focus_window
from agentfloat.services.progress import store

STATUS_LABEL = {"running": "进行中", "need_input": "等待确认", "failed": "失败",
                "done": "已完成", "cancelled": "已取消", "plan": "准备"}
STATUS_DOT = {"running": "●", "need_input": "!", "failed": "×",
              "done": "✓", "cancelled": "–", "plan": "○"}
STEP_ICON = {"done": "✓", "running": "▸", "failed": "×", "pending": "○"}


def _dt(text):
    try:
        return datetime.fromisoformat(str(text or "").replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def segment_text(done, total, width=12):
    total = max(1, int(total or 0))
    width = max(4, int(width or 12))
    filled = int(round(width * max(0, min(done, total)) / float(total)))
    return "▰" * filled + "▱" * (width - filled)


def fmt_duration(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds < 60:
        return "%ds" % seconds
    minutes = seconds // 60
    if minutes < 60:
        return "%dm" % minutes
    return "%dh%02dm" % (minutes // 60, minutes % 60)


def step_seconds(step, now=None):
    start = _dt(step.get("startedAt"))
    if not start:
        return 0
    end = _dt(step.get("finishedAt")) or (now or datetime.now().astimezone())
    try:
        return max(0, (end - start).total_seconds())
    except TypeError:
        return 0


def session_elapsed(data, now=None):
    start = _dt(data.get("createdAt"))
    if not start:
        return 0
    end = _dt(data.get("finishedAt"))
    if not end and str(data.get("status") or "") in ("done", "failed", "cancelled"):
        # 旧数据没有 session 级 finishedAt：退回最后一次更新时间，避免「已用」继续涨
        end = _dt(data.get("updatedAt"))
    end = end or (now or datetime.now().astimezone())
    try:
        return max(0, (end - start).total_seconds())
    except TypeError:
        return 0


def sessions_signature(rows):
    return "||".join("%s:%s:%s" % (r.get("sessionId"), r.get("status"), r.get("updatedAt"))
                     for r in rows)


class StepRow(QWidget):
    def __init__(self, step, max_seconds, colors):
        super().__init__()
        c = colors
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(8)
        icon = QLabel(STEP_ICON.get(str(step.get("status")), "○"))
        icon.setFixedWidth(14)
        icon.setStyleSheet("color: rgb(%d,%d,%d); font-size:12px;" % c["TEXT_SECONDARY"])
        lay.addWidget(icon)
        title = QLabel(step.get("title") or "")
        title.setFixedWidth(138)
        title.setStyleSheet("font-size:11.5px; color: rgb(%d,%d,%d);" % c["TEXT"])
        lay.addWidget(title)
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(5)
        bar.setMaximum(max(1, int(max_seconds)))
        bar.setValue(min(int(step_seconds(step)), int(max_seconds)))
        bar.setStyleSheet(
            "QProgressBar { background: rgba(255,255,255,0.08); border:none; border-radius:4px; }"
            "QProgressBar::chunk { background: rgb(%d,%d,%d); border-radius:4px; }"
            % c["ACCENT"])
        lay.addWidget(bar, 1)
        secs = step_seconds(step)
        est = float(step.get("estimateMinutes") or 0) * 60
        text = fmt_duration(secs) if secs else "—"
        if est:
            text += " / 估 " + fmt_duration(est)
        dur = QLabel(text)
        dur.setFixedWidth(104)
        dur.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        dur.setStyleSheet("font-size:10.5px; color: rgb(%d,%d,%d);" % c["HINT"])
        lay.addWidget(dur)


class ProgressCockpit(QMainWindow):
    def __init__(self, theme="dark", session_id=""):
        super().__init__()
        self._theme = theme if theme in ("dark", "light") else "dark"
        self._c = get_colors(self._theme)
        self._session_id = session_id
        self._sig = ""
        self._rows = []
        self._replay_timer = QTimer(self)
        self._replay_timer.setInterval(650)
        self._replay_timer.timeout.connect(self._replay_next)
        self._replay_index = -1
        self._replaying = False
        self.setWindowTitle("AgentFloat · 进度驾驶舱")
        self.resize(860, 560)
        self.setStyleSheet(
            "QMainWindow { background: rgb(%d,%d,%d); }"
            "QWidget#cockpitRight { background: rgb(%d,%d,%d); }"
            "QLabel { background: transparent; }"
            "QScrollArea { background: transparent; border: none; }"
            % (self._c["GLASS_BG"][0], self._c["GLASS_BG"][1], self._c["GLASS_BG"][2],
               self._c["GLASS_BG"][0], self._c["GLASS_BG"][1], self._c["GLASS_BG"][2]))

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setFixedWidth(240)
        self.list.setStyleSheet(
            "QListWidget { background: rgb(%d,%d,%d); border:none; color: rgb(%d,%d,%d);"
            " font-family:'%s'; font-size:11.5px; }"
            "QListWidget::item { padding:8px 10px; border-bottom:1px solid rgba(255,255,255,0.06); }"
            "QListWidget::item:selected { background: rgba(10,132,255,0.18); }"
            % (self._c["SURFACE"][0], self._c["SURFACE"][1], self._c["SURFACE"][2],
               self._c["TEXT"][0], self._c["TEXT"][1], self._c["TEXT"][2], FONT_FAMILY))
        self.list.currentRowChanged.connect(self._on_select)
        split.addWidget(self.list)

        right = QWidget()
        right.setObjectName("cockpitRight")
        self._right = QVBoxLayout(right)
        self._right.setContentsMargins(18, 16, 18, 16)
        self._right.setSpacing(10)
        head = QHBoxLayout()
        self.title = QLabel("选择左侧任务")
        self.title.setStyleSheet("font-size:17px; font-weight:700; color: rgb(%d,%d,%d);"
                                 % self._c["TEXT"])
        head.addWidget(self.title)
        head.addStretch(1)
        self.status = QLabel("")
        self.status.setStyleSheet("font-size:11px; color: rgb(%d,%d,%d);"
                                  % self._c["TEXT_SECONDARY"])
        head.addWidget(self.status)
        self._right.addLayout(head)
        self.meta = QLabel("")
        self.meta.setStyleSheet("font-size:11px; color: rgb(%d,%d,%d);" % self._c["HINT"])
        self._right.addWidget(self.meta)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.steps_host = QWidget()
        self.steps_box = QVBoxLayout(self.steps_host)
        self.steps_box.setContentsMargins(0, 4, 0, 4)
        self.steps_box.setSpacing(2)
        self.scroll.setWidget(self.steps_host)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.steps_host.setStyleSheet("background: transparent;")
        self._right.addWidget(self.scroll, 1)

        actions = QHBoxLayout()
        self.btn_resume = QPushButton("继续")
        self.btn_resume.clicked.connect(self._resume)
        self.btn_cancel = QPushButton("中断")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_replay = QPushButton("回放")
        self.btn_replay.clicked.connect(self._replay)
        self.btn_focus = QPushButton("聚焦窗口")
        self.btn_focus.clicked.connect(self._focus)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(lambda: self._refresh(force=True))
        for btn in (self.btn_resume, self.btn_cancel, self.btn_replay,
                    self.btn_focus, self.btn_refresh):
            btn.setStyleSheet(
                "QPushButton { border:1px solid rgba(255,255,255,0.12); background: transparent;"
                " border-radius:8px; padding:5px 14px; font-size:11px; color: rgb(%d,%d,%d); }"
                "QPushButton:hover { background: rgba(255,255,255,0.08); }"
                "QPushButton:focus { border-color: rgb(%d,%d,%d); }"
                "QPushButton:disabled { color: rgba(%d,%d,%d,0.35);"
                " border-color: rgba(255,255,255,0.06); }"
                % (self._c["TEXT"][0], self._c["TEXT"][1], self._c["TEXT"][2],
                   self._c["ACCENT"][0], self._c["ACCENT"][1], self._c["ACCENT"][2],
                   self._c["TEXT"][0], self._c["TEXT"][1], self._c["TEXT"][2]))
            actions.addWidget(btn)
        actions.addStretch(1)
        self._right.addLayout(actions)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        settings = QSettings("AgentFloat", "ProgressCockpit")
        geo = settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def closeEvent(self, event):
        QSettings("AgentFloat", "ProgressCockpit").setValue("geometry", self.saveGeometry())
        super().closeEvent(event)

    def _refresh(self, force=False):
        # 回放期间暂停定时刷新：重建 StepRow 会抹掉高亮、把滚动拉回顶部
        if self._replaying and not force:
            return
        if force:
            self._stop_replay()
        rows = store.list_sessions()
        sig = sessions_signature(rows)
        if sig != self._sig:
            self._sig = sig
            self._rows = rows
            self._fill_list(rows)
        if self._session_id:
            for idx, data in enumerate(self._rows):
                if data.get("sessionId") == self._session_id:
                    self.list.setCurrentRow(idx)
                    break
            self._session_id = ""
        self._render_selected()

    def _fill_list(self, rows):
        current = self._current()
        keep = current.get("sessionId") if current else ""
        self.list.blockSignals(True)
        self.list.clear()
        for data in rows:
            status = str(data.get("status") or "")
            done = sum(1 for s in data.get("steps") or [] if s.get("status") == "done")
            total = len(data.get("steps") or [])
            item = QListWidgetItem("%s %s\n %d/%d · %s" % (
                STATUS_DOT.get(status, "○"),
                data.get("title") or data.get("project") or data.get("sessionId"),
                done, total, STATUS_LABEL.get(status, status)))
            if status == "need_input":
                item.setForeground(QColor("#FF9F0A"))
            elif status == "failed":
                item.setForeground(QColor("#FF453A"))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if keep:
            for idx, data in enumerate(rows):
                if data.get("sessionId") == keep:
                    self.list.setCurrentRow(idx)
                    return
        if rows:
            self.list.setCurrentRow(0)

    def _current(self):
        idx = self.list.currentRow() if hasattr(self, "list") else -1
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None

    def _on_select(self, _row):
        self._stop_replay()
        self._render_selected()

    def _stop_replay(self):
        self._replay_timer.stop()
        self._replaying = False
        self._replay_index = -1
        if hasattr(self, "_timer") and not self._timer.isActive():
            self._timer.start()

    def _render_selected(self):
        data = self._current()
        if not data:
            self.title.setText("暂无任务")
            self.meta.setText("CLI / MCP 写入进度后会出现在这里")
            self.status.setText("")
            self.btn_resume.setEnabled(False)
            self.btn_cancel.setEnabled(False)
            self.btn_replay.setEnabled(False)
            self.btn_focus.setEnabled(False)
            return
        status = str(data.get("status") or "")
        self.title.setText(data.get("title") or data.get("project") or data.get("sessionId"))
        self.status.setText(STATUS_LABEL.get(status, status))
        eta = (data.get("eta") or {}).get("etaText") or "待估"
        done_n, total_n = (sum(1 for x in (data.get("steps") or []) if x.get("status") == "done"),
                           len(data.get("steps") or []))
        self.meta.setText("项目 %s · %s %d/%d · 已用 %s · ETA %s · 更新 %s" % (
            data.get("project") or "—", segment_text(done_n, total_n), done_n, total_n,
            fmt_duration(session_elapsed(data)), eta,
            str(data.get("updatedAt") or "")[11:16]))
        self.btn_resume.setEnabled(status in ("need_input", "failed"))
        self.btn_cancel.setEnabled(status in ("running", "need_input"))
        self.btn_replay.setEnabled(bool(data.get("steps")))
        self.btn_focus.setEnabled(bool(data.get("window")))
        self._render_steps(data)

    def _render_steps(self, data):
        while self.steps_box.count():
            item = self.steps_box.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        steps = data.get("steps") or []
        max_sec = max([step_seconds(s) for s in steps] + [60])
        for step in steps:
            self.steps_box.addWidget(StepRow(step, max_sec, self._c))
        if not steps:
            empty = QLabel("没有步骤信息（只能看到活跃/停滞）")
            empty.setStyleSheet("color: rgb(%d,%d,%d); font-size:11px;" % self._c["HINT"])
            self.steps_box.addWidget(empty)
        self.steps_box.addStretch(1)

    def _resume(self):
        data = self._current()
        if not data:
            return
        try:
            # 复用 store 的 retry：复位原失败步骤，不追加「步骤 N」
            store.update(data.get("sessionId"), {"action": "retry", "source": "qt"})
        except Exception:  # noqa: BLE001
            pass
        self._refresh(force=True)

    def _cancel(self):
        data = self._current()
        if not data:
            return
        try:
            store.update(data.get("sessionId"), {"action": "cancel", "source": "qt"})
        except Exception:  # noqa: BLE001
            pass
        self._refresh(force=True)

    def _focus(self):
        data = self._current()
        if not data:
            return
        if not focus_window(data.get("window")):
            self.status.setText("未找到窗口：" + str(data.get("window") or "未记录"))

    def _replay(self):
        if not self._rows:
            return
        self._replay_index = -1
        self._replaying = True
        self._timer.stop()          # 回放期间不刷新，避免 StepRow 被重建
        self._replay_timer.start()
        self._replay_next()

    def _replay_next(self):
        steps = (self._current() or {}).get("steps") or []
        self._replay_index += 1
        if self._replay_index >= len(steps):
            self._stop_replay()
            return
        for i in range(self.steps_box.count()):
            w = self.steps_box.itemAt(i).widget()
            if isinstance(w, StepRow):
                w.setStyleSheet("background: transparent;")
                if i == self._replay_index:
                    w.setStyleSheet("background: rgba(10,132,255,0.10); border-radius:8px;")


_COCKPIT = None


def open_cockpit(session_id="", theme="dark"):
    """打开（或复用）驾驶舱窗口。"""
    global _COCKPIT
    if _COCKPIT is None:
        _COCKPIT = ProgressCockpit(theme=theme, session_id=session_id)
    else:
        if session_id:
            _COCKPIT._session_id = session_id
        _COCKPIT.show()
    _COCKPIT.show()
    _COCKPIT.raise_()
    _COCKPIT.activateWindow()
    return _COCKPIT
