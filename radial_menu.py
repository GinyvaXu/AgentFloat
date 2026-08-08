# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — 悬停 / 长按环绕菜单（v1.0.6 统一高级感重绘）

设计遵循 apple-design：
- 整环一次性绘制（单一毛玻璃底色 + 细边框），不再逐扇区叠加半透明色块，
  从根上消除「相邻扇区半透明重叠」的显示错误；
- 悬停扇区用主题强调色整体高亮（唯一强调色），品牌色只保留为外缘 6px 小圆点；
- 入场动画统一缩放+淡入（可随时打断重定向），非逐扇区交错扫描；
- 关闭逻辑：光标在扇区上/浮窗上永不关闭；移开后 2 秒宽限期再关闭。
"""
import math
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QCursor
from PyQt5.QtWidgets import QWidget, QApplication

from af_theme import get_colors

CLOSE_GRACE_MS = 2000   # 移出扇区后的关闭宽限期（用户指定 1~3 秒）


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
        self._pad = 30             # 阴影边距
        self._progress = 0.0
        self._hover_idx = -1
        self._theme = "light"
        self._anchor_rect = None
        self._sector_cache = []    # (id, start_angle, sweep_angle)

        # 入场动画：统一缩放 + 淡入（可打断）
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim_value)
        self._anim.finished.connect(self._on_anim_finished)

        # 光标轮询（仅用于扇区悬停高亮；关闭由宽限计时器决定）
        self._poll = QTimer(self)
        self._poll.setInterval(100)
        self._poll.timeout.connect(self._poll_cursor)

        # 关闭宽限计时器
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(CLOSE_GRACE_MS)
        self._close_timer.timeout.connect(self._on_close_grace)

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
        screen = QApplication.screenAt(center_global)
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(x, geo.right() - side + 1))
            y = max(geo.top(), min(y, geo.bottom() - side + 1))
        self.move(x, y)
        self._progress = 0.0
        self._hover_idx = -1
        self._sector_cache = []
        self._close_timer.stop()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._poll.start()

    def close_menu(self):
        self._poll.stop()
        self._close_timer.stop()
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
        """返回光标所在扇区下标；不在环带上返回 -1。
        坐标统一用 global_pos - self.pos()（顶层窗口，避免高分屏换算误差）。"""
        c = self._center()
        p = global_pos - self.pos()
        dx, dy = p.x() - c.x(), p.y() - c.y()
        dist = math.hypot(dx, dy)
        if dist < self._inner - 8 or dist > self._outer + 8:
            return -1
        angle = (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0
        n = len(self._items)
        if n == 0:
            return -1
        sweep = 360.0 / n
        idx = int(angle // sweep)
        return idx if idx < n else -1

    def _in_menu_rect(self, global_pos):
        """光标是否落在菜单窗口矩形内（DPI 安全：与浮窗同一坐标空间）"""
        return self.rect().adjusted(-6, -6, 6, 6).contains(global_pos - self.pos())

    def _poll_cursor(self):
        if not self.isVisible():
            return
        pos = QCursor.pos()
        idx = self._sector_at(pos)
        in_anchor = self._anchor_rect is not None and self._anchor_rect.contains(pos)

        if idx >= 0:
            # 在扇区上：保持打开 + 高亮
            self._close_timer.stop()
            if idx != self._hover_idx:
                self._hover_idx = idx
                self.update()
        elif in_anchor:
            # 在触发浮窗上：保持打开，清除高亮
            self._close_timer.stop()
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.update()
        else:
            # 移出扇区与浮窗：进入宽限期
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.update()
            if not self._close_timer.isActive():
                self._close_timer.start()

    def _on_close_grace(self):
        # 宽限期结束仍不在扇区/浮窗上 → 关闭
        pos = QCursor.pos()
        idx = self._sector_at(pos)
        in_anchor = self._anchor_rect is not None and self._anchor_rect.contains(pos)
        if idx < 0 and not in_anchor:
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
        ring_bg = QColor(30, 30, 34, 240) if is_dark else QColor(250, 250, 252, 242)
        ring_border = QColor(255, 255, 255, 70) if is_dark else QColor(0, 0, 0, 42)
        text_c = QColor(*c["TEXT"])
        accent = QColor(*c["ACCENT"])
        center_pt = self._center()
        n = len(self._items)
        if n == 0:
            return

        scale = 0.72 + 0.28 * self._progress
        fade = self._progress

        painter.save()
        painter.translate(center_pt)
        painter.scale(scale, scale)

        # ── 毛玻璃阴影（Apple 材质深度：柔和多层）──
        for off, alpha in [(0, 26), (3, 14), (6, 7)]:
            sh = QColor(0, 0, 0, int(alpha * fade))
            painter.setPen(Qt.NoPen)
            painter.setBrush(sh)
            painter.drawEllipse(QRectF(-self._outer + off, -self._outer + off,
                                       self._outer * 2, self._outer * 2))

        # ── 整环一次性绘制（单一底色，杜绝扇区重叠错误）──
        ring_path = QPainterPath()
        ring_path.setFillRule(Qt.OddEvenFill)
        ring_path.addEllipse(QRectF(-self._outer, -self._outer, self._outer * 2, self._outer * 2))
        ring_path.addEllipse(QRectF(-self._inner, -self._inner, self._inner * 2, self._inner * 2))
        painter.setPen(QPen(ring_border, 1.2))
        painter.setBrush(ring_bg)
        painter.drawPath(ring_path)

        # ── 悬停扇区高亮（唯一强调色）──
        sweep = 360.0 / n
        if 0 <= self._hover_idx < n:
            a0 = -90.0 + self._hover_idx * sweep
            hp = QPainterPath()
            hp.moveTo(self._polar(a0, self._outer))
            hp.arcTo(QRectF(-self._outer, -self._outer, self._outer * 2, self._outer * 2), a0, sweep)
            hp.arcTo(QRectF(-self._inner, -self._inner, self._inner * 2, self._inner * 2),
                     a0 + sweep, -sweep)
            hp.closeSubpath()
            painter.setPen(QPen(QColor(255, 255, 255, 120) if is_dark else QColor(255, 255, 255, 200), 1.2))
            painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 205))
            painter.drawPath(hp)

        # ── 扇区分隔线（细、低对比）──
        painter.setPen(QPen(ring_border, 1))
        for i in range(1, n):
            a = -90.0 + i * sweep
            painter.drawLine(self._polar(a, self._inner), self._polar(a, self._outer))

        # ── 图标字符 + 标签 + 品牌圆点 ──
        self._sector_cache = []
        label_alpha = int(200 * fade)
        for i, item in enumerate(self._items):
            self._sector_cache.append((item.id, -90.0 + i * sweep, sweep))
            mid = -90.0 + (i + 0.5) * sweep
            rad = self._outer * 0.68
            pt = self._polar(mid, rad)
            hovered = (i == self._hover_idx)

            # 品牌色小圆点（外缘，仅做微辨识）
            dot_pt = self._polar(mid, self._outer - 12)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(item.color))
            painter.drawEllipse(QRectF(dot_pt.x() - 3.5, dot_pt.y() - 3.5, 7, 7))

            # 主字符
            painter.setPen(QColor(255, 255, 255) if hovered else
                           QColor(text_c.red(), text_c.green(), text_c.blue(), label_alpha))
            char_font = QFont("Segoe UI", 15, QFont.Bold)
            painter.setFont(char_font)
            painter.drawText(QRectF(pt.x() - 40, pt.y() - 36, 80, 26), Qt.AlignCenter, item.char)

            # 标签
            label_font = QFont("Microsoft YaHei", 8)
            painter.setFont(label_font)
            painter.setPen(QColor(255, 255, 255, 235) if hovered else
                           QColor(text_c.red(), text_c.green(), text_c.blue(), max(90, label_alpha - 30)))
            painter.drawText(QRectF(pt.x() - 55, pt.y() - 10, 110, 18), Qt.AlignCenter, item.label)

        painter.restore()

    def _polar(self, angle_deg, radius):
        rad = math.radians(angle_deg)
        return QPointF(math.cos(rad) * radius, math.sin(rad) * radius)

    def hideEvent(self, event):
        self._poll.stop()
        self._close_timer.stop()
        super().hideEvent(event)
