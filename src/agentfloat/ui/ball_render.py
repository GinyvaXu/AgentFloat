# -*- coding: utf-8 -*-
"""浮球位图绘制（主浮球与启动动画共用同一实现，保证视觉一致、去除重复代码）。

v3.7.0 品牌更新：与「AgentFloat」新图标一致 —— 紫→蓝品牌渐变圆角底 +
白色旋涡 glyph（取自随包资源 ``assets/agent_float_swirl.png``，缺失时回退
为矢量螺旋绘制，保证冻结/裁剪场景下仍可渲染）。
"""
import math
import os

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap)

# 品牌渐变端点（取样自新图标 1024px 原稿的左上 / 中心 / 右下角）
BRAND_START = (150, 47, 229)      # 紫 #962FE5
BRAND_MID = (70, 58, 236)         # 中段 #463AEC
BRAND_END = (2, 133, 254)         # 蓝 #0285FE

# 球体圆角比例（与图标方圆角一致；浮球掩码/涟漪裁剪共用，避免两份魔数）
BALL_RADIUS_RATIO = 0.22

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

    # 品牌渐变底（135°：紫 → 蓝，与新图标同源）
    lg = QLinearGradient(rect.topLeft(), rect.bottomRight())
    boost = 14 if hovered else 0
    lg.setColorAt(0.0, QColor(min(255, BRAND_START[0] + boost),
                              min(255, BRAND_START[1] + boost),
                              min(255, BRAND_START[2] + boost)))
    lg.setColorAt(1.0, QColor(min(255, BRAND_END[0] + boost),
                              min(255, BRAND_END[1] + boost),
                              min(255, BRAND_END[2] + boost)))
    # 中段取样自原稿中心色，避免角对角线性插值把中段冲淡
    lg.setColorAt(0.5, QColor(min(255, BRAND_MID[0] + boost),
                              min(255, BRAND_MID[1] + boost),
                              min(255, BRAND_MID[2] + boost)))
    p.setBrush(QBrush(lg))
    p.drawRoundedRect(rect, rad, rad)

    # 顶部微高光：给平面渐变一点玻璃厚度（不影响图标还原度）
    sheen = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + s * 0.45))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 30))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(sheen))
    p.drawRoundedRect(rect, rad, rad)

    # 边缘描边：常态极淡白边；悬停转为品牌色高亮环（兼作悬停反馈）
    ring = QColor(accent.red(), accent.green(), accent.blue(), 120) if hovered \
        else QColor(255, 255, 255, 40)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(ring, max(1.2, s * 0.022)))
    p.drawRoundedRect(rect.adjusted(0.6, 0.6, -0.6, -0.6), rad, rad)

    # 白色旋涡 glyph（与图标同比例：约占球体 45%）
    try:
        dpr = max(1.0, float(pm.devicePixelRatio()))
    except Exception:
        dpr = 1.0
    glyph = _glyph(max(16, int(round(s * dpr))))
    if glyph is not None:
        glyph.setDevicePixelRatio(dpr)
        p.drawPixmap(QRectF(cx - s / 2.0, cy - s / 2.0, s, s), glyph,
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
