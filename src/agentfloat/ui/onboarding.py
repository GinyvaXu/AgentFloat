# -*- coding: utf-8 -*-
"""新用户嵌入式引导（v3.9.0）——浮窗聚光灯 + 分步气泡

设计：
- 覆盖浮球所在屏幕的半透明遮罩，用「挖洞」把浮球本身露出来并加一圈光环；
- 气泡贴着浮球放置（自动选上下左右），带步骤序号、标题、说明与按钮；
- 步骤纯数据（STEPS），几何计算与步骤模型可单测；
- 首次运行自动播放（config.onboarding_done=false），随时可从右键菜单/设置重播。

交互：下一步 / 上一步 / 跳过；Esc=跳过，Enter/→=下一步，←=上一步；点击遮罩空白=下一步。
"""
from PyQt5.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, Qt,
                          QTimer, pyqtSignal)
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from agentfloat.ui.tokens import FONT, RADIUS, SPACE

# 步骤定义：anchor="ball" 表示高亮浮球本体（几何由调用方给出）
STEPS = [
    {
        "title": "认识浮球",
        "desc": "这就是 AgentFloat —— 常驻桌面的一颗小球。\n"
                "所有操作都从它开始，不占任务栏、不抢焦点。",
        "anchor": "ball",
    },
    {
        "title": "单击 = 启动 Agent",
        "desc": "点一下浮球，立即启动你设置的默认 Agent。\n"
                "（在「设置 → 通用 → 主 Agent 启动」里更换）",
        "anchor": "ball",
    },
    {
        "title": "长按 = 环绕菜单",
        "desc": "按住浮球向外滑动，滑到哪个扇区松手就执行哪个动作：\n"
                "Skills 辅助窗 / API 用量 / 快报 / 剪贴板 / 移动浮窗 / 退出。",
        "anchor": "ball",
    },
    {
        "title": "右键 = 更多入口",
        "desc": "右键浮球可以看到：启动具体 Agent、设置、\n"
                "复制 Web 控制台令牌、开机自启、使用教程、退出。",
        "anchor": "ball",
    },
    {
        "title": "拖到边缘会吸附隐藏",
        "desc": "把浮球拖到屏幕边缘会自动吸附；开启「贴边隐藏」后\n"
                "它会让出屏幕空间，鼠标靠近边缘时重新滑出。",
        "anchor": "ball",
    },
    {
        "title": "随时可以重看这份教程",
        "desc": "右键浮球 →「使用教程」可再次播放本引导；\n"
                "更完整的图文教程在设置页「指南」中。开始使用吧！",
        "anchor": "ball",
    },
]

BUBBLE_W = 396
BUBBLE_MIN_H = 150
GAP = 26          # 气泡与浮球的间距
MARGIN = 16       # 气泡与屏幕边界的间距
HOLE_PAD = 12     # 光环相对浮球的额外留白


def bubble_geometry(ball_rect, screen_rect, size=(BUBBLE_W, BUBBLE_MIN_H)):
    """计算气泡位置：优先放浮球右侧，其次左侧，再上/下；并收进屏幕内。

    屏幕比气泡还小时先收缩气泡尺寸（保证任何分辨率下都不越界）。
    返回 (QRect 气泡, str 方向)。方向用于绘制引导箭头。
    """
    b = QRect(ball_rect)
    s = QRect(screen_rect)
    # 先按屏幕可用空间收缩尺寸（极小屏/高 DPI 缩放场景）
    bw = max(180, min(int(size[0]), s.width() - 2 * MARGIN))
    bh = max(110, min(int(size[1]), s.height() - 2 * MARGIN))
    right = QRect(b.right() + GAP, b.center().y() - bh // 2, bw, bh)
    left = QRect(b.left() - GAP - bw, b.center().y() - bh // 2, bw, bh)
    below = QRect(b.center().x() - bw // 2, b.bottom() + GAP, bw, bh)
    above = QRect(b.center().x() - bw // 2, b.top() - GAP - bh, bw, bh)

    def fits(r):
        return r.left() >= s.left() + MARGIN and r.right() <= s.right() - MARGIN \
            and r.top() >= s.top() + MARGIN and r.bottom() <= s.bottom() - MARGIN

    for rect, side in ((right, "right"), (left, "left"), (below, "bottom"), (above, "top")):
        if fits(rect):
            return rect, side
    # 都放不下（浮球贴边/小屏）→ 按首选方向夹进屏幕（收缩后不会越界）
    x = min(max(right.left(), s.left() + MARGIN), max(s.left() + MARGIN,
                                                      s.right() - MARGIN - bw))
    y = min(max(right.top(), s.top() + MARGIN), max(s.top() + MARGIN,
                                                     s.bottom() - MARGIN - bh))
    return QRect(x, y, bw, bh), "right"


def spotlight_rect(ball_rect):
    """聚光灯高亮区域（浮球外扩一点，形成光环）"""
    return QRect(ball_rect).adjusted(-HOLE_PAD, -HOLE_PAD, HOLE_PAD, HOLE_PAD)


class OnboardingOverlay(QWidget):
    """浮窗聚光灯引导覆盖层（v3.9.2：更多动画 + 浮球状态联动）"""

    finished = pyqtSignal(bool)      # True = 看完，False = 跳过
    step_changed = pyqtSignal(int)   # 当前步骤下标（用于让浮球切到对应状态）

    def __init__(self, ball_rect, screen_rect, theme="light", parent=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._theme = theme
        self._index = 0
        self._ball = QRect(ball_rect)
        self._pulse = 0.0
        self._pulse_dir = 1
        self._fade_target = None
        geo = QRect(screen_rect)
        self.setGeometry(geo)
        self._build_bubble()
        # 聚光灯脉冲（光环呼吸）+ 气泡淡入
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(33)          # ~30fps，开销极小
        self._pulse_timer.timeout.connect(self._on_pulse)
        self._pulse_timer.start()
        try:
            from PyQt5.QtWidgets import QGraphicsOpacityEffect
            self._bubble_fx = QGraphicsOpacityEffect(self._bubble)
            self._bubble.setGraphicsEffect(self._bubble_fx)
        except Exception:  # noqa: BLE001
            self._bubble_fx = None
        self._bubble_anim = QPropertyAnimation(self._bubble, b"pos", self)
        self._bubble_anim.setDuration(260)
        self._bubble_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._apply_step()

    def _on_pulse(self):
        """光环呼吸 + 气泡淡入推进"""
        self._pulse += 0.035 * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse, self._pulse_dir = 1.0, -1
        elif self._pulse <= 0.0:
            self._pulse, self._pulse_dir = 0.0, 1
        if self._bubble_fx is not None and self._fade_target is not None:
            cur = self._bubble_fx.opacity()
            step = (self._fade_target - cur) * 0.28
            nxt = cur + step
            if abs(self._fade_target - nxt) < 0.01:
                nxt = self._fade_target
            self._bubble_fx.setOpacity(max(0.0, min(1.0, nxt)))
        self.update()

    # ── 气泡 ───────────────────────────────────────
    def _build_bubble(self):
        self._bubble = QFrame(self)
        self._bubble.setObjectName("onboardBubble")
        lay = QVBoxLayout(self._bubble)
        lay.setContentsMargins(SPACE.lg, SPACE.lg, SPACE.lg, SPACE.md)
        lay.setSpacing(SPACE.sm)
        self._step_lbl = QLabel("")
        self._step_lbl.setObjectName("onboardStep")
        self._title = QLabel("")
        self._title.setObjectName("onboardTitle")
        self._desc = QLabel("")
        self._desc.setObjectName("onboardDesc")
        self._desc.setWordWrap(True)
        lay.addWidget(self._step_lbl)
        lay.addWidget(self._title)
        lay.addWidget(self._desc)
        row = QHBoxLayout()
        row.addStretch(1)
        self._skip = QPushButton("跳过")
        self._skip.setObjectName("onboardSkip")
        self._prev = QPushButton("上一步")
        self._prev.setObjectName("onboardPrev")
        self._next = QPushButton("下一步")
        self._next.setObjectName("onboardNext")
        row.addWidget(self._skip)
        row.addWidget(self._prev)
        row.addWidget(self._next)
        lay.addLayout(row)
        self._skip.clicked.connect(lambda: self._finish(False))
        self._prev.clicked.connect(lambda: self._go(-1))
        self._next.clicked.connect(lambda: self._go(1))
        self._bubble.setStyleSheet(self._css())

    def _css(self):
        dark = self._theme != "light"
        bg = "rgba(32,32,36,0.98)" if dark else "rgba(252,252,255,0.99)"
        tx = "#F5F5F7" if dark else "#1D1D1F"
        tx2 = "#A1A1A6" if dark else "#6E6E73"
        bd = "rgba(255,255,255,0.14)" if dark else "rgba(60,60,67,0.14)"
        return (
            "QFrame#onboardBubble { background: %(bg)s; border: 1px solid %(bd)s;"
            " border-radius: %(r)dpx; }"
            "QLabel#onboardStep { color: #0A84FF; font-size: %(fc)dpx; font-weight: 700;"
            " letter-spacing: 0.4px; }"
            "QLabel#onboardTitle { color: %(tx)s; font-size: %(ft)dpx; font-weight: 700; }"
            "QLabel#onboardDesc { color: %(tx2)s; font-size: %(fb)dpx; line-height: 1.7; }"
            "QPushButton { background: transparent; color: %(tx2)s; border: 1px solid %(bd)s;"
            " border-radius: %(rsm)dpx; padding: 6px 14px; font-size: %(fb)dpx; }"
            "QPushButton#onboardNext { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            " stop:0 #0A84FF, stop:1 #7A5CFF); color: #FFF; border: none; font-weight: 600; }"
            % {"bg": bg, "bd": bd, "tx": tx, "tx2": tx2, "r": RADIUS.lg,
               "rsm": RADIUS.sm, "fc": FONT.caption, "ft": FONT.title, "fb": FONT.body}
        )

    # ── 步骤 ───────────────────────────────────────
    def _apply_step(self):
        step = STEPS[self._index]
        self._step_lbl.setText("第 %d / %d 步" % (self._index + 1, len(STEPS)))
        self._title.setText(step["title"])
        self._desc.setText(step["desc"])
        self._prev.setEnabled(self._index > 0)
        self._prev.setVisible(self._index > 0)
        self._next.setText("开始使用" if self._index == len(STEPS) - 1 else "下一步")
        rect, side = bubble_geometry(self._ball, self.geometry(),
                                     (BUBBLE_W, self._bubble.sizeHint().height()))
        self._side = side
        # 气泡：淡入 + 从下方滑入（每步都播，形成节奏感）
        try:
            self._bubble.resize(rect.size())
            start = QRect(rect)
            start.moveTop(rect.top() + 14)
            self._bubble.move(start.topLeft())
            self._bubble_anim.stop()
            self._bubble_anim.setStartValue(start.topLeft())
            self._bubble_anim.setEndValue(rect.topLeft())
            self._bubble_anim.start()
            if self._bubble_fx is not None:
                self._bubble_fx.setOpacity(0.0)
                self._fade_target = 1.0
        except Exception:  # noqa: BLE001
            self._bubble.setGeometry(rect)
        # 通知外层：让浮球切到对应功能的状态（v3.9.2）
        try:
            self.step_changed.emit(self._index)
        except Exception:  # noqa: BLE001
            pass
        self.update()

    def _go(self, delta):
        idx = self._index + delta
        if idx >= len(STEPS):
            self._finish(True)
            return
        self._index = max(0, min(len(STEPS) - 1, idx))
        self._apply_step()

    def _finish(self, completed):
        try:
            self._pulse_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        self.finished.emit(bool(completed))
        self.close()

    # ── 事件 ───────────────────────────────────────
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self._finish(False)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Right):
            self._go(1)
        elif key in (Qt.Key_Left, Qt.Key_Backspace):
            self._go(-1)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # 点空白处 = 下一步（气泡上的点击由子控件处理）
        if not self._bubble.geometry().contains(event.pos()):
            self._go(1)
        super().mousePressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            self.setFocusPolicy(Qt.StrongFocus)
            self.setFocus()
            self.activateWindow()
            self.raise_()
        except Exception:  # noqa: BLE001
            pass

    # ── 绘制 ───────────────────────────────────────
    def paintEvent(self, event):
        try:
            self._paint(event)
        except Exception:  # noqa: BLE001
            # 绘制异常不应冒泡成 CRITICAL（覆盖层可降级为纯遮罩）
            try:
                p = QPainter(self)
                p.fillRect(self.rect(), QColor(0, 0, 0, 150))
                p.end()
            except Exception:  # noqa: BLE001
                pass

    def _paint(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hole = spotlight_rect(self._ball).translated(-self.geometry().topLeft())
        holef = QRectF(float(hole.left()), float(hole.top()),
                       float(hole.width()), float(hole.height()))
        path = QPainterPath()
        path.addRect(QRectF(float(self.rect().left()), float(self.rect().top()),
                            float(self.width()), float(self.height())))
        inner = QPainterPath()
        inner.addRoundedRect(holef, holef.width() / 2.0, holef.height() / 2.0)
        p.fillPath(path.subtracted(inner), QColor(0, 0, 0, 150))
        # 聚光灯脉冲：外圈呼吸 + 内圈实环（v3.9.2 更有动感）
        breath = 4.0 + 5.0 * self._pulse
        glow = holef.adjusted(-breath, -breath, breath, breath)
        p.setPen(QPen(QColor(10, 132, 255, int(46 + 60 * self._pulse)), 5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(glow, glow.width() / 2.0, glow.height() / 2.0)
        p.setPen(QPen(QColor(10, 132, 255, 235), 2.4))
        p.drawRoundedRect(holef, holef.width() / 2.0, holef.height() / 2.0)
        # 指向气泡的引导箭头（小三角）
        self._draw_arrow(p, holef)
        p.end()

    def _draw_arrow(self, p, holef):
        """从光环指向气泡的小箭头（跟随气泡方向）"""
        side = getattr(self, "_side", "right")
        L = 14.0
        if side == "right":
            tip = QPointF(holef.right() + 6, holef.center().y())
            a = QPointF(tip.x() + L, tip.y() - 7)
            b = QPointF(tip.x() + L, tip.y() + 7)
        elif side == "left":
            tip = QPointF(holef.left() - 6, holef.center().y())
            a = QPointF(tip.x() - L, tip.y() - 7)
            b = QPointF(tip.x() - L, tip.y() + 7)
        elif side == "bottom":
            tip = QPointF(holef.center().x(), holef.bottom() + 6)
            a = QPointF(tip.x() - 7, tip.y() + L)
            b = QPointF(tip.x() + 7, tip.y() + L)
        else:
            tip = QPointF(holef.center().x(), holef.top() - 6)
            a = QPointF(tip.x() - 7, tip.y() - L)
            b = QPointF(tip.x() + 7, tip.y() - L)
        tri = QPainterPath()
        tri.moveTo(tip)
        tri.lineTo(a)
        tri.lineTo(b)
        tri.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 132, 255, int(150 + 80 * self._pulse)))
        p.drawPath(tri)
