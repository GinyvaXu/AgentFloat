# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — 悬停 / 长按环绕菜单

QPainter 自绘扇区圆环（避开 Windows 层叠模糊 API 的坑），
参考 RadialPopMenu 交错动画 + Nimbus 自绘方案。
"""
import math
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QCursor
from PyQt5.QtWidgets import QWidget, QApplication

from af_theme import get_colors


class RadialMenuItem(object):
    __slots__ = ("id", "label", "subtitle", "color", "char")

    def __init__(self, item_id, label, subtitle="", color="#5B8DEF", char=""):
        self.id = item_id
        self.label = label
        self.subtitle = subtitle
        self.color = color
        self.char = char or (label[0] if label else "?")


class RadialMenu(QWidget):
    action_triggered = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self._items = []
        self._outer = 120          # 外环半径
        self._inner = 46           # 中心孔半径
        self._pad = 28             # 阴影边距
        self._progress = 0.0
        self._hover_idx = -1
        self._theme = "light"
        self._anchor_rect = None
        self._sector_cache = []    # (id, start_angle, sweep_angle)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)
        self._anim.finished.connect(self._on_anim_finished)

        self._poll = QTimer(self)
        self._poll.setInterval(120)
        self._poll.timeout.connect(self._poll_cursor)

        self._close_pending = False

    # ── 公开接口 ─────────────────────────────────
    def set_theme(self, theme):
        self._theme = theme
        if self.isVisible():
            self.update()

    def set_items(self, items, radius=None):
        self._items = list(items)
        if radius:
            self._outer = int(radius)
            self._inner = max(28, int(radius * 0.36))

    def open_at(self, center_global, anchor_rect=None):
        """center_global: 环绕中心（全局坐标）；anchor_rect: 触发浮窗区域，用于保持打开"""
        self._anchor_rect = anchor_rect
        side = int((self._outer + self._pad) * 2)
        self.setFixedSize(side, side)
        x = int(center_global.x() - side / 2)
        y = int(center_global.y() - side / 2)
        # 边缘防溢出（SAO 思路：钳制到所在屏幕可用区域）
        screen = QApplication.screenAt(center_global)
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(x, geo.right() - side + 1))
            y = max(geo.top(), min(y, geo.bottom() - side + 1))
        self.move(x, y)
        self._progress = 0.0
        self._hover_idx = -1
        self._sector_cache = []
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._poll.start()

    def close_menu(self):
        self._poll.stop()
        self._anim.stop()
        self.hide()

    # ── 动画 ────────────────────────────────────
    def _on_anim_value(self, v):
        self._progress = float(v)
        self.update()

    def _on_anim_finished(self):
        self._progress = 1.0
        self.update()

    # ── 命中测试 ─────────────────────────────────
    def _center(self):
        return QPointF(self.width() / 2.0, self.height() / 2.0)

    def _sector_at(self, global_pos):
        c = self._center()
        p = self.mapFromGlobal(global_pos)
        dx, dy = p.x() - c.x(), p.y() - c.y()
        dist = math.hypot(dx, dy)
        if dist < self._inner - 6 or dist > self._outer + 6:
            return -1
        angle = (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0
        n = len(self._items)
        if n == 0:
            return -1
        sweep = 360.0 / n
        idx = int(angle // sweep)
        return idx if idx < n else -1

    def _poll_cursor(self):
        if not self.isVisible():
            return
        pos = QCursor.pos()
        # 用 geometry()（顶层窗口为全局坐标）替代 frameGeometry()，
        # 避免 WA_ShowWithoutActivating 下 frameGeometry 坐标偏移导致菜单误关
        in_menu = self.geometry().contains(pos)
        in_anchor = self._anchor_rect is not None and self._anchor_rect.contains(pos)
        if in_menu:
            self._close_pending = False
            idx = self._sector_at(pos)
            if idx != self._hover_idx:
                self._hover_idx = idx
                self.update()
        elif in_anchor:
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.update()
        else:
            if self._close_pending:
                self.close_menu()
            else:
                self._close_pending = True
                QTimer.singleShot(250, self._flush_close)

    def _flush_close(self):
        if self._close_pending and self.isVisible():
            self.close_menu()

    # ── 鼠标 ────────────────────────────────────
    def mousePressEvent(self, event):
        idx = self._sector_at(event.globalPos())
        if idx < 0:
            self.close_menu()
            event.accept()
            return
        event.accept()

    def mouseReleaseEvent(self, event):
        idx = self._sector_at(event.globalPos())
        if 0 <= idx < len(self._items):
            item = self._items[idx]
            self.close_menu()
            self.action_triggered.emit(item.id)
        else:
            self.close_menu()
        event.accept()

    # ── 绘制 ────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            self._render_paint(painter)
        except Exception:
            # 绘制异常不破坏 Qt paint 状态；仅记录一次避免刷屏
            if not getattr(self, "_paint_error_logged", False):
                self._paint_error_logged = True
                import logging, traceback
                logging.getLogger("AgentFloat").error(
                    "环绕菜单绘制异常:\n%s", traceback.format_exc())
        finally:
            painter.end()


    def _render_paint(self, painter):
        painter.setRenderHint(QPainter.Antialiasing)
        c = get_colors(self._theme)
        is_dark = self._theme == "dark"
        ring_bg = QColor(30, 30, 34, 208) if is_dark else QColor(255, 255, 255, 216)
        ring_border = QColor(255, 255, 255, 60) if is_dark else QColor(0, 0, 0, 36)
        text_c = QColor(*c["TEXT"])
        center_pt = self._center()
        n = len(self._items)
        if n == 0:
            return
        sweep = 360.0 / n
        total = float(n + 2)

        painter.save()
        painter.translate(center_pt)

        # 底层圆环
        painter.setPen(QPen(ring_border, 1.5))
        painter.setBrush(ring_bg)
        painter.drawEllipse(QRectF(-self._outer, -self._outer, self._outer * 2, self._outer * 2))

        # 中心孔
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.drawEllipse(QRectF(-self._inner, -self._inner, self._inner * 2, self._inner * 2))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        self._sector_cache = []
        for i, item in enumerate(self._items):
            # 交错弹出进度
            eff = max(0.0, min(1.0, (self._progress * total - i) / 1.0))
            if eff <= 0.01:
                continue
            a0 = -90.0 + i * sweep
            drawn_sweep = sweep * eff
            self._sector_cache.append((item.id, a0, drawn_sweep))
            base = QColor(item.color)
            alpha = 36 + int(96 * eff)
            if i == self._hover_idx:
                alpha = 235
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(base.red(), base.green(), base.blue(), alpha))
            path = QPainterPath()
            path.moveTo(self._polar(a0, self._outer))
            path.arcTo(QRectF(-self._outer, -self._outer, self._outer * 2, self._outer * 2),
                       a0, drawn_sweep)
            path.arcTo(QRectF(-self._inner, -self._inner, self._inner * 2, self._inner * 2),
                       a0 + drawn_sweep, -drawn_sweep)
            path.closeSubpath()
            painter.drawPath(path)

            # 分隔线
            if i > 0 and eff > 0.5:
                painter.setPen(QPen(ring_border, 1))
                painter.drawLine(self._polar(a0, self._inner), self._polar(a0, self._outer))

            # 文字
            mid = a0 + drawn_sweep / 2.0
            rad = self._outer * 0.68
            _pt = self._polar(mid, rad)
            tx, ty = _pt.x(), _pt.y()
            painter.setPen(QColor(255, 255, 255) if i == self._hover_idx else text_c)
            char_font = QFont("Segoe UI", 15, QFont.Bold)
            painter.setFont(char_font)
            painter.drawText(QRectF(tx - 40, ty - 34, 80, 26), Qt.AlignCenter, item.char)
            label_font = QFont("Microsoft YaHei", 8)
            painter.setFont(label_font)
            painter.setPen(QColor(255, 255, 255, 220) if i == self._hover_idx else
                           QColor(text_c.red(), text_c.green(), text_c.blue(), 200))
            painter.drawText(QRectF(tx - 55, ty - 8, 110, 18), Qt.AlignCenter, item.label)

        painter.restore()

        # 顶部小三角指示（指向 12 点方向的选中感）
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*c["ACCENT"]))
        tri = QPainterPath()
        tri.moveTo(center_pt.x() - 7, center_pt.y() - self._inner + 10)
        tri.lineTo(center_pt.x() + 7, center_pt.y() - self._inner + 10)
        tri.lineTo(center_pt.x(), center_pt.y() - self._inner - 4)
        tri.closeSubpath()
        painter.drawPath(tri)

    def _polar(self, angle_deg, radius):
        rad = math.radians(angle_deg)
        return QPointF(math.cos(rad) * radius, math.sin(rad) * radius)

    def hideEvent(self, event):
        self._poll.stop()
        super().hideEvent(event)
