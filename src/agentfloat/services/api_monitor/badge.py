# -*- coding: utf-8 -*-
"""API 余额显示框（PATCH 3.5.1 重做）

- 半透明小框（与浮球同款圆角/描边/半透明观感），位于浮球上方或下方，可拖动自由调整偏移
- 多行模块化：每行 = 标题 + 数值（设置中自定义行数/来源/显示方式，见 badge_rows）
- 字符完整：按最长行自适应尺寸，并在屏幕内钳制，文本不裁切
"""
import logging

from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics

_logger = logging.getLogger("AgentFloat")

FONT_FAMILY = "Microsoft YaHei"

BADGE_THEMES = {
    "light": {
        "bg":     (250, 250, 252, 205),
        "border": (0, 0, 0, 28),
        "text":   (28, 28, 30),
        "dim":    (110, 110, 115),
        "warn":   (255, 59, 48),     # iOS 红 #FF3B30
        "sep":    (0, 0, 0, 20),
    },
    "dark": {
        "bg":     (28, 28, 32, 196),
        "border": (255, 255, 255, 38),
        "text":   (242, 242, 247),
        "dim":    (155, 155, 162),
        "warn":   (255, 105, 97),
        "sep":    (255, 255, 255, 26),
    },
}


class ApiBalanceBadge(QWidget):
    """余额显示框：支持多行（标题 值）与拖动调整位置"""

    MARGIN = 6        # 与浮球间距
    H_PAD = 10        # 内边距-水平
    V_PAD = 5         # 内边距-垂直
    RADIUS = 12       # 圆角（与浮球同款观感）
    LINE_GAP = 3      # 行间距
    TITLE_GAP = 6     # 标题与数值间距

    def __init__(self, parent_float=None, on_offset_changed=None):
        super().__init__()
        self._parent_float = parent_float
        self._on_offset_changed = on_offset_changed
        self._theme = "light"
        self._rows = []                  # [(title, value)]
        self._is_low = False
        self._is_error = False
        self._warn_threshold = 5.0
        self._pos_mode = "top"           # top | bottom
        self._dx = 0                     # 相对默认位置的偏移（可拖动调整）
        self._dy = 0
        self._dragging = False
        self._drag_start = None
        self._drag_base = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))
        self.setCursor(Qt.SizeAllCursor)

    # ── 配置 ─────────────────────────────────────
    def set_theme(self, theme: str):
        self._theme = theme if theme in BADGE_THEMES else "light"
        self.update()

    def set_warn_threshold(self, value):
        try:
            self._warn_threshold = max(0.0, float(value))
        except (TypeError, ValueError):
            self._warn_threshold = 5.0

    def set_position_mode(self, mode):
        self._pos_mode = "bottom" if str(mode) == "bottom" else "top"
        self.sync_position()

    def set_offset(self, dx, dy):
        try:
            self._dx, self._dy = int(dx or 0), int(dy or 0)
        except (TypeError, ValueError):
            self._dx = self._dy = 0
        self.sync_position()

    def offset(self):
        return self._dx, self._dy

    # ── 内容 ─────────────────────────────────────
    def set_rows(self, rows, is_low=None, is_error=False):
        """rows: [(标题, 数值)]；标题可为空"""
        self._rows = [(str(t or ""), str(v if v is not None else "--")) for t, v in (rows or [])]
        if not self._rows:
            self._rows = [("", "--")]
        self._is_error = bool(is_error)
        if is_low is not None:
            self._is_low = bool(is_low) and not is_error
        else:
            self._is_low = False
        self._sync_size()
        self.sync_position()
        self.update()

    def update_balance(self, text: str, value=None, is_error: bool = False, is_low=None):
        """兼容入口：单行（无标题）"""
        low = is_low
        if low is None and value is not None and self._warn_threshold > 0 and not is_error:
            try:
                low = float(value) < self._warn_threshold
            except (TypeError, ValueError):
                low = None
        self.set_rows([("", (text or "--").strip())], is_low=low, is_error=is_error)

    # ── 尺寸与位置 ────────────────────────────────
    def _sync_size(self):
        fm = QFontMetrics(self.font())
        w = 0
        for title, value in self._rows:
            lw = fm.horizontalAdvance(value)
            if title:
                lw += fm.horizontalAdvance(title) + self.TITLE_GAP
            w = max(w, lw)
        h = len(self._rows) * fm.height() + max(0, len(self._rows) - 1) * self.LINE_GAP
        self.setFixedSize(max(w + self.H_PAD * 2, 34), h + self.V_PAD * 2)

    def sync_position(self):
        pf = self._parent_float
        if pf is None:
            return
        x = pf.x() + (pf.width() - self.width()) // 2 + self._dx
        if self._pos_mode == "bottom":
            y = pf.y() + pf.height() + self.MARGIN + self._dy
        else:
            y = pf.y() - self.height() - self.MARGIN + self._dy
        # 屏幕内钳制：保证小框与文字完整可见
        try:
            screen = QApplication.screenAt(pf.geometry().center()) or QApplication.primaryScreen()
            g = screen.availableGeometry()
            x = max(g.left() + 4, min(x, g.right() - self.width() - 4))
            y = max(g.top() + 4, min(y, g.bottom() - self.height() - 4))
        except Exception:  # noqa: BLE001
            pass
        self.move(int(x), int(y))

    # ── 拖动自由调整 ──────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPos()
            self._drag_base = QPoint(self.x(), self.y())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._drag_start is not None:
            delta = event.globalPos() - self._drag_start
            self.move(self._drag_base + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            pf = self._parent_float
            if pf is not None:
                base_x = pf.x() + (pf.width() - self.width()) // 2
                if self._pos_mode == "bottom":
                    base_y = pf.y() + pf.height() + self.MARGIN
                else:
                    base_y = pf.y() - self.height() - self.MARGIN
                self._dx = int(self.x() - base_x)
                self._dy = int((self._drag_base.y() + (event.globalPos().y() - self._drag_start.y())) - base_y)
                if self._on_offset_changed:
                    try:
                        self._on_offset_changed(self._dx, self._dy)
                    except Exception:  # noqa: BLE001
                        _logger.debug("角标位置保存失败", exc_info=True)
            self.sync_position()
        super().mouseReleaseEvent(event)

    # ── 绘制 ─────────────────────────────────────
    def paintEvent(self, event):
        if not self._rows:
            return
        t = BADGE_THEMES[self._theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QPen(QColor(*t["border"]), 1))
        p.setBrush(QColor(*t["bg"]))
        p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)

        fm = QFontMetrics(self.font())
        v_color = QColor(*(t["warn"] if (self._is_low or self._is_error) else t["text"]))
        t_color = QColor(*t["dim"])
        line_h = fm.height()
        y = self.V_PAD
        for title, value in self._rows:
            x = self.H_PAD
            if title:
                p.setPen(t_color)
                p.drawText(x, y + fm.ascent(), title)
                x += fm.horizontalAdvance(title) + self.TITLE_GAP
            p.setPen(v_color)
            p.drawText(x, y + fm.ascent(), value)
            y += line_h + self.LINE_GAP
