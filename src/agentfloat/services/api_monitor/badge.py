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
    """余额显示框：支持多行（标题 值）与拖动调整位置/大小/不透明度"""

    MARGIN = 6        # 与浮球间距
    H_PAD = 10        # 内边距-水平（随缩放）
    V_PAD = 5         # 内边距-垂直（随缩放）
    RADIUS = 12       # 圆角（与浮球同款观感，随缩放）
    LINE_GAP = 3      # 行间距（随缩放）
    TITLE_GAP = 6     # 标题与数值间距（随缩放）
    BASE_PT = 9.0     # 基准字号
    MIN_SCALE = 0.7
    MAX_SCALE = 2.0
    RESIZE_ZONE = 18  # 右下角缩放热区（像素）

    def __init__(self, parent_float=None, on_offset_changed=None, on_style_changed=None):
        super().__init__()
        self._parent_float = parent_float
        self._on_offset_changed = on_offset_changed
        self._on_style_changed = on_style_changed
        self._theme = "light"
        self._rows = []                  # [(title, value)]
        self._is_low = False
        self._is_error = False
        self._warn_threshold = 5.0
        self._pos_mode = "top"           # top | bottom
        self._dx = 0                     # 相对默认位置的偏移（可拖动调整）
        self._dy = 0
        self._scale = 1.0                # PATCH 3.5.4：大小（字号/内边距同步缩放）
        self._opacity = 0.88             # PATCH 3.5.4：背景不透明度（文字保持清晰）
        self._dragging = False
        self._resizing = False
        self._drag_start = None
        self._drag_base = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._apply_font()
        self.setCursor(Qt.SizeAllCursor)

    def _apply_font(self):
        font = QFont(FONT_FAMILY, int(self.BASE_PT), QFont.Bold)
        font.setPointSizeF(max(6.0, self.BASE_PT * self._scale))
        self.setFont(font)

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

    # PATCH 3.5.4：大小 / 不透明度
    def set_scale(self, scale, persist=False):
        try:
            value = float(scale)
        except (TypeError, ValueError):
            value = 1.0
        self._scale = max(self.MIN_SCALE, min(self.MAX_SCALE, value))
        self._apply_font()
        self._sync_size()
        self.sync_position()
        self.update()
        if persist and self._on_style_changed:
            self._on_style_changed(self._scale, self._opacity)

    def scale(self):
        return self._scale

    def set_opacity(self, opacity, persist=False):
        try:
            value = float(opacity)
        except (TypeError, ValueError):
            value = 0.88
        self._opacity = max(0.25, min(1.0, value))
        self.update()
        if persist and self._on_style_changed:
            self._on_style_changed(self._scale, self._opacity)

    def opacity(self):
        return self._opacity

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
                lw += fm.horizontalAdvance(title) + int(self.TITLE_GAP * self._scale)
            w = max(w, lw)
        gap = int(self.LINE_GAP * self._scale)
        h = len(self._rows) * fm.height() + max(0, len(self._rows) - 1) * gap
        h_pad = int(self.H_PAD * self._scale)
        v_pad = int(self.V_PAD * self._scale)
        self.setFixedSize(max(w + h_pad * 2, int(34 * self._scale)), h + v_pad * 2)

    def sync_position(self):
        pf = self._parent_float
        if pf is None:
            return
        margin = int(self.MARGIN * self._scale)
        x = pf.x() + (pf.width() - self.width()) // 2 + self._dx
        if self._pos_mode == "bottom":
            y = pf.y() + pf.height() + margin + self._dy
        else:
            y = pf.y() - self.height() - margin + self._dy
        # 屏幕内钳制：保证小框与文字完整可见
        try:
            screen = QApplication.screenAt(pf.geometry().center()) or QApplication.primaryScreen()
            g = screen.availableGeometry()
            x = max(g.left() + 4, min(x, g.right() - self.width() - 4))
            y = max(g.top() + 4, min(y, g.bottom() - self.height() - 4))
        except Exception:  # noqa: BLE001
            pass
        self.move(int(x), int(y))

    # ── 拖动移动 / 右下角缩放 / 滚轮调整 ──────────────
    def _in_resize_zone(self, pos):
        return pos.x() >= self.width() - self.RESIZE_ZONE and pos.y() >= self.height() - self.RESIZE_ZONE

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.globalPos()
            self._drag_base = QPoint(self.x(), self.y())
            self._resize_start_scale = self._scale
            if self._in_resize_zone(event.pos()):
                self._resizing = True
                self._dragging = False
            else:
                self._dragging = True
                self._resizing = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing and self._drag_start is not None:
            delta = max(event.globalPos().x() - self._drag_start.x(),
                        event.globalPos().y() - self._drag_start.y())
            self.set_scale(self._resize_start_scale + delta / 45.0)
        elif self._dragging and self._drag_start is not None:
            delta = event.globalPos() - self._drag_start
            self.move(self._drag_base + delta)
        else:
            self.setCursor(Qt.SizeFDiagCursor if self._in_resize_zone(event.pos()) else Qt.SizeAllCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and (self._dragging or self._resizing):
            was_resize = self._resizing
            self._dragging = False
            self._resizing = False
            if was_resize:
                self.set_scale(self._scale, persist=True)
            elif self._parent_float is not None:
                pf = self._parent_float
                base_x = pf.x() + (pf.width() - self.width()) // 2
                if self._pos_mode == "bottom":
                    base_y = pf.y() + pf.height() + int(self.MARGIN * self._scale)
                else:
                    base_y = pf.y() - self.height() - int(self.MARGIN * self._scale)
                self._dx = int(self.x() - base_x)
                self._dy = int((self._drag_base.y() + (event.globalPos().y() - self._drag_start.y())) - base_y)
                if self._on_offset_changed:
                    try:
                        self._on_offset_changed(self._dx, self._dy)
                    except Exception:  # noqa: BLE001
                        _logger.debug("角标位置保存失败", exc_info=True)
            self.sync_position()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """滚轮 = 调整大小；Ctrl+滚轮 = 调整背景不透明度"""
        step = event.angleDelta().y() / 120.0
        if step:
            if event.modifiers() & Qt.ControlModifier:
                self.set_opacity(self._opacity + step * 0.05, persist=True)
            else:
                self.set_scale(self._scale + step * 0.05, persist=True)
        event.accept()

    # ── 绘制 ─────────────────────────────────────
    def paintEvent(self, event):
        if not self._rows:
            return
        t = BADGE_THEMES[self._theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        bg, border = t["bg"], t["border"]
        radius = int(self.RADIUS * self._scale)
        p.setPen(QPen(QColor(border[0], border[1], border[2], int(border[3] * self._opacity)), 1))
        p.setBrush(QColor(bg[0], bg[1], bg[2], int(bg[3] * self._opacity)))
        p.drawRoundedRect(rect, radius, radius)

        fm = QFontMetrics(self.font())
        v_color = QColor(*(t["warn"] if (self._is_low or self._is_error) else t["text"]))
        t_color = QColor(*t["dim"])
        line_h = fm.height()
        h_pad = int(self.H_PAD * self._scale)
        v_pad = int(self.V_PAD * self._scale)
        title_gap = int(self.TITLE_GAP * self._scale)
        line_gap = int(self.LINE_GAP * self._scale)
        y = v_pad
        for title, value in self._rows:
            x = h_pad
            if title:
                p.setPen(t_color)
                p.drawText(x, y + fm.ascent(), title)
                x += fm.horizontalAdvance(title) + title_gap
            p.setPen(v_color)
            p.drawText(x, y + fm.ascent(), value)
            y += line_h + line_gap
