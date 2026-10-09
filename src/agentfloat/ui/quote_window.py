# -*- coding: utf-8 -*-
"""语录浮窗（v3.10.0）：单击浮球弹出的半透明卡片

设计：
- 毛玻璃卡片（半透明底 + 细边框 + 投影 + 圆角），配色跟随语录分类
- 大号装饰引号 + 分类徽章 + 正文（自动换行/自适应字号）+ 作者与出处
- 底部：换一条 / 复制 / 关闭 + 自动关闭进度线
- 动效：淡入 + 上滑；鼠标悬停暂停自动关闭；可拖动；Esc 关闭
- 数据：web/data/quotes.json（由 docs/浮窗语录库-审核稿.md 解析生成）

纯逻辑（选句/去重/加权）与绘制分离，便于单测。
"""
import json
import os
import random

from PyQt5.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, Qt,
                          QTimer, pyqtSignal)
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from agentfloat.core.paths import _resolve_path
from agentfloat.core.theme import get_colors
from agentfloat.ui.tokens import FONT, RADIUS, SPACE

CARD_W = 420
NO_REPEAT = 60          # 最近 N 条不重复
DEFAULT_CATS = ("nietzsche", "philosophy", "code", "anime", "tips")


# ── 数据层（可单测）────────────────────────────────
def quotes_path():
    """语录数据路径（随包 assets/data 或 web/data 双位置兼容）"""
    for rel in (("web", "data", "quotes.json"), ("data", "quotes.json")):
        p = _resolve_path(*rel)
        if os.path.isfile(p):
            return p
    return _resolve_path("web", "data", "quotes.json")


class QuoteBank(object):
    """语录库：加载 JSON、按分类过滤、加权随机且不近期重复"""

    def __init__(self, path=None, rng=None):
        self._path = path or quotes_path()
        self._rng = rng or random.Random()
        self._cats = {}
        self.quotes = []
        self.categories = []
        self._recent = []
        self.load()

    def load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (IOError, ValueError):
            data = {}
        self.categories = data.get("categories") or []
        self._cats = {c["id"]: c for c in self.categories}
        self.quotes = [q for q in (data.get("quotes") or []) if q.get("t")]
        return len(self.quotes)

    def cat_meta(self, cid):
        return self._cats.get(cid) or {"id": cid, "name": cid, "color": "#7F8C8D", "icon": "❝"}

    def available(self, enabled_cats=None):
        cats = set(enabled_cats or DEFAULT_CATS)
        return [q for q in self.quotes if q.get("c") in cats]

    def pick(self, enabled_cats=None):
        """加权随机选一条；尽量避开最近出现过的"""
        pool = self.available(enabled_cats)
        if not pool:
            return None
        fresh = [q for q in pool if id(q) not in self._recent and q["t"] not in self._recent]
        use = fresh or pool
        weights = [max(1, int(q.get("w") or 1)) for q in use]
        try:
            item = self._rng.choices(use, weights=weights, k=1)[0]
        except AttributeError:                       # Python < 3.6 兜底
            item = self._rng.choice(use)
        self._recent.append(item["t"])
        if len(self._recent) > NO_REPEAT:
            self._recent = self._recent[-NO_REPEAT:]
        return item

    def stats(self):
        return {"total": len(self.quotes), "categories": len(self.categories)}


# ── 浮窗 ──────────────────────────────────────────
class QuoteWindow(QWidget):
    """半透明语录卡片（贴浮球弹出）"""

    closed = pyqtSignal()
    copied = pyqtSignal(str)

    def __init__(self, bank=None, cfg=None, theme="light", parent=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("AgentFloat")
        self._bank = bank or QuoteBank()
        self._cfg = dict(cfg or {})
        self._theme = theme
        self._quote = None
        self._drag = None
        self._hover = False
        self._paused = False
        self._build()
        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.timeout.connect(self.close_window)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(260)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._progress = 0.0
        self._ptimer = QTimer(self)
        self._ptimer.setInterval(50)
        self._ptimer.timeout.connect(self._tick_progress)

    # ── 构建 ──────────────────────────────────────
    def _build(self):
        lay = QVBoxLayout(self)
        m = SPACE.lg
        lay.setContentsMargins(m, m, m, SPACE.md)
        lay.setSpacing(SPACE.sm)
        head = QHBoxLayout()
        self._chip = QLabel("❝")
        self._chip.setObjectName("quoteChip")
        head.addWidget(self._chip)
        head.addStretch(1)
        self._close = QPushButton("✕")
        self._close.setObjectName("quoteClose")
        self._close.setFixedSize(24, 24)
        self._close.clicked.connect(self.close_window)
        head.addWidget(self._close)
        lay.addLayout(head)

        self._text = QLabel("")
        self._text.setObjectName("quoteText")
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self._text)

        self._author = QLabel("")
        self._author.setObjectName("quoteAuthor")
        self._author.setAlignment(Qt.AlignRight)
        lay.addWidget(self._author)

        row = QHBoxLayout()
        row.setSpacing(SPACE.sm)
        row.addStretch(1)
        self._btn_next = QPushButton("换一条")
        self._btn_copy = QPushButton("复制")
        for b in (self._btn_next, self._btn_copy):
            b.setObjectName("quoteBtn")
        self._btn_next.clicked.connect(self.next_quote)
        self._btn_copy.clicked.connect(self.copy_quote)
        row.addWidget(self._btn_next)
        row.addWidget(self._btn_copy)
        lay.addLayout(row)
        self.setStyleSheet(self._css())
        self.setFixedWidth(CARD_W)

    def _css(self):
        c = get_colors(self._theme)
        tx = "#%02X%02X%02X" % tuple(c["TEXT"])
        hint = "#%02X%02X%02X" % tuple(c["HINT"])
        fs = int(self._cfg.get("font_size") or 15)
        return (
            "QLabel#quoteChip { color: %(acc)s; font-size: 17px; font-weight: 700; }"
            "QLabel#quoteText { color: %(tx)s; font-size: %(fs)dpx; line-height: 1.75; }"
            "QLabel#quoteAuthor { color: %(hint)s; font-size: %(fa)dpx; }"
            "QPushButton#quoteBtn { background: transparent; color: %(hint)s;"
            " border: 1px solid rgba(255,255,255,0.16); border-radius: %(r)dpx;"
            " padding: 5px 13px; font-size: %(fb)dpx; }"
            "QPushButton#quoteBtn:hover { color: %(tx)s; border-color: %(acc)s; }"
            "QPushButton#quoteClose { background: transparent; border: none; color: %(hint)s;"
            " font-size: 12px; }"
            "QPushButton#quoteClose:hover { color: #FF5F57; }"
            % {"tx": tx, "hint": hint, "acc": self._accent_hex(), "fs": fs,
               "fa": FONT.caption, "fb": FONT.body, "r": RADIUS.sm}
        )

    def _accent_hex(self):
        if self._quote:
            return self._bank.cat_meta(self._quote.get("c")).get("color") or "#0A84FF"
        return "#0A84FF" if self._theme == "light" else "#409CFF"

    # ── 内容 ──────────────────────────────────────
    def show_quote(self, quote=None, anchor_rect=None, screen_rect=None):
        """展示一条语录（默认随机取）；anchor_rect 为浮球的全局矩形"""
        self._quote = quote or self._bank.pick(self._cfg.get("categories"))
        if not self._quote:
            return False
        meta = self._bank.cat_meta(self._quote.get("c"))
        self._chip.setText("%s  %s" % (meta.get("icon") or "❝", meta.get("name") or ""))
        self._text.setText("“%s”" % self._quote.get("t", ""))
        src = self._quote.get("s") or ""
        self._author.setText("— %s%s" % (self._quote.get("a", ""),
                                         ("　%s" % src) if src else ""))
        self.setStyleSheet(self._css())
        self.adjustSize()
        self._place(anchor_rect, screen_rect)
        self._paused = False
        self._progress = 0.0
        secs = max(3, int(self._cfg.get("auto_close_s") or 12))
        self._auto.start(secs * 1000)
        self._ptimer.start()
        self.show()
        self.raise_()
        self._fade.stop()
        self.setWindowOpacity(0.0)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(float(self._cfg.get("opacity") or 0.95))
        self._fade.start()
        return True

    def _place(self, anchor_rect, screen_rect):
        """贴浮球放置（右→左→下→上，自动收进屏幕）"""
        from agentfloat.ui.onboarding import bubble_geometry
        ball = QRect(anchor_rect) if anchor_rect else QRect()
        if ball.isNull():
            scr = QApplication.primaryScreen()
            geo = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
            ball = QRect(geo.center().x(), geo.center().y(), 1, 1)
        else:
            scr = QApplication.screenAt(ball.center()) or QApplication.primaryScreen()
            geo = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
        size = (self.width(), self.height())
        rect, _side = bubble_geometry(ball, geo, size)
        start = QPoint(rect.left(), rect.top() + 14)
        self._slide.stop()
        self.move(start)
        self._slide.setStartValue(start)
        self._slide.setEndValue(rect.topLeft())
        self._slide.start()

    def next_quote(self):
        if self.show_quote(self._bank.pick(self._cfg.get("categories"))):
            return True
        return False

    def copy_quote(self):
        if not self._quote:
            return
        txt = "“%s” — %s %s" % (self._quote.get("t", ""), self._quote.get("a", ""),
                                self._quote.get("s", ""))
        try:
            QApplication.clipboard().setText(txt.strip())
            self.copied.emit(txt.strip())
            self._btn_copy.setText("已复制")
            QTimer.singleShot(1200, lambda: self._btn_copy.setText("复制"))
        except Exception:  # noqa: BLE001
            pass

    def close_window(self):
        self._auto.stop()
        self._ptimer.stop()
        try:
            self._fade.stop()
        except Exception:  # noqa: BLE001
            pass
        self.hide()
        self.closed.emit()

    # ── 自动关闭进度 + 悬停暂停 ────────────────────
    def _tick_progress(self):
        if self._paused:
            return
        self._progress = min(1.0, self._progress + 0.05 / max(1.0, (self._cfg.get("auto_close_s") or 12)))
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self._paused = True
        self._auto.stop()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._paused = False
        secs = max(3, int(self._cfg.get("auto_close_s") or 12))
        self._auto.start(int(secs * (1.0 - self._progress) * 1000))
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_window()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.next_quote()
        else:
            super().keyPressEvent(event)

    # ── 拖动 ──────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPos() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        super().mouseReleaseEvent(event)

    # ── 绘制：毛玻璃底 + 分类色装饰 ────────────────
    def paintEvent(self, event):
        try:
            self._paint()
        except Exception:  # noqa: BLE001
            pass

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        rad = float(RADIUS.lg)
        # 投影
        p.setPen(Qt.NoPen)
        for off, k in ((3.0, 0.30), (1.5, 0.22)):
            p.setBrush(QColor(0, 0, 0, int(70 * k)))
            p.drawRoundedRect(r.adjusted(off, off + 1.5, off, off + 1.5), rad, rad)
        # 玻璃底（跟随主题 + 不透明度）
        dark = self._theme != "light"
        base = QColor(28, 28, 32) if dark else QColor(252, 252, 255)
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        c1 = QColor(base)
        c1.setAlpha(238 if dark else 244)
        c2 = QColor(base)
        c2.setAlpha(222 if dark else 232)
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        p.setBrush(grad)
        p.drawRoundedRect(r, rad, rad)
        # 分类色描边 + 顶部高光
        acc = QColor(self._accent_hex())
        pen = QPen(QColor(acc.red(), acc.green(), acc.blue(), 150), 1.2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, rad, rad)
        # 左上角装饰大引号（分类色，低透明度）
        p.setPen(QColor(acc.red(), acc.green(), acc.blue(), 46))
        f = QFont()
        f.setPointSizeF(46.0)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(10, -6, 120, 90), Qt.AlignLeft | Qt.AlignTop, "“")
        # 自动关闭进度线（底部，悬停时高亮）
        line_w = (self.width() - 24) * (1.0 - self._progress)
        if line_w > 1:
            p.setPen(Qt.NoPen)
            a = 120 if self._hover else 70
            p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), a))
            p.drawRoundedRect(QRectF(12, self.height() - 5.0, line_w, 2.0), 1.0, 1.0)
        p.end()
