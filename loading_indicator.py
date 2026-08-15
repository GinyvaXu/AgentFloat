# -*- mode: python ; coding: utf-8 -*-
"""LoadingIndicator — 动画加载指示器（浮窗锚定的毛玻璃小卡片）

用于 dsh 启动、Web 壳打开等后台任务的进度可视化：
- loading：旋转加载环 + 无限进度条动画 + 阶段文案 + 已等待秒数
- success：绿色对勾，短暂展示后自动淡出
- error：红色叹号，展示后自动淡出
- 出现/消失均有淡入淡出动画
"""
import time

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QLinearGradient
from PyQt5.QtWidgets import QWidget, QApplication

_ACCENT = QColor(77, 107, 254)     # 品牌蓝
_OK = QColor(48, 209, 88)          # 成功绿
_ERR = QColor(255, 95, 86)         # 错误红


class LoadingIndicator(QWidget):
    def __init__(self, anchor=None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("AgentFloat 加载")
        self._anchor = anchor
        self._phase = "loading"   # loading / success / error
        self._title = ""
        self._detail = ""
        self._angle = 0
        self._progress_off = 0.0
        self.setFixedSize(292, 94)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._on_tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

    # ── 对外 API ────────────────────────────────────
    def show_loading(self, title, detail=""):
        self._phase = "loading"
        self._title = title
        self._detail = detail
        self._reposition()
        self._present()

    def set_detail(self, detail):
        if self._phase == "loading":
            self._detail = detail
            self.update()

    def show_success(self, text, detail=""):
        self._phase = "success"
        self._title = text
        self._detail = detail
        self._anim_timer.stop()
        self._reposition()
        self._present()

    def show_error(self, text, detail=""):
        self._phase = "error"
        self._title = text
        self._detail = detail
        self._anim_timer.stop()
        self._reposition()
        self._present()

    def hide_after(self, ms):
        self._hide_timer.start(ms)

    def hide_now(self):
        self._hide_timer.stop()
        self._anim_timer.stop()
        self.hide()

    # ── 内部 ────────────────────────────────────────
    def _present(self):
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        if self._phase == "loading":
            self._anim_timer.start()

    def _fade_out(self):
        self._anim_timer.stop()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide, Qt.UniqueConnection)
        self._fade.start()

    def _on_tick(self):
        self._angle = (self._angle + 5) % 360
        self._progress_off = (self._progress_off + 2.2) % 100.0
        self.update()

    def _reposition(self):
        sw = QApplication.primaryScreen().availableGeometry()
        w, h = self.width(), self.height()
        if self._anchor is not None and getattr(self._anchor, "isVisible", lambda: False)():
            g = self._anchor.geometry()
            x = g.center().x() - w // 2
            y = g.top() - h - 14
            if y < sw.top() + 8:
                y = g.bottom() + 14  # 上方放不下则放到浮窗下方
        else:
            x = sw.center().x() - w // 2
            y = sw.center().y() - h // 2
        x = max(sw.left() + 8, min(x, sw.right() - w - 8))
        y = max(sw.top() + 8, min(y, sw.bottom() - h - 8))
        self.move(x, y)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)

        # 毛玻璃卡片
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(34, 36, 40, 236))
        grad.setColorAt(1.0, QColor(21, 22, 25, 236))
        p.fillPath(path, grad)
        p.setPen(QPen(QColor(255, 255, 255, 36), 1))
        p.drawPath(path)

        # 左侧状态图标
        cx = 58
        cy = self.height() / 2
        r = 21
        if self._phase == "loading":
            p.setPen(QPen(QColor(255, 255, 255, 28), 4, Qt.SolidLine, Qt.RoundCap))
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setPen(QPen(_ACCENT, 4, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), int(-self._angle * 16), int(100 * 16))
        elif self._phase == "success":
            p.setPen(QPen(_OK, 4, Qt.SolidLine, Qt.RoundCap))
            chk = QPainterPath()
            chk.moveTo(cx - 13, cy + 1)
            chk.lineTo(cx - 4, cy + 10)
            chk.lineTo(cx + 13, cy - 9)
            p.drawPath(chk)
        else:
            p.setPen(QPen(_ERR, 4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx - 9, cy - 9), QPointF(cx + 9, cy + 9))
            p.drawLine(QPointF(cx - 9, cy + 9), QPointF(cx + 9, cy - 9))

        # 标题
        p.setPen(QColor(255, 255, 255, 246))
        font = QFont("Microsoft YaHei UI", 10)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(94, 12, self.width() - 108, 26), Qt.AlignLeft | Qt.AlignVCenter, self._title)

        # 详情
        p.setPen(QColor(255, 255, 255, 168))
        font2 = QFont("Microsoft YaHei UI", 8)
        p.setFont(font2)
        p.drawText(QRectF(94, 40, self.width() - 108, 18), Qt.AlignLeft | Qt.AlignVCenter, self._detail)

        # 底部无限进度条（仅 loading）
        if self._phase == "loading":
            bar = QRectF(94, 68, self.width() - 108, 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 24))
            p.drawRoundedRect(bar, 2, 2)
            seg = 64.0
            x0 = bar.left() + (self._progress_off - seg)
            p.setBrush(_ACCENT)
            p.drawRoundedRect(QRectF(x0, bar.top(), seg, bar.height()), 2, 2)
        p.end()
