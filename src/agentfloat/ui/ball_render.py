# -*- coding: utf-8 -*-
"""浮球位图绘制（主浮球与启动动画共用同一实现，保证视觉一致、去除重复代码）。

沿用 v3.6.2 的深色玻璃质感（方案 A）：深色玻璃底 + 品牌渐变描边 + 内部光晕；
v3.7.0 起内部旋涡 glyph 换成 AF-2 新图标（取自随包资源
``assets/agent_float_swirl.png``，缺失时回退为矢量螺旋绘制，保证冻结/裁剪场景
下仍可渲染）。
"""
import math
import os

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap, QRadialGradient)

# 球体圆角比例（沿用深色玻璃球时期的比例；浮球掩码/涟漪裁剪共用，避免两份魔数）
BALL_RADIUS_RATIO = 0.30

# 描边渐变的收尾色（品牌紫，起点用主题强调色）
BORDER_END = (175, 82, 222)

# 旋涡 glyph 源位图缓存（None=未加载，False=不可用）
_GLYPH_SOURCE = None
_GLYPH_SCALED = {}


def ball_radius(size):
    """球体圆角半径（逻辑像素）"""
    return max(6.0, float(size) * BALL_RADIUS_RATIO)


def draw_spiral(p, cx, cy, k=1.0):
    """矢量回退旋涡：从中心向外 2.35 圈的螺旋线（glyph 资源缺失时使用）"""
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


def _glyph_source():
    """加载并缓存随包旋涡 glyph（失败返回 False，调用方走矢量回退）"""
    global _GLYPH_SOURCE
    if _GLYPH_SOURCE is None:
        pm = QPixmap()
        try:
            from agentfloat.core.paths import SWIRL_PATH
            if os.path.isfile(SWIRL_PATH):
                pm = QPixmap(SWIRL_PATH)
        except Exception:
            pm = QPixmap()
        _GLYPH_SOURCE = pm if not pm.isNull() else False
    return _GLYPH_SOURCE


def _glyph(pixel_size):
    """按目标像素尺寸取缩放后的 glyph（含缓存，避免每帧重采样）"""
    src = _glyph_source()
    if not src:
        return None
    key = int(pixel_size)
    pm = _GLYPH_SCALED.get(key)
    if pm is None:
        pm = src.scaled(key, key, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        _GLYPH_SCALED[key] = pm
    return pm


def render_into(pm, side, size, accent, hovered=False):
    """把浮球绘制到既有位图（位图边长 side，球体直径 size，居中）"""
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    s = float(size)
    cx = cy = side / 2.0
    rad = ball_radius(s)
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

    # 品牌渐变描边（135°：主题强调色 → 品牌紫）
    lg = QLinearGradient(rect.topLeft(), rect.bottomRight())
    ba = 250 if hovered else 220
    lg.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), ba))
    lg.setColorAt(1.0, QColor(BORDER_END[0], BORDER_END[1], BORDER_END[2], ba))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QBrush(lg), max(1.8, s * 0.035)))
    p.drawRoundedRect(rect.adjusted(0.9, 0.9, -0.9, -0.9), rad, rad)

    # 白色旋涡 glyph（AF-2 新图标：与品牌图标同一识别符号）
    try:
        dpr = max(1.0, float(pm.devicePixelRatio()))
    except Exception:
        dpr = 1.0
    glyph = _glyph(max(16, int(round(s * dpr))))
    if glyph is not None:
        glyph.setDevicePixelRatio(dpr)
        gw = s * 0.72      # 与旧绘制比例接近，深色玻璃上留出边距
        p.drawPixmap(QRectF(cx - gw / 2.0, cy - gw / 2.0, gw, gw), glyph,
                     QRectF(0, 0, glyph.width(), glyph.height()))
    else:
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
