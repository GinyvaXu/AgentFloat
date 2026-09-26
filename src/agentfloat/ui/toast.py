# -*- coding: utf-8 -*-
"""AgentFloat — 轻量浮层提示（启动反馈气泡）

点按浮球启动 Agent 后，在浮球旁弹出一枚小气泡（弹簧入场 + 停留 + 淡出），
给用户「点按已生效、正在启动」的即时反馈（P2 解决「点按响应迟滞」）。
无交互、不抢焦点、不拦截鼠标。
"""
from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QWidget

from agentfloat.core.theme import get_colors
from agentfloat.ui.motion import Tokens as MotionTokens, motion, spring

_PAD_X = 14
_PAD_Y = 9
_GAP = 10                 # 与锚点浮球的间距
_DURATION_MS = 1500
_FONT_PT = 9


class LaunchToast(QWidget):
    """启动反馈气泡（单例复用）"""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._text = ""
        self._theme = "light"
        self._p = 0.0
        self._p_state = spring(0.0, MotionTokens.PRESS)
        self._cancel_anim = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

    # ── 公共 API ──────────────────────────────────────
    def show_for(self, anchor, text, theme="light", duration_ms=_DURATION_MS):
        """在 anchor（浮球窗口）旁弹出气泡"""
        self._text = str(text)
        self._theme = theme or "light"
        w, h = self._measure()
        self.setFixedSize(w, h)
        self._place(anchor)
        if self._cancel_anim is not None:
            self._cancel_anim()
            self._cancel_anim = None
        self._hide_timer.stop()
        if not self.isVisible():
            self._p_state.jump(0.0)
            self._p = 0.0
            self.show()
        self.raise_()
        self._p_state.set_params(*MotionTokens.PRESS)
        self._cancel_anim = motion().animate_to(self._p_state, 1.0, self._on_progress)
        self._hide_timer.start(int(duration_ms))

    # ── 内部 ──────────────────────────────────────────
    def _font(self):
        return QFont("Microsoft YaHei", _FONT_PT, QFont.DemiBold)

    def _measure(self):
        fm = QFontMetrics(self._font())
        tw = fm.horizontalAdvance(self._text)
        return _PAD_X * 2 + 14 + 6 + tw, _PAD_Y * 2 + max(18, fm.height())

    def _place(self, anchor):
        try:
            g = anchor.frameGeometry()
        except Exception:
            g = None
        screen = None
        if g is not None:
            screen = QApplication.screenAt(g.center())
        screen = screen or QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else None
        w, h = self.width(), self.height()
        if g is not None:
            x = g.right() + _GAP
            y = g.center().y() - h // 2
            if geo is not None and x + w > geo.right():
                x = g.left() - w - _GAP
        else:
            x, y = 40, 40
        if geo is not None:
            x = max(geo.left() + 4, min(x, geo.right() - w - 4))
            y = max(geo.top() + 4, min(y, geo.bottom() - h - 4))
        self.move(int(x), int(y))

    def _on_progress(self, v):
        self._p = max(0.0, min(1.0, float(v)))
        self.update()

    def _fade_out(self):
        if self._cancel_anim is not None:
            self._cancel_anim()
        self._p_state.set_params(*MotionTokens.RING_CLOSE)
        self._cancel_anim = motion().animate_to(
            self._p_state, 0.0, self._on_progress, on_done=self.hide)

    # ── 绘制 ──────────────────────────────────────────
    def paintEvent(self, event):
        if self._p <= 0.001:
            return
        c = get_colors(self._theme)
        is_dark = self._theme == "dark"
        if is_dark:
            bg = QColor(44, 44, 46, 242)
            border = QColor(255, 255, 255, 36)
            text_c = QColor(245, 245, 247)
        else:
            bg = QColor(255, 255, 255, 244)
            border = QColor(0, 0, 0, 30)
            text_c = QColor(29, 29, 31)
        accent = QColor(*c["ACCENT"])

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self._p)
        s = 0.94 + 0.06 * self._p
        cx, cy = self.width() / 2.0, self.height() / 2.0
        p.translate(cx, cy)
        p.scale(s, s)
        p.translate(-cx, -cy)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        radius = rect.height() / 2.0 - 0.5
        p.setPen(QPen(border, 1.0))
        p.setBrush(bg)
        p.drawRoundedRect(rect, radius, radius)

        # 品牌色圆点（呼吸感：随入场进度轻微放大）
        dot_r = 3.5 + 1.5 * self._p
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawEllipse(QRectF(_PAD_X - 3.5, cy - dot_r, dot_r * 2, dot_r * 2))

        # 文本
        p.setPen(text_c)
        p.setFont(self._font())
        text_rect = QRectF(_PAD_X + 14 + 6, 0, self.width() - (_PAD_X + 14 + 6) - _PAD_X,
                           self.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self._text)
        p.end()
