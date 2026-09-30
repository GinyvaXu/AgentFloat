# -*- coding: utf-8 -*-
"""浮球位图绘制（v3.6.2）：主浮球与启动动画共用同一实现，保证视觉一致、去除重复代码。

方案 C：深色玻璃 + 品牌渐变描边 + 内部光晕 + 白色旋涡。
"""
import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap, QRadialGradient)


def draw_spiral(p, cx, cy, k=1.0):
    """白色旋涡：从中心向外 2.35 圈的螺旋线"""
    path = QPainterPath()
    n = 56
    for i in range(n + 1):
        t = i / n
        ang = t * math.pi * 2.35 - math.pi * 0.5
        rad = (1.2 + 7.3 * t) * k
        x = cx + math.cos(ang) * rad
        y = cy + math.sin(ang) * rad
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    p.setPen(QPen(QColor(255, 255, 255, 238), max(1.6, 3.2 * k),
                  Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


def render_into(pm, side, size, accent, hovered=False):
    """把浮球绘制到既有位图（位图边长 side，球体直径 size，居中）"""
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    s = float(size)
    cx = cy = side / 2.0
    rad = max(6.0, s * 0.30)
    rect = QRectF(cx - s / 2.0, cy - s / 2.0, s, s)

    # 阴影（悬停加深 / 弹性放大有阴影托底更立体）
    p.setPen(Qt.NoPen)
    base_a = 64 if hovered else 46
    for off, k in ((0.0, 0.45), (2.2, 0.28), (4.2, 0.15)):
        p.setBrush(QColor(0, 0, 0, int(base_a * k)))
        p.drawRoundedRect(rect.adjusted(off, off + 1.2, off, off + 1.2), rad, rad)

    # 深色玻璃底
    p.setBrush(QColor(30, 30, 34, 240))
    p.drawRoundedRect(rect, rad, rad)

    # 内部光晕（品牌色，悬停更亮）
    glow = QRadialGradient(QPointF(cx, rect.y() + s * 0.40), s * 0.55)
    ga = 64 if hovered else 46
    glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), ga))
    glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
    p.setBrush(QBrush(glow))
    p.drawRoundedRect(rect, rad, rad)

    # 品牌渐变描边（135°：#0a84ff → #af52de）
    lg = QLinearGradient(rect.topLeft(), rect.bottomRight())
    ba = 250 if hovered else 220
    lg.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), ba))
    lg.setColorAt(1.0, QColor(175, 82, 222, ba))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QBrush(lg), max(1.8, s * 0.035)))
    p.drawRoundedRect(rect.adjusted(0.9, 0.9, -0.9, -0.9), rad, rad)

    # 白色旋涡 glyph（品牌延续）
    draw_spiral(p, cx, cy, s / 52.0)
    p.end()


def render_ball_pixmap(size, accent, hovered=False, dpr=1.0, margin_ratio=0.10):
    """渲染独立位图：球体直径 size，四周留 margin_ratio*size 给阴影/发光"""
    side = int(round(size * (1.0 + margin_ratio * 2)))
    pm = QPixmap(int(side * dpr), int(side * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    render_into(pm, side, size, accent, hovered)
    return pm
