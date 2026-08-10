# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — 喝水助手面板与提醒弹窗

- WaterPanel：独立小面板（毛玻璃无边框），展示今日杯数与三个循环计时器，
  提供 开始/暂停/跳过/重置 与「+1 已喝水」快捷操作。
- WaterReminderPopup：提醒弹窗。支持两种形态：
    fullscreen = 指定屏幕的全屏遮罩（默认，醒目；可通过进程豁免名单静默）
    popup      = 屏幕居中的大卡片弹窗
  弹窗为可聚焦置顶窗口（避免首次点击只激活窗口导致“无法关闭”），
  带淡入淡出动画，需手动确认后才关闭。
"""
from PyQt5.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QVBoxLayout,
)

from af_theme import get_colors
from skills_panel import _TitleBar
from water_reminder import STATE_CN


def _fmt_sec(sec):
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%02d:%02d" % (m, s)


def _hex(c):
    return "#%02X%02X%02X" % (c[0], c[1], c[2])


class WaterPanel(QDialog):
    """喝水助手主面板：今日杯数 + 三个循环计时器"""

    open_settings_requested = pyqtSignal()

    def __init__(self, manager, theme="dark", parent=None):
        super().__init__(parent)
        self._manager = manager
        self._theme = theme
        self._cfg = manager.config()
        self._c = get_colors(theme)
        self._rows = {}
        self.setWindowTitle("AgentFloat — 喝水助手")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(380, 468)
        self.setStyleSheet(self._stylesheet())
        self._setup_ui()
        manager.timers_changed.connect(self._refresh)
        manager.cups_changed.connect(self._refresh)
        self._refresh()

    def _stylesheet(self):
        c = self._c
        is_dark = self._theme == "dark"
        sf = _hex(c["SURFACE"])
        tx = _hex(c["TEXT"])
        hi = _hex(c["HINT"])
        ac = _hex(c["ACCENT"])
        bd = _hex(c["SEPARATOR"])
        card = "#333336" if is_dark else "#FFFFFF"
        banner = "rgba(255,255,255,0.06)" if is_dark else "rgba(255,255,255,0.62)"
        hover = "rgba(255,255,255,0.09)" if is_dark else "rgba(120,120,128,0.10)"
        return (
            "QDialog { background: %s; border: 1px solid %s; border-radius: 14px; }" % (sf, bd)
            + "QFrame#titleBar { background: %s; border-top-left-radius: 14px;"
              " border-top-right-radius: 14px; border-bottom: 1px solid %s; }" % (banner, bd)
            + "QFrame#waterCard { background: %s; border: 1px solid %s; border-radius: 10px; }" % (card, bd)
            + "QFrame#timerRow { background: %s; border: 1px solid %s; border-radius: 10px; }" % (card, bd)
            + "QLabel { color: %s; border: none; background: transparent; }" % tx
            + "QProgressBar { background: %s; border: none; border-radius: 4px;"
              " height: 8px; text-align: center; font-size: 0px; }" % (hover if not is_dark else "rgba(255,255,255,0.10)")
            + "QProgressBar::chunk { background: %s; border-radius: 4px; }" % ac
            + "QPushButton { background: %s; color: %s; border: 1px solid %s;"
              " border-radius: 8px; padding: 6px 12px; font-size: 12px; }" % (card, ac, bd)
            + "QPushButton:hover { background: %s; }" % sf
            + "QPushButton:disabled { color: %s; }" % hi
            + "QPushButton#primary { background: %s; color: #FFF; border: none; font-weight: bold; }" % ac
            + "QPushButton#primary:hover { background: %s; }" % _hex(c["ACCENT"])
        )

    def _setup_ui(self):
        c = self._c
        ac = _hex(c["ACCENT"])
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(_TitleBar(self, "喝水助手"))

        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(10)

        # ── 今日杯数卡片 ──
        card = QFrame()
        card.setObjectName("waterCard")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 12, 14, 12)
        cv.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel("今日饮水")
        title.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        top.addWidget(title)
        top.addStretch()
        self.lbl_target = QLabel("")
        self.lbl_target.setStyleSheet("color: %s; font-size: 11px;" % _hex(c["HINT"]))
        top.addWidget(self.lbl_target)
        cv.addLayout(top)

        num_row = QHBoxLayout()
        num_row.setSpacing(8)
        self.lbl_cups = QLabel("0")
        self.lbl_cups.setFont(QFont("Microsoft YaHei", 30, QFont.Bold))
        self.lbl_cups.setStyleSheet("color: %s;" % ac)
        num_row.addWidget(self.lbl_cups)
        num_row.addWidget(QLabel("杯"))
        num_row.addStretch()
        self.btn_cup = QPushButton("＋1 已喝水")
        self.btn_cup.setObjectName("primary")
        self.btn_cup.setCursor(Qt.PointingHandCursor)
        self.btn_cup.clicked.connect(lambda: self._manager.add_cup(1))
        num_row.addWidget(self.btn_cup)
        cv.addLayout(num_row)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        cv.addWidget(self.progress)
        body.addWidget(card)

        # ── 计时器列表 ──
        for t in self._manager.timers():
            body.addWidget(self._build_timer_row(t))

        body.addStretch(1)
        root.addLayout(body, 1)

    def _build_timer_row(self, t):
        c = self._c
        row = QFrame()
        row.setObjectName("timerRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        dot = QLabel(t["char"])
        dot.setAlignment(Qt.AlignCenter)
        dot.setFixedSize(34, 34)
        dot.setStyleSheet(
            "QLabel { color: #FFF; font-size: 14px; font-weight: bold;"
            " background: %s; border-radius: 17px; }" % t["color"])
        lay.addWidget(dot)

        info = QVBoxLayout()
        info.setSpacing(1)
        name = QLabel(t["name"])
        name.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        info.addWidget(name)
        self._rows[t["id"]] = {"state": QLabel("")}
        self._rows[t["id"]]["state"].setStyleSheet("color: %s; font-size: 10px;" % _hex(c["HINT"]))
        info.addWidget(self._rows[t["id"]]["state"])
        lay.addLayout(info, 1)

        tm = QLabel(_fmt_sec(t["remaining"]))
        tm.setFont(QFont("Consolas", 13, QFont.Bold))
        tm.setStyleSheet("color: %s;" % _hex(c["TEXT"]))
        self._rows[t["id"]]["time"] = tm
        lay.addWidget(tm)

        btn_toggle = QPushButton("")
        btn_toggle.setCursor(Qt.PointingHandCursor)
        btn_toggle.setFixedWidth(52)
        btn_toggle.clicked.connect(lambda _c, tid=t["id"]: self._toggle(tid))
        lay.addWidget(btn_toggle)
        self._rows[t["id"]]["toggle"] = btn_toggle

        btn_skip = QPushButton("跳过")
        btn_skip.setCursor(Qt.PointingHandCursor)
        btn_skip.clicked.connect(lambda _c, tid=t["id"]: self._manager.skip_timer(tid))
        lay.addWidget(btn_skip)

        return row

    def _toggle(self, tid):
        t = self._manager.timer_info(tid)
        if not t:
            return
        if t["state"] in ("running", "snoozed"):
            self._manager.pause_timer(tid)
        else:
            self._manager.start_timer(tid)

    def _refresh(self, *_):
        cups = self._manager.today_cups()
        target = max(1, int(self._cfg.get("target_cups") or 8))
        self.lbl_cups.setText(str(cups))
        self.lbl_target.setText("目标 %d 杯" % target)
        self.progress.setValue(min(100, int(cups / target * 100)))
        for tid, row in self._rows.items():
            t = self._manager.timer_info(tid)
            if not t:
                continue
            row["time"].setText(_fmt_sec(t["remaining"]))
            row["state"].setText(STATE_CN.get(t["state"], t["state"]))
            btn = row["toggle"]
            if t["state"] in ("running", "snoozed"):
                btn.setText("暂停")
            elif t["state"] == "paused":
                btn.setText("继续")
            else:
                btn.setText("开始")


class WaterReminderPopup(QDialog):
    """提醒弹窗：全屏遮罩或居中卡片，需手动确认，带淡入淡出动画"""

    confirmed = pyqtSignal(str)   # timer id：已喝水 / 知道了
    snoozed = pyqtSignal(str)     # timer id：稍后提醒

    def __init__(self, timer_info, message, theme="dark", fullscreen=True,
                 sound=True, parent=None):
        super().__init__(parent)
        self._timer = timer_info or {}
        self._message = message or "该休息一下啦"
        self._theme = theme
        self._fullscreen = fullscreen
        self._sound = sound
        self._closing = False
        self._c = get_colors(theme)
        self._screen = None
        self.setWindowTitle("喝水助手提醒")
        # 使用 Qt.Window（而非 Qt.Tool）：Tool 窗口不抢焦点，
        # 会导致真实场景下首次点击只激活窗口、按钮“点不动”。
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._build_animation()
        self._build_ui()

    def _build_animation(self):
        self._op_effect = QGraphicsOpacityEffect(self)
        self._op_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._op_effect)
        self._anim_in = QPropertyAnimation(self._op_effect, b"opacity", self)
        self._anim_in.setDuration(220)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(1.0)
        self._anim_in.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_out = QPropertyAnimation(self._op_effect, b"opacity", self)
        self._anim_out.setDuration(180)
        self._anim_out.setStartValue(1.0)
        self._anim_out.setEndValue(0.0)
        self._anim_out.setEasingCurve(QEasingCurve.InCubic)
        self._anim_out.finished.connect(self._real_close)

    def _build_ui(self):
        c = self._c
        ac = _hex(c["ACCENT"])
        tx = _hex(c["TEXT"])
        hi = _hex(c["HINT"])
        card_bg = "rgba(44,44,46,0.92)" if self._theme == "dark" else "rgba(250,250,252,0.94)"
        border = _hex(c["SEPARATOR"])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setFixedSize(420, 320)
        card.setStyleSheet(
            "QFrame { background: %s; border: 1px solid %s; border-radius: 22px; }"
            % (card_bg, border))
        cv = QVBoxLayout(card)
        cv.setContentsMargins(30, 26, 30, 24)
        cv.setSpacing(10)

        char = self._timer.get("char") or "水"
        color = self._timer.get("color") or "#00A6A6"
        dot = QLabel(char)
        dot.setAlignment(Qt.AlignCenter)
        dot.setFixedSize(72, 72)
        dot.setStyleSheet(
            "QLabel { color: #FFF; font-size: 32px; font-weight: bold;"
            " background: %s; border-radius: 36px; }" % color)
        cv.addWidget(dot, 0, Qt.AlignCenter)

        name = QLabel("（%s 计时提醒）" % (self._timer.get("name") or "喝水"))
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet("color: %s; font-size: 12px; border: none;" % hi)
        cv.addWidget(name)

        msg = QLabel(self._message)
        msg.setAlignment(Qt.AlignCenter)
        msg.setWordWrap(True)
        msg.setFont(QFont("Microsoft YaHei", 17, QFont.Bold))
        msg.setStyleSheet("color: %s; font-size: 17px; border: none;" % tx)
        cv.addWidget(msg)

        cv.addStretch(1)

        confirm_text = "已喝水 💧" if (self._timer.get("id") == "drink") else "知道了 ✓"
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        btn_snooze = QPushButton("稍后提醒")
        btn_snooze.setCursor(Qt.PointingHandCursor)
        btn_snooze.setStyleSheet(
            "QPushButton { background: transparent; color: %s; border: 1px solid %s;"
            " border-radius: 10px; padding: 10px 18px; font-size: 13px; }" % (hi, border))
        btn_snooze.clicked.connect(self._on_snooze)
        btn_row.addWidget(btn_snooze)

        btn_ok = QPushButton(confirm_text)
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet(
            "QPushButton { background: %s; color: #FFF; border: none; border-radius: 10px;"
            " padding: 10px 22px; font-size: 13px; font-weight: bold; }" % ac)
        btn_ok.clicked.connect(self._on_confirm)
        btn_row.addWidget(btn_ok)

        cv.addLayout(btn_row)
        root.addWidget(card)

    def _on_confirm(self):
        self.confirmed.emit(self._timer.get("id") or "")
        self._animate_close()

    def _on_snooze(self):
        self.snoozed.emit(self._timer.get("id") or "")
        self._animate_close()

    def _animate_close(self):
        if self._closing:
            return
        self._closing = True
        self._anim_out.start()

    def _real_close(self):
        self.close()

    def show_on_screen(self, screen=None):
        if screen is not None:
            self._screen = screen
        if self._fullscreen:
            self.showFullScreen()
        else:
            self.show()
        if self._screen is not None:
            g = self._screen.geometry()
            if self._fullscreen:
                self.setGeometry(g)
            else:
                self.move(g.center().x() - self.width() // 2,
                          g.center().y() - self.height() // 2)
        # 确保窗口激活，避免首次点击只激活窗口
        self.raise_()
        self.activateWindow()
        self._anim_in.start()
        if self._sound:
            self._play_sound()

    def paintEvent(self, event):
        if not self._fullscreen:
            return
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 150))
        p.end()

    @staticmethod
    def _play_sound():
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            try:
                QApplication.beep()
            except Exception:
                pass
