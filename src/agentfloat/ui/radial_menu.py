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
                          QEasingCurve, pyqtSignal)
from PyQt5.QtGui import (QPainter, QColor, QPen, QFont, QPainterPath, QCursor,
                         QPixmap, QBrush, QRadialGradient, QLinearGradient,
                         QConicalGradient)
from PyQt5.QtWidgets import QWidget, QApplication

from agentfloat.core.theme import get_colors
from agentfloat.ui.motion import Tokens as MotionTokens, motion, spring

CLOSE_GRACE_MS = 2000   # 移出扇区后的关闭宽限期（用户指定 1~3 秒）
RADIAL_PAD = 30        # 菜单外缘阴影边距（供主程序计算环心对齐）


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
    center_clicked = pyqtSignal()  # 点击中心孔（浮窗所在位置）时发出，供快捷启动

    def __init__(self, parent=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self._items = []
        self._outer = 120          # 外环半径
        self._inner = 46           # 中心孔半径
        self._pad = RADIAL_PAD      # 阴影边距
        self._progress = 0.0
        self._hover_idx = -1
        self._theme = "light"
        self._anchor_rect = None
        self._sector_cache = []    # (id, start_angle, sweep_angle)

        # PATCH 3.2.0：按住选环 + 扇区内容预渲染（更强渐变发光视觉）
        self._hold_select = True
        self._hold_active = False
        self._pixmaps = {}         # (i, hovered, dpr) -> QPixmap
        self._cache_dpr = 0.0

        # 展开/收拢：弹簧驱动（可打断、速度继承；展开轻过冲，收拢干脆）
        self._progress_state = spring(0.0, MotionTokens.RING_OPEN)
        self._motion_cancel = None
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
        self._poll.setInterval(60)      # 60ms：磁吸高亮更跟手
        self._poll.timeout.connect(self._poll_cursor)

        # 关闭宽限计时器
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(CLOSE_GRACE_MS)
        self._close_timer.timeout.connect(self._on_close_grace)

    # ── 公开接口 ─────────────────────────────────
    def set_theme(self, theme):
        self._theme = theme
        self._pixmaps.clear()
        if self.isVisible():
            self.update()

    def set_items(self, items, radius=None):
        self._items = list(items)
        self._pixmaps.clear()
        if radius:
            self._outer = int(radius)
            self._inner = max(28, int(radius * 0.36))

    # ── 按住选环（PATCH 3.2.0）────────────────────
    def set_hold_mode(self, enabled):
        """是否启用「按住选环」：长按弹出后不松手，滑到扇区松手即执行"""
        self._hold_select = bool(enabled)

    def begin_hold(self):
        """长按弹出菜单、按键仍按住 → 进入选环模式"""
        self._hold_active = bool(self._hold_select)
        return self._hold_active

    def end_hold(self, global_pos):
        """按住选环松手：命中扇区则执行，否则取消关闭。返回是否处理了本次松手"""
        if not self._hold_active:
            return False
        self._hold_active = False
        idx = self._click_index(global_pos)
        if 0 <= idx < len(self._items):
            item = self._items[idx]
            self.close_menu()
            self.action_triggered.emit(item.id)
        else:
            self.close_menu()
        return True

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
        self._hover_idx = -1
        self._sector_cache = []
        self._close_timer.stop()
        self._closing = False
        self._btn_down = False
        self._press_pos = None
        self._press_idx = -1
        self._press_progress = 0.0
        self._press_anim.stop()
        self.show()
        self.raise_()
        self._progress_state.set_params(*MotionTokens.RING_OPEN)
        if self._motion_cancel is not None:
            self._motion_cancel()
        self._motion_cancel = motion().animate_to(
            self._progress_state, 1.0, self._on_spring_progress,
            on_done=self._on_open_done)
        self._poll.start()

    def close_menu(self):
        self._poll.stop()
        self._close_timer.stop()
        if not self.isVisible():
            return
        if self._closing:
            return
        self._closing = True
        if self._motion_cancel is not None:
            self._motion_cancel()
            self._motion_cancel = None
        self._progress_state.set_params(*MotionTokens.RING_CLOSE)
        self._motion_cancel = motion().animate_to(
            self._progress_state, 0.0, self._on_spring_progress,
            on_done=self._really_hide)

    # ── 动画（弹簧驱动）─────────────────────────
    def _on_spring_progress(self, v):
        self._progress = float(v)
        self.update()

    def _on_open_done(self):
        self._progress = 1.0
        self.update()

    def _really_hide(self):
        self._closing = False
        self._motion_cancel = None
        self._progress_state.jump(0.0)
        self._progress = 0.0
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
        坐标用 mapFromGlobal 转换（高分屏 DPI 安全），命中半径与绘制缩放保持同步。"""
        c = self._center()
        # 坐标用 mapFromGlobal（高分辨屏 DPI 安全）；
        # 命中半径随入场/关闭动画缩放同步，避免「灰块悬在按键之间 / 悬停错位」
        p = self.mapFromGlobal(global_pos)
        dx, dy = p.x() - c.x(), p.y() - c.y()
        # 与绘制一致的当前缩放（弹簧展开/收拢，含轻过冲）
        scale = 0.30 + 0.70 * self._progress
        if scale > 0.01:
            dx, dy = dx / scale, dy / scale
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

    def _apply_magnet(self, global_pos, raw):
        """磁吸滞回：光标贴近扇区边界时保持上一个高亮扇区（防抖/防误击）"""
        prev = self._hover_idx
        n = len(self._items)
        if raw < 0 or prev < 0 or raw == prev or n == 0 or not (0 <= prev < n):
            return raw
        c = self._center()
        p = self.mapFromGlobal(global_pos)
        dx, dy = p.x() - c.x(), p.y() - c.y()
        scale = 0.30 + 0.70 * self._progress
        if scale > 0.01:
            dx, dy = dx / scale, dy / scale
        angle = (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0
        sweep = 360.0 / n
        margin = min(6.0, sweep * 0.18)
        frac = angle % sweep
        if frac < margin and prev == (raw - 1) % n:
            return prev
        if frac > sweep - margin and prev == (raw + 1) % n:
            return prev
        return raw

    def _click_index(self, global_pos):
        """点击判定：优先沿用当前高亮扇区（磁吸），环带边缘 ±14px 宽容"""
        idx = self._sector_at(global_pos)
        if idx < 0 and self._hover_idx >= 0:
            c = self._center()
            p = self.mapFromGlobal(global_pos)
            dist = math.hypot(p.x() - c.x(), p.y() - c.y())
            scale = max(0.01, 0.30 + 0.70 * self._progress)
            if (self._inner - 14) <= dist / scale <= (self._outer + 14):
                return self._hover_idx
        return idx

    def _in_menu_rect(self, global_pos):
        """光标是否落在菜单窗口矩形内（DPI 安全：与浮窗同一坐标空间）"""
        return self.rect().adjusted(-6, -6, 6, 6).contains(self.mapFromGlobal(global_pos))

    def _poll_cursor(self):
        if not self.isVisible():
            return
        pos = QCursor.pos()
        idx = self._apply_magnet(pos, self._sector_at(pos))
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
        idx = self._click_index(event.globalPos())
        if idx < 0:
            # 中心孔区域：视为点击浮窗本身（快捷启动），由主程序处理
            c = self._center()
            p = self.mapFromGlobal(event.globalPos())
            if math.hypot(p.x() - c.x(), p.y() - c.y()) <= self._inner:
                self.center_clicked.emit()
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
        idx = self._click_index(event.globalPos())
        if idx < 0:
            idx = self._press_idx
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
        brand = QColor(*c["ACCENT"])
        center_pt = self._center()
        n = len(self._items)
        if n == 0:
            return

        # PATCH 3.2.0：DPI 变化时重建扇区预渲染缓存（跨屏/缩放安全）
        dpr = self.devicePixelRatioF() or 1.0
        if abs(dpr - self._cache_dpr) > 0.01:
            self._pixmaps.clear()
            self._cache_dpr = dpr

        # 弹簧展开/收拢：整体缩放 + 淡入淡出（progress 含轻微过冲）
        scale = 0.30 + 0.70 * self._progress
        fade = max(0.0, min(1.0, self._progress))

        painter.save()
        painter.translate(center_pt)
        painter.scale(scale, scale)
        painter.setOpacity(fade)

        # ── 外发光（PATCH 3.2.0：更强渐变发光；悬停扇区时更亮）──
        glow_c = QColor(brand)
        glow_c.setAlpha(72 if self._hover_idx >= 0 else 40)
        glow_r = self._outer + self._pad * 0.85
        glow = QRadialGradient(QPointF(0, 0), glow_r)
        glow.setColorAt(0.60, QColor(glow_c.red(), glow_c.green(), glow_c.blue(), 0))
        glow.setColorAt(0.84, glow_c)
        glow.setColorAt(1.0, QColor(glow_c.red(), glow_c.green(), glow_c.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(0, 0), glow_r, glow_r)

        # ── 毛玻璃底：径向渐变（更强质感）──
        bg = QRadialGradient(QPointF(0, 0), float(self._outer))
        if is_dark:
            bg.setColorAt(0.0, QColor(40, 40, 48, 246))
            bg.setColorAt(0.72, QColor(26, 26, 32, 246))
            bg.setColorAt(1.0, QColor(16, 16, 20, 250))
        else:
            bg.setColorAt(0.0, QColor(252, 252, 255, 246))
            bg.setColorAt(0.72, QColor(244, 244, 249, 246))
            bg.setColorAt(1.0, QColor(230, 230, 240, 250))
        ring_border = QColor(255, 255, 255, 70) if is_dark else QColor(0, 0, 0, 42)
        ring_path = QPainterPath()
        ring_path.setFillRule(Qt.OddEvenFill)
        ring_path.addEllipse(QRectF(-self._outer, -self._outer, self._outer * 2, self._outer * 2))
        ring_path.addEllipse(QRectF(-self._inner, -self._inner, self._inner * 2, self._inner * 2))
        painter.setPen(QPen(ring_border, 1.2))
        painter.setBrush(bg)
        painter.drawPath(ring_path)

        # ── 品牌渐变描边（内/外缘各一圈，更强视觉）──
        gpen = QPen()
        gpen.setWidthF(1.8)
        gpen.setBrush(QBrush(self._brand_conical(brand)))
        painter.setPen(gpen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(0, 0), float(self._outer), float(self._outer))
        painter.drawEllipse(QPointF(0, 0), float(self._inner), float(self._inner))

        # ── 扇区分隔线（细、低对比）──
        sweep = 360.0 / n
        painter.setPen(QPen(ring_border, 1))
        for i in range(1, n):
            a = -90.0 + i * sweep
            painter.drawLine(self._polar(a, self._inner), self._polar(a, self._outer))

        # ── 悬停/按压扇区：品牌渐变高亮 + 描边发光（PATCH 3.2.0）──
        if 0 <= self._hover_idx < n:
            hp = self._sector_path(self._hover_idx)
            item_c = QColor(self._items[self._hover_idx].color)
            press = self._press_progress if self._press_idx == self._hover_idx else 0.0
            a0 = -90.0 + self._hover_idx * sweep
            grad = QLinearGradient(self._polar(a0, self._outer), self._polar(a0 + sweep, self._inner))
            base_a = 92 if is_dark else 74
            grad.setColorAt(0.0, QColor(item_c.red(), item_c.green(), item_c.blue(),
                                        int(base_a + 60 * press)))
            grad.setColorAt(1.0, QColor(brand.red(), brand.green(), brand.blue(),
                                        int(max(0, base_a - 24) + 50 * press)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(grad)
            painter.drawPath(hp)
            painter.setPen(QPen(QColor(item_c.red(), item_c.green(), item_c.blue(), 160), 1.4))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(hp)

        # ── 图标字符 + 标签（预渲染 pixmap + 错峰浮现 + 悬停放大）──
        self._sector_cache = []
        for i, item in enumerate(self._items):
            self._sector_cache.append((item.id, -90.0 + i * sweep, sweep))
            sector_p = max(0.0, min(1.0, (self._progress - i * 0.04) / 0.72))
            mid = -90.0 + (i + 0.5) * sweep
            rad = self._outer * (0.60 if n >= 8 else 0.68)
            pt = self._polar(mid, rad)
            hovered = (i == self._hover_idx)
            if sector_p <= 0.02:
                continue

            # 品牌色小圆点（外缘；悬停时轻微变淡）
            dot_pt = self._polar(mid, self._outer - 10)
            painter.setPen(Qt.NoPen)
            dot_c = QColor(item.color)
            dot_c.setAlpha(int((150 if hovered else 255) * sector_p))
            painter.setBrush(dot_c)
            painter.drawEllipse(QRectF(dot_pt.x() - 3.0, dot_pt.y() - 3.0, 6, 6))

            # 按压缩小 / 悬停放大（1.06）
            content_scale = (1.0 - 0.07 * self._press_progress) * (0.70 + 0.30 * sector_p)
            if hovered:
                content_scale *= 1.06
            pm = self._sector_pixmap(i, hovered, dpr)
            painter.save()
            painter.translate(pt)
            painter.scale(content_scale, content_scale)
            painter.setOpacity(fade * sector_p)
            painter.drawPixmap(int(-pm.width() / 2.0 / dpr), int(-pm.height() / 2.0 / dpr), pm)
            painter.restore()

        painter.restore()

    def _brand_conical(self, brand):
        """品牌色环形渐变（外/内描边共用，PATCH 3.2.0 更强视觉）"""
        g = QConicalGradient(QPointF(0, 0), -90.0)
        purple = QColor(0xAF, 0x52, 0xDE)
        g.setColorAt(0.0, brand)
        g.setColorAt(0.35, purple)
        g.setColorAt(0.7, brand)
        g.setColorAt(1.0, purple)
        return g

    def _sector_pixmap(self, idx, hovered, dpr):
        """扇区内容（图标 + 标签 + 悬停光晕）预渲染缓存（PATCH 3.2.0）"""
        key = (idx, bool(hovered), round(float(dpr), 2))
        pm = self._pixmaps.get(key)
        if pm is not None:
            return pm
        item = self._items[idx]
        n = len(self._items)
        if n >= 8:
            w, h, char_h = 108, 48, 24
            char_font = QFont("Segoe UI", 12, QFont.Bold)
            label_font = QFont("Microsoft YaHei", 7)
        else:
            w, h, char_h = 120, 56, 30
            char_font = QFont("Segoe UI", 15, QFont.Bold)
            label_font = QFont("Microsoft YaHei", 8)
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            c = get_colors(self._theme)
            text_c = QColor(*c["TEXT"])
            if hovered:
                gc = QColor(item.color)
                gc.setAlpha(96)
                glow = QRadialGradient(QPointF(w / 2.0, h / 2.0), w / 2.0)
                glow.setColorAt(0.0, gc)
                glow.setColorAt(1.0, QColor(gc.red(), gc.green(), gc.blue(), 0))
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(QRectF(0, 0, w, h))
                p.setPen(QColor(255, 255, 255, 255))
            else:
                p.setPen(QColor(text_c.red(), text_c.green(), text_c.blue(), 235))
            p.setFont(char_font)
            p.drawText(QRectF(0, 0, w, char_h), Qt.AlignCenter, item.char)
            p.setFont(label_font)
            if hovered:
                p.setPen(QColor(255, 255, 255, 238))
            else:
                p.setPen(QColor(text_c.red(), text_c.green(), text_c.blue(), 150))
            p.drawText(QRectF(0, char_h, w, h - char_h), Qt.AlignCenter, item.label)
        finally:
            p.end()
        self._pixmaps[key] = pm
        return pm

    def _sector_path(self, idx):
        """返回扇区 idx 的填充路径（数学角度约定，与命中测试/图标一致）。
        不使用 QPainterPath.arcTo：其角度约定（90°=正上方、正角度逆时针）
        与 _polar 的数学角度（-90°=正上方）相差 180°，
        会导致高亮路径画到错误扇区（“灰块乱飞”根因）。"""
        n = len(self._items)
        if n == 0 or not (0 <= idx < n):
            return QPainterPath()
        sweep = 360.0 / n
        a0 = -90.0 + idx * sweep
        a1 = a0 + sweep
        steps = 20
        path = QPainterPath()
        path.moveTo(self._polar(a0, self._outer))
        for k in range(1, steps + 1):
            path.lineTo(self._polar(a0 + sweep * k / steps, self._outer))
        path.lineTo(self._polar(a1, self._inner))
        for k in range(steps - 1, -1, -1):
            path.lineTo(self._polar(a0 + sweep * k / steps, self._inner))
        path.closeSubpath()
        return path

    def _polar(self, angle_deg, radius):
        rad = math.radians(angle_deg)
        return QPointF(math.cos(rad) * radius, math.sin(rad) * radius)

    def hideEvent(self, event):
        self._poll.stop()
        self._close_timer.stop()
        if self._motion_cancel is not None:
            self._motion_cancel()
            self._motion_cancel = None
        super().hideEvent(event)
