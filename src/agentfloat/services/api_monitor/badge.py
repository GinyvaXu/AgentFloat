"""
API ???? ? ??????
?????????????????????????????
?? v1.6.0 ? ApiMonitorPanel???/??/??????????
"""
import logging
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QColor, QPen, QFont

_logger = logging.getLogger("AgentFloat")

FONT_FAMILY = "Microsoft YaHei"

BADGE_THEMES = {
    "light": {
        "bg":     (255, 255, 255, 232),
        "border": (0, 0, 0, 55),
        "text":   (28, 28, 30),
        "warn":   (255, 59, 48),    # iOS ? #FF3B30
    },
    "dark": {
        "bg":     (44, 44, 46, 232),
        "border": (255, 255, 255, 45),
        "text":   (242, 242, 247),
        "warn":   (255, 105, 97),
    },
}


class ApiBalanceBadge(QWidget):
    """?????? ? ????????????????????"""

    MARGIN = 5        # ????????
    H_PAD = 10        # ???????????
    V_PAD = 4         # ???????????
    RADIUS = 7        # ????

    def __init__(self, parent_float=None):
        super().__init__()
        self._parent_float = parent_float
        self._theme = "light"
        self._text = ""
        self._is_low = False
        self._is_error = False
        self._warn_threshold = 5.0

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # ???????????????????????
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFont(QFont(FONT_FAMILY, 9, QFont.Bold))

    # ?? ???? ?????????????????????????????????
    def set_theme(self, theme: str):
        self._theme = theme if theme in BADGE_THEMES else "light"
        self.update()

    def set_warn_threshold(self, value):
        try:
            self._warn_threshold = max(0.0, float(value))
        except (TypeError, ValueError):
            self._warn_threshold = 5.0

    def update_balance(self, text: str, value=None, is_error: bool = False):
        """???????value ????????????is_error ??????"""
        self._text = (text or "--").strip()
        self._is_error = is_error
        self._is_low = False
        if value is not None and self._warn_threshold > 0 and not is_error:
            try:
                self._is_low = float(value) < self._warn_threshold
            except (TypeError, ValueError):
                pass
        self._resize_to_text()
        self.sync_position()
        self.update()

    # ?? ?? ?????????????????????????????????????
    def _resize_to_text(self):
        fm = self.fontMetrics()
        w = fm.horizontalAdvance(self._text) + self.H_PAD * 2
        h = fm.height() + self.V_PAD * 2
        self.setFixedSize(max(w, 28), h)

    def sync_position(self):
        pf = self._parent_float
        if pf is None:
            return
        x = pf.x() + (pf.width() - self.width()) // 2
        y = pf.y() - self.height() - self.MARGIN
        # ?????????????
        try:
            screen = QApplication.screenAt(pf.geometry().center()) or QApplication.primaryScreen()
            if y < screen.availableGeometry().top():
                y = pf.y() + pf.height() + self.MARGIN
        except Exception:
            pass
        self.move(x, y)

    # ?? ?? ?????????????????????????????????????
    def paintEvent(self, event):
        if not self._text:
            return
        t = BADGE_THEMES[self._theme]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QPen(QColor(*t["border"]), 1))
        p.setBrush(QColor(*t["bg"]))
        p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        fg = t["warn"] if (self._is_low or self._is_error) else t["text"]
        p.setPen(QColor(*fg))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)
