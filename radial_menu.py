# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — 悬停 / 长按环绕菜单（v1.0.6 统一高级感重绘）

设计遵循 apple-design：
- 整环一次性绘制（单一毛玻璃底色 + 细边框），不再逐扇区叠加半透明色块，
  从根上消除「相邻扇区半透明重叠」的显示错误；
- 悬停扇区用中性灰色高亮（无蓝无描边）；按下扇区时内容向中心轻微缩小 + 灰色加深，
  呈现「真的按下去」的触感；品牌色只保留为外缘 6px 小圆点（悬停时轻微变淡）；
- 入场动画统一缩放+淡入（OutBack 轻微过冲，可随时打断重定向）；
- 关闭动画：整体向中心收拢（缩小 + 淡出）；
- 关闭逻辑：光标在扇区上/浮窗上/菜单窗口矩形内永不关闭；整体移出后 2 秒宽限期再关闭；
  点击菜单外任意处立即关闭（Win32 全局左键检测）。
"""
import math
from PyQt5.QtCore import (Qt, QPointF, QRectF, QTimer, QVariantAnimation,
                          QEasingCurve, QAbstractAnimation, pyqtSignal)
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
    closed = pyqtSignal()          # 菜单真正隐藏时发出（用于恢复余额角标等）

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

        # 入场动画：统一缩放 + 淡入（OutBack 轻微过冲，可打断）
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(self._on_anim_value)
        self._anim.finished.connect(self._on_anim_finished)

        # 关闭淡出动画
        self._close_anim = QVariantAnimation(self)
        self._close_anim.setDuration(170)
        self._close_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._close_anim.valueChanged.connect(self._on_close_anim_value)
        self._close_anim.finished.connect(self._really_hide)
        self._close_progress = 1.0
        self._closing = False

        # 点击外部检测状态
        self._btn_down = False
        self._press_pos = None

        # 扇区按压反馈（按下去的触感）
        self._press_idx = -1
        self._press_progress = 0.0
        self._press_anim = QVariantAnimation(self)
        self._press_anim.setDuration(120)
        self._press_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._press_anim.valueChanged.connect(self._on_press_anim_value)
        self._press_anim.finished.connect(self._on_press_anim_finished)

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
        self._close_anim.stop()
        self._closing = False
        self._close_progress = 1.0
        self._btn_down = False
        self._press_pos = None
        self._press_idx = -1
        self._press_progress = 0.0
        self._press_anim.stop()
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
        if not self.isVisible():
            return
        if self._close_anim.state() == QAbstractAnimation.Running:
            return
        self._closing = True
        self._close_anim.stop()
        self._close_anim.setStartValue(1.0)
        self._close_anim.setEndValue(0.0)
        self._close_anim.start()

    # ── 动画 ────────────────────────────────────
    def _on_anim_value(self, v):
        self._progress = float(v)
        self.update()

    def _on_anim_finished(self):
        self._progress = 1.0
        self.update()

    def _on_close_anim_value(self, v):
        self._close_progress = float(v)
        self.update()

    def _really_hide(self):
        self._closing = False
        self.hide()
        self.closed.emit()

    def _on_press_anim_value(self, v):
        self._press_progress = float(v)
        self.update()

    def _on_press_anim_finished(self):
        if self._press_progress <= 0.01:
            self._press_idx = -1

    def _start_press(self, idx):
        self._press_idx = idx
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_progress)
        self._press_anim.setEndValue(1.0)
        self._press_anim.start()

    def _reset_press(self):
        if self._press_idx < 0:
            return
        self._press_anim.stop()
        self._press_anim.setStartValue(self._press_progress)
        self._press_anim.setEndValue(0.0)
        self._press_anim.start()

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
        in_menu = self._in_menu_rect(pos)

        # 点击菜单外任意处 → 立即关闭（全局左键检测）
        if self._detect_click_outside(pos):
            self.close_menu()
            return

        if idx >= 0:
            # 在扇区上：保持打开 + 高亮
            self._close_timer.stop()
            if idx != self._hover_idx:
                self._hover_idx = idx
                self.update()
            if self._press_idx >= 0 and idx != self._press_idx:
                self._reset_press()
        elif in_anchor or in_menu:
            # 在触发浮窗上 / 菜单窗口矩形内（含中心孔与间隙）：保持打开，清除高亮
            self._close_timer.stop()
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.update()
            if self._press_idx >= 0:
                self._reset_press()
        else:
            # 整体移出菜单与浮窗：进入宽限期
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.update()
            if self._press_idx >= 0:
                self._reset_press()
            if not self._close_timer.isActive():
                self._close_timer.start()

    def _outside_interactive(self, pos):
        # pos 是否位于「菜单可交互区 + 浮窗」之外（即点击空白处）
        if 0 <= self._sector_at(pos) < len(self._items):
            return False
        if self._anchor_rect is not None and self._anchor_rect.contains(pos):
            return False
        if self._in_menu_rect(pos):
            return False
        return True

    def _detect_click_outside(self, pos):
        # Win32 全局左键检测：按下或释放发生在菜单外 → 立即关闭。
        # 轮询间隙内完成的快速点击（按下+释放）也会在释放时按释放位置判定。
        try:
            import ctypes
            down = bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False
        prev = self._btn_down
        self._btn_down = down
        if down:
            if not prev:
                # 记录按下位置；若直接按在菜单外则立即关闭
                self._press_pos = pos
                return self._outside_interactive(pos)
            return False
        if prev:
            # 刚释放：按下位置在菜单外（或未捕获按下、释放点在菜单外）→ 关闭
            pp = self._press_pos
            self._press_pos = None
            if pp is None:
                return self._outside_interactive(pos)
            return self._outside_interactive(pp)
        return False

    def _on_close_grace(self):
        # 宽限期结束仍不在扇区/浮窗/菜单矩形内 → 关闭
        pos = QCursor.pos()
        idx = self._sector_at(pos)
        in_anchor = self._anchor_rect is not None and self._anchor_rect.contains(pos)
        in_menu = self._in_menu_rect(pos)
        if idx < 0 and not in_anchor and not in_menu:
            self.close_menu()

    # ── 鼠标 ────────────────────────────────────
    def mousePressEvent(self, event):
        if self._closing:
            event.accept()
            return
        idx = self._sector_at(event.globalPos())
        if idx < 0:
            self.close_menu()
            event.accept()
            return
        self._start_press(idx)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._closing:
            event.accept()
            return
        self._reset_press()
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

        eased = self._ease_out_back(self._progress)
        # 关闭动画：整体向中心收拢（缩小 + 淡出）
        close_scale = 0.30 + 0.70 * self._close_progress
        scale = (0.72 + 0.28 * eased) * close_scale
        fade = min(1.0, self._progress) * self._close_progress

        painter.save()
        painter.translate(center_pt)
        painter.scale(scale, scale)
        painter.setOpacity(fade)

        # ── 毛玻璃阴影（Apple 材质深度：柔和多层）──
        for off, alpha in [(0, 26), (3, 14), (6, 7)]:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, alpha))
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

        # ── 扇区分隔线（细、低对比）──
        sweep = 360.0 / n
        painter.setPen(QPen(ring_border, 1))
        for i in range(1, n):
            a = -90.0 + i * sweep
            painter.drawLine(self._polar(a, self._inner), self._polar(a, self._outer))

        # ── 悬停/按压扇区：中性灰高亮，无蓝无描边；按住时灰色加深 ──
        if 0 <= self._hover_idx < n:
            a0 = -90.0 + self._hover_idx * sweep
            hp = QPainterPath()
            hp.moveTo(self._polar(a0, self._outer))
            hp.arcTo(QRectF(-self._outer, -self._outer, self._outer * 2, self._outer * 2), a0, sweep)
            hp.arcTo(QRectF(-self._inner, -self._inner, self._inner * 2, self._inner * 2),
                     a0 + sweep, -sweep)
            hp.closeSubpath()
            press = self._press_progress if self._press_idx == self._hover_idx else 0.0
            if is_dark:
                fill = QColor(255, 255, 255, int(26 + 26 * press))
            else:
                fill = QColor(0, 0, 0, int(24 + 28 * press))
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawPath(hp)

        # ── 图标字符 + 标签 + 品牌圆点 ──
        self._sector_cache = []
        for i, item in enumerate(self._items):
            self._sector_cache.append((item.id, -90.0 + i * sweep, sweep))
            mid = -90.0 + (i + 0.5) * sweep
            rad = self._outer * 0.68
            pt = self._polar(mid, rad)
            hovered = (i == self._hover_idx)

            # 品牌色小圆点（外缘，仅做微辨识；悬停时轻微变淡）
            dot_pt = self._polar(mid, self._outer - 12)
            painter.setPen(Qt.NoPen)
            dot_c = QColor(item.color)
            if hovered:
                dot_c.setAlpha(150)
            painter.setBrush(dot_c)
            painter.drawEllipse(QRectF(dot_pt.x() - 3.5, dot_pt.y() - 3.5, 7, 7))

            # 按压扇区：内容向中心轻微缩小（按下去的触感）
            content_scale = 1.0 - 0.07 * self._press_progress
            painter.save()
            painter.translate(pt)
            painter.scale(content_scale, content_scale)
            painter.translate(-pt)

            # 主字符
            painter.setPen(QColor(255, 255, 255) if hovered else text_c)
            char_font = QFont("Segoe UI", 15, QFont.Bold)
            painter.setFont(char_font)
            painter.drawText(QRectF(pt.x() - 40, pt.y() - 36, 80, 26), Qt.AlignCenter, item.char)

            # 标签
            label_font = QFont("Microsoft YaHei", 8)
            painter.setFont(label_font)
            painter.setPen(QColor(255, 255, 255, 235) if hovered else
                           QColor(text_c.red(), text_c.green(), text_c.blue(), 150))
            painter.drawText(QRectF(pt.x() - 55, pt.y() - 10, 110, 18), Qt.AlignCenter, item.label)

            painter.restore()

        painter.restore()

    def _polar(self, angle_deg, radius):
        rad = math.radians(angle_deg)
        return QPointF(math.cos(rad) * radius, math.sin(rad) * radius)

    def hideEvent(self, event):
        self._poll.stop()
        self._close_timer.stop()
        self._close_anim.stop()
        super().hideEvent(event)

    @staticmethod
    def _ease_out_back(t, overshoot=0.9):
        # OutBack 缓动：末端约 5% 过冲后回落（Apple 式轻回弹）
        t -= 1.0
        c = overshoot + 1.0
        return 1.0 + c * (t ** 3) + overshoot * (t ** 2)
