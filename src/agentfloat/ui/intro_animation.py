# -*- coding: utf-8 -*-
"""启动动画（v3.6.2）：屏幕中心的光晕 + 圆环 + 放大回弹的浮球 → 缩小飞向落点

时间线（毫秒，纯函数便于单测）：
    0–260    画面淡入（轻微暗角）
    0–900    浮球从 0.15 放大到 1.12（OutBack 回弹）
    900–1300 回落到 1.06（轻微沉降）
    0–1100   第 1 圈光环扩散；350–1600 第 2 圈
    500–1700 星点飘散
    800–1500 文字浮现（版本号 + 问候语，上滑淡入）
    ≥2200 且主程序就绪（或最迟 5200）→ 700ms 飞向浮球真实落点并缩到真实大小
    → finished 信号（交给真浮球）

不可跳过；窗口不抢焦点、不接收鼠标（点击可穿透）。
"""
import math
import random

from PyQt5.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap,
                         QRadialGradient)
from PyQt5.QtWidgets import QApplication, QWidget

from agentfloat.core.logging_setup import _log
from agentfloat.core.theme import get_colors
from agentfloat.ui import ball_render, chime

FADE_IN_END = 260
POP_END = 900
SETTLE_END = 1300
RING1 = (0, 1100)
RING2 = (350, 1600)
SPARKLES = (500, 1700)
TEXT_IN = (800, 1500)
MIN_HOLD_END = 2200
MAX_HOLD_END = 5200
FLY_MS = 700
RIPPLE_MS = 1150          # 落位后的涟漪持续时间

GREETINGS = (
    "欢迎回来",
    "已就绪，随时待命",
    "让 Agent 开工吧",
    "今天也高效一点",
    "你好，我是 AgentFloat",
    "一切都准备好了",
)

SPARKLE_COUNT = 18
RIPPLE_COUNT = 3


def pick_greeting(custom="", rng=None):
    text = str(custom or "").strip()
    if text:
        return text
    return (rng or random).choice(GREETINGS)


def intro_title(version, custom_greeting="", rng=None):
    """中心文字：版本号 + 随机问候语"""
    return "v%s · %s" % (version, pick_greeting(custom_greeting, rng))


def ease_out_back(t, s=1.35):
    t = max(0.0, min(1.0, t))
    return 1.0 + (s + 1.0) * (t - 1.0) ** 3 + s * (t - 1.0) ** 2


def ease_out_cubic(t):
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _span(t, start, end):
    """区间内的归一化进度（0–1）"""
    if end <= start:
        return 1.0 if t >= end else 0.0
    return max(0.0, min(1.0, (t - start) / float(end - start)))


def ball_scale_at(t):
    """浮球相对基准尺寸的缩放（基准 = 中心大球直径）"""
    if t <= POP_END:
        return 0.15 + (1.12 - 0.15) * ease_out_back(_span(t, 0, POP_END), 1.25)
    if t <= SETTLE_END:
        p = _span(t, POP_END, SETTLE_END)
        return 1.12 + (1.06 - 1.12) * ease_out_cubic(p)
    return 1.06


def timeline(t, t_fly=None):
    """返回该时刻的视觉状态（纯函数）"""
    state = {
        "phase": "intro",
        "t": t,
        "ball_scale": ball_scale_at(t),
        "overlay_a": int(58 * _span(t, 0, FADE_IN_END)),
        "text_a": int(255 * _span(t, TEXT_IN[0], TEXT_IN[1])),
        "text_dy": int(16 * (1.0 - _span(t, TEXT_IN[0], TEXT_IN[1]))),
        "ring1": (0.0, 0),
        "ring2": (0.0, 0),
        "arc_a": 0,                      # 旋转弧环
        "sparkles": 0.0,
        "glow": 1.0 + 0.08 * math.sin(t / 240.0),
        "bob": 0.0,                      # 轻微上下浮动
        "tilt": 0.0,                     # 球体轻微摇摆
        "ripple_p": None,
        "flash": 0.0,
    }
    for key, span in (("ring1", RING1), ("ring2", RING2)):
        p = _span(t, span[0], span[1])
        if 0.0 < p < 1.0:
            state[key] = (0.55 + 1.75 * ease_out_cubic(p), int(150 * (1.0 - p)))
    sp = _span(t, SPARKLES[0], SPARKLES[1])
    if 0.0 < sp < 1.0:
        state["sparkles"] = sp
    # 旋转弧环（比圆环更快、更有方向感）
    arc = _span(t, 260, 1900)
    if 0.0 < arc < 1.0:
        state["arc_a"] = int(150 * (1.0 - arc))
    if t < POP_END + 900:
        state["bob"] = 6.0 * math.sin(t / 300.0)
        state["tilt"] = 7.0 * math.sin(t / 380.0)
    if t_fly is not None and t >= t_fly:
        fly_end = t_fly + FLY_MS
        state["phase"] = "fly"
        state["fly_p"] = _span(t, t_fly, fly_end)
        fade = _span(t, t_fly + FLY_MS * 0.55, fly_end)
        state["text_a"] = int(state["text_a"] * (1.0 - _span(t, t_fly, t_fly + FLY_MS * 0.35)))
        state["overlay_a"] = int(state["overlay_a"] * (1.0 - fade))
        state["ring1"] = (0.0, 0)
        state["ring2"] = (0.0, 0)
        state["arc_a"] = 0
        state["sparkles"] = 0.0
        state["bob"] = 0.0
        state["tilt"] = 0.0
        if t >= fly_end:
            # 落位：涟漪 + 落点闪光
            state["phase"] = "ripple"
            state["ripple_p"] = _span(t, fly_end, fly_end + RIPPLE_MS)
            state["flash"] = 1.0 - _span(t, fly_end, fly_end + 280)
            state["overlay_a"] = int(state["overlay_a"] * (1.0 - _span(t, fly_end, fly_end + 400)))
            if state["ripple_p"] >= 1.0:
                state["phase"] = "done"
    return state


class IntroAnimation(QWidget):
    """启动动画覆盖层（无边框、置顶、不接受输入、不抢焦点）"""

    finished = pyqtSignal()      # 动画彻底结束（涟漪播完）
    landed = pyqtSignal()        # 浮球已飞抵落点（此时显示真浮球，涟漪继续播）

    def __init__(self, version, theme="dark", greeting="", sound=True, volume=chime.DEFAULT_VOLUME,
                 parent=None):
        super().__init__(parent)
        self._version = str(version)
        self._theme = theme
        self._greeting = str(greeting or "")
        self._sound = bool(sound)
        self._volume = float(volume)
        self._title = intro_title(self._version, self._greeting)
        self._ready_ms = None
        self._target_rect = None
        self._t0 = QElapsedTimer()
        self._sound_played = False
        self._landed_emitted = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint |
                            Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        accent = QColor(*get_colors(theme)["ACCENT"])
        self._accent = accent
        # 高分辨率预渲染一张大球位图，动画中只做缩放绘制（零重建）
        self._ball_px = None
        self._ball_px_size = 0
        self._big = 0.0
        self._target_size = 0.0
        self._center = QPointF()
        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)

    def _ensure_ball_pixmap(self, dpr=1.0):
        """预渲染中心大球位图（一次性；动画/离屏渲染共用）"""
        if self._ball_px is not None:
            return
        self._ball_px_size = max(1.0, self._big * 1.05)
        self._ball_px = ball_render.render_ball_pixmap(self._ball_px_size, self._accent,
                                                       hovered=True, dpr=dpr, margin_ratio=0.18)

    # ── 生命周期 ──────────────────────────────────
    def start(self, screen=None):
        """显示并开始动画（返回是否成功）"""
        screen = screen or QApplication.primaryScreen()
        if screen is None:
            return False
        self._geo = screen.availableGeometry()
        self.setGeometry(self._geo)
        self._center = QPointF(self._geo.center())
        # 中心大球（比首版更小巧，避免"太大"）
        self._big = max(96.0, min(self._geo.height() * 0.26, 240.0))
        try:
            dpr = float(screen.devicePixelRatio())
        except Exception:  # noqa: BLE001
            dpr = 1.0
        self._ensure_ball_pixmap(dpr)
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self._t0.start()
        self._tick.start()
        _log().info("[启动动画] 开始：%s（音效=%s 音量=%.2f）", self._title, self._sound, self._volume)
        return True

    def app_ready(self, target_rect):
        """主程序就绪：记录浮球真实落点，动画将在合适时机飞向它"""
        self._target_rect = QRectF(target_rect)
        self._target_size = float(target_rect.width())
        self._ready_ms = self._t0.elapsed() if self._t0.isValid() else 0
        _log().debug("[启动动画] 主程序就绪 @%sms 目标=%s", self._ready_ms, target_rect)

    def _fly_start_ms(self):
        if self._ready_ms is None:
            return MAX_HOLD_END
        return max(MIN_HOLD_END, min(MAX_HOLD_END, self._ready_ms))

    def _on_tick(self):
        t = self._t0.elapsed()
        if self._sound and not self._sound_played and t >= 90:
            self._sound_played = True
            chime.play(self._volume)
        state = timeline(t, self._fly_start_ms())
        self.update()
        if state["phase"] == "ripple" and not self._landed_emitted:
            self._landed_emitted = True
            _log().info("[启动动画] 浮球落位 @%.0fms（进入涟漪阶段）", t)
            self.landed.emit()
        if state["phase"] == "done":
            self._tick.stop()
            self.hide()
            _log().info("[启动动画] 完成（%.0fms）", t)
            self.finished.emit()

    # ── 绘制 ─────────────────────────────────────
    def render_frame(self, elapsed_ms, size=None):
        """离屏渲染某一时刻的画面（测试/预览用）"""
        size = size or self.size()
        if self._big <= 0:
            self._big = max(120.0, min(size.height() * 0.6, 320.0))
        if self._center.isNull():
            self._center = QPointF(size.width() / 2.0, size.height() / 2.0)
        self._ensure_ball_pixmap(1.0)
        pm = QPixmap(size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        state = timeline(elapsed_ms, self._fly_start_ms())
        self._paint_state(p, size.width(), size.height(), state)
        p.end()
        return pm

    def _ball_diameter(self, state):
        """当前球体直径：中心大球按缩放 → 飞行时插值到真实尺寸"""
        if state["phase"] != "fly":
            return self._big * state["ball_scale"]
        p = ease_out_cubic(state["fly_p"])
        start = self._big * timeline(self._fly_start_ms(), self._fly_start_ms())["ball_scale"]
        target = self._target_size or start
        return start + (target - start) * p

    def _ball_center(self, state):
        if self._target_rect is None:
            return self._center
        if state["phase"] == "fly":
            p = ease_out_cubic(state["fly_p"])
            tc = self._target_rect.center()
            return QPointF(self._center.x() + (tc.x() - self._center.x()) * p,
                           self._center.y() + (tc.y() - self._center.y()) * p)
        if state["phase"] == "ripple":
            return self._target_rect.center()          # 涟漪以落点为圆心
        return self._center

    def paintEvent(self, event):
        state = timeline(self._t0.elapsed() if self._t0.isValid() else 0, self._fly_start_ms())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self._paint_state(p, self.width(), self.height(), state)
        p.end()

    def _paint_state(self, p, width, height, state):
        """把某个时刻的视觉状态画到 painter（离屏/窗口共用）"""
        accent = self._accent
        center = self._ball_center(state)
        diameter = self._ball_diameter(state)
        radius = max(6.0, diameter / 2.0)

        # 轻微暗角：让光晕更立体
        if state["overlay_a"] > 0:
            grad = QRadialGradient(center, max(width, height) * 0.75)
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, state["overlay_a"]))
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawRect(0, 0, width, height)

        # 外圈光晕（呼吸；涟漪阶段交给真浮球，不再绘制大球光晕）
        if state["phase"] != "ripple":
            glow_r = radius * 2.4 * state["glow"]
            glow = QRadialGradient(center, glow_r)
            glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 96))
            glow.setColorAt(0.55, QColor(accent.red(), accent.green(), accent.blue(), 34))
            glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            p.setBrush(glow)
            p.setPen(Qt.NoPen)
            p.drawEllipse(center, glow_r, glow_r)

        # 扩散圆环
        for key in ("ring1", "ring2"):
            scale, alpha = state.get(key, (0.0, 0))
            if scale > 0 and alpha > 0:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha),
                              max(1.4, radius * 0.05)))
                r = radius * scale
                p.drawEllipse(center, r, r)

        # 旋转弧环（比圆环更快、更有方向感）
        if state.get("arc_a", 0) > 0:
            spin = (state.get("t", 0) / 900.0) * 360.0
            rr = radius * 1.38
            p.setBrush(Qt.NoBrush)
            for k, spread in ((0, 68), (170, 46)):
                p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), state["arc_a"]),
                              max(1.6, radius * 0.06)))
                p.drawArc(QRectF(center.x() - rr, center.y() - rr, rr * 2.0, rr * 2.0),
                          int((spin + k) * 16), int(spread * 16))

        # 星点
        if state["sparkles"] > 0:
            sp = state["sparkles"]
            for i in range(SPARKLE_COUNT):
                ang = (i / SPARKLE_COUNT) * math.pi * 2 + 0.35
                dist = radius * (1.15 + 1.5 * sp) * (1.0 + 0.12 * math.sin(i * 2.7))
                x = center.x() + math.cos(ang) * dist
                y = center.y() + math.sin(ang) * dist
                alpha = int(200 * (1.0 - sp) * (0.55 + 0.45 * ((i * 37) % 10) / 9.0))
                size = 1.6 + 2.2 * ((i * 13) % 5) / 4.0
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), max(0, alpha)))
                p.drawEllipse(QPointF(x, y), size, size)

        # 落位涟漪 + 落点闪光（先画，让球体压在涟漪之上）
        ripple_p = state.get("ripple_p")
        if ripple_p is not None:
            base_r = max(10.0, (self._target_size or 52) * 0.55)
            for i in range(RIPPLE_COUNT):
                seg = ripple_p * 1.4 - i * 0.22
                if 0.0 < seg < 1.0:
                    alpha = int(165 * (1.0 - seg) * (1.0 - ripple_p * 0.2))
                    if alpha > 0:
                        rr = base_r + seg * base_r * 3.6
                        p.setBrush(Qt.NoBrush)
                        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha),
                                      max(1.6, base_r * 0.12)))
                        p.drawEllipse(center, rr, rr)
                        # 内圈白亮描边，增强水波纹质感
                        p.setPen(QPen(QColor(255, 255, 255, int(alpha * 0.45)),
                                      max(1.0, base_r * 0.05)))
                        p.drawEllipse(center, rr - max(1.6, base_r * 0.06), rr - max(1.6, base_r * 0.06))
        if state.get("flash", 0) > 0:
            fr = max(24.0, (self._target_size or 52) * 1.6)
            flash_grad = QRadialGradient(center, fr * 1.5)
            fa = int(120 * state["flash"])
            flash_grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), fa))
            flash_grad.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            p.setPen(Qt.NoPen)
            p.setBrush(flash_grad)
            p.drawEllipse(center, fr * 1.5, fr * 1.5)

        # 浮球（预渲染位图缩放；涟漪阶段交给真浮球，不再重复绘制）
        if state["phase"] != "ripple" and self._ball_px is not None and diameter > 2:
            pm = self._ball_px
            logical = pm.width() / pm.devicePixelRatio()          # 含留白
            draw = logical * (diameter / max(1.0, self._ball_px_size))
            p.save()
            p.translate(center.x(), center.y() + state.get("bob", 0.0))
            if state.get("tilt"):
                p.rotate(state["tilt"])
            p.drawPixmap(QRectF(-draw / 2.0, -draw / 2.0, draw, draw), pm,
                         QRectF(0, 0, pm.width(), pm.height()))
            p.restore()

        # 文字：版本号 + 问候语（半透明胶囊底，任何壁纸上都清晰）
        if state["text_a"] > 0:
            text = self._title
            dark = self._theme != "light"
            a = state["text_a"]
            fg = QColor(245, 245, 247, a) if dark else QColor(28, 28, 30, a)
            font = QFont("Microsoft YaHei", max(12, int(self._big * 0.085)), QFont.DemiBold)
            font.setLetterSpacing(QFont.PercentageSpacing, 106)
            p.setFont(font)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(text)
            th = fm.height()
            pad_x, pad_y = 20, 10
            pw, ph = tw + pad_x * 2.0, th + pad_y * 2.0
            ty = center.y() + radius * 1.35 + 34 + state["text_dy"]      # 胶囊中心
            pill = QRectF(center.x() - pw / 2.0, ty - ph / 2.0, pw, ph)
            pill_r = ph / 2.0
            k = a / 255.0
            bg = QColor(10, 10, 14, int(160 * k)) if dark else QColor(255, 255, 255, int(185 * k))
            border = QColor(255, 255, 255, int(46 * k)) if dark else QColor(0, 0, 0, int(30 * k))
            p.setPen(QPen(border, 1))
            p.setBrush(bg)
            p.drawRoundedRect(pill, pill_r, pill_r)
            p.setPen(fg)
            p.drawText(pill, Qt.AlignCenter, text)
            # 品牌渐变下划线（贴胶囊底部内侧）
            grad = QLinearGradient(pill.left() + pad_x, 0, pill.right() - pad_x, 0)
            grad.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            grad.setColorAt(0.5, QColor(accent.red(), accent.green(), accent.blue(), min(255, a)))
            grad.setColorAt(1.0, QColor(175, 82, 222, 0))
            p.setPen(QPen(grad, 2.0))
            p.drawLine(QPointF(pill.left() + pad_x, pill.bottom() - 0.8),
                       QPointF(pill.right() - pad_x, pill.bottom() - 0.8))
