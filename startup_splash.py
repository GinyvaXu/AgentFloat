# -*- mode: python ; coding: utf-8 -*-
"""StartupSplash — AgentFloat 启动窗口动画

程序启动时显示居中的启动动画窗口：
- 品牌蓝旋转环 + 「AgentFloat」标题 + 当前启动状态文案
- 启动完成后切换为绿色对勾「已就绪」，约 1 秒后自动淡出
- 出现/消失均有淡入淡出动画；纯 Qt 绘制，无额外依赖
"""
import time

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QLinearGradient
from PyQt5.QtWidgets import QWidget, QApplication

_ACCENT = QColor(77, 107, 254)     # 品牌蓝
_OK = QColor(48, 209, 88)          # 成功绿


class StartupSplash(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("AgentFloat 启动")
        self._phase = "loading"   # loading / done
        self._title = "AgentFloat"
        self._detail = "正在启动…"
        self._angle = 0
        self.setFixedSize(360, 150)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(260)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

    # ── 对外 API ────────────────────────────────────
    def start(self, detail="正在启动…"):
        """显示启动动画（居中）。"""
        self._phase = "loading"
        self._detail = detail
        self._hide_timer.stop()
        self._reposition()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._anim_timer.start()

    def set_detail(self, detail):
        if self._phase == "loading":
            self._detail = detail
            self.update()

    def done(self, detail="已就绪", close_after_ms=1000):
        """启动完成：显示绿色对勾，约 1 秒后自动关闭。"""
        self._phase = "done"
        self._detail = detail
        self._anim_timer.stop()
        self.update()
        self._hide_timer.start(close_after_ms)

    def close_now(self):
        self._hide_timer.stop()
        self._anim_timer.stop()
        self.hide()

    # ── 内部 ────────────────────────────────────────
    def _fade_out(self):
        self._anim_timer.stop()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        try:
            self._fade.finished.disconnect()
        except TypeError:
            pass
        self._fade.finished.connect(self.hide)
        self._fade.start()

    def _on_tick(self):
        self._angle = (self._angle + 5) % 360
        self.update()

    def _reposition(self):
        sw = QApplication.primaryScreen().availableGeometry()
        x = sw.center().x() - self.width() // 2
        y = sw.center().y() - self.height() // 2
        self.move(x, y)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)

        # 毛玻璃卡片
        path = QPainterPath()
        path.addRoundedRect(rect, 20, 20)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(34, 36, 40, 244))
        grad.setColorAt(1.0, QColor(21, 22, 25, 244))
        p.fillPath(path, grad)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawPath(path)

        # 左侧状态图标（旋转环 / 对勾）
        cx = 62.0
        cy = self.height() / 2
        r = 26.0
        if self._phase == "loading":
            p.setPen(QPen(QColor(255, 255, 255, 30), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setPen(QPen(_ACCENT, 5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), int(-self._angle * 16), int(120 * 16))
        else:
            p.setPen(QPen(_OK, 5, Qt.SolidLine, Qt.RoundCap))
            chk = QPainterPath()
            chk.moveTo(cx - 15, cy + 1)
            chk.lineTo(cx - 5, cy + 11)
            chk.lineTo(cx + 15, cy - 10)
            p.drawPath(chk)

        # 标题
        p.setPen(QColor(255, 255, 255, 250))
        font = QFont("Microsoft YaHei UI", 16)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(104, 34, self.width() - 120, 32), Qt.AlignLeft | Qt.AlignVCenter, self._title)

        # 状态文案
        p.setPen(QColor(255, 255, 255, 176))
        font2 = QFont("Microsoft YaHei UI", 10)
        p.setFont(font2)
        p.drawText(QRectF(104, 72, self.width() - 120, 24), Qt.AlignLeft | Qt.AlignVCenter, self._detail)

        # 底部细进度条（仅 loading）
        if self._phase == "loading":
            bar = QRectF(104, 112, self.width() - 130, 3)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 26))
            p.drawRoundedRect(bar, 1.5, 1.5)
            seg = 72.0
            span = max(1.0, bar.width() - seg)
            x0 = bar.left() + (time.time() * 60 % 100.0) / 100.0 * span
            p.setBrush(_ACCENT)
            p.drawRoundedRect(QRectF(x0, bar.top(), seg, bar.height()), 1.5, 1.5)
        p.end()
