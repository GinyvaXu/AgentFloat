# -*- coding: utf-8 -*-
"""窗口动效工具（PATCH 3.3.0）：统一渐入/渐出（透明度 + 轻微位移）

所有浮动面板/弹窗共用，保证「全流程窗口都有合理的渐出渐入」。
- fade_in: 透明度 0→1 + 轻微上浮（8px），弹簧/缓动收尾
- fade_out: 透明度 1→0 + 轻微下沉，结束后可回调（默认 hide）
"""
from PyQt5.QtCore import QPropertyAnimation, QEasingCurve, QPoint, QParallelAnimationGroup

from agentfloat.ui.motion import Tokens


def _fade_anim(widget, start, end, duration, curve):
    a = QPropertyAnimation(widget, b"windowOpacity", widget)
    a.setDuration(duration)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(curve)
    return a


def fade_in(widget, duration=None, slide_px=8):
    """渐入：透明度 0→当前 + 从下方滑入（不动窗口位置属性，用 geometry 偏移）"""
    duration = duration or Tokens.PANEL_IN_MS
    try:
        target = max(0.6, min(1.0, widget.windowOpacity() if widget.windowOpacity() > 0 else 1.0))
    except Exception:  # noqa: BLE001
        target = 1.0
    widget.setWindowOpacity(0.0)
    group = QParallelAnimationGroup(widget)
    group.addAnimation(_fade_anim(widget, 0.0, target, duration, QEasingCurve.OutCubic))
    if slide_px:
        try:
            geo = widget.geometry()
            start_pos = geo.topLeft() + QPoint(0, slide_px)
            widget.move(start_pos)
            pa = QPropertyAnimation(widget, b"pos", widget)
            pa.setDuration(duration)
            pa.setStartValue(start_pos)
            pa.setEndValue(geo.topLeft())
            pa.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(pa)
        except Exception:  # noqa: BLE001
            pass
    # 持有引用防止被 GC
    widget._fade_group = group
    group.start()


def fade_out(widget, duration=None, on_done=None, slide_px=6):
    """渐出：透明度 →0 + 轻微下沉，结束后回调（默认 hide）"""
    duration = duration or Tokens.PANEL_OUT_MS
    try:
        start = widget.windowOpacity()
    except Exception:  # noqa: BLE001
        start = 1.0
    group = QParallelAnimationGroup(widget)
    group.addAnimation(_fade_anim(widget, start, 0.0, duration, QEasingCurve.InCubic))
    if slide_px:
        try:
            geo = widget.geometry()
            pa = QPropertyAnimation(widget, b"pos", widget)
            pa.setDuration(duration)
            pa.setStartValue(geo.topLeft())
            pa.setEndValue(geo.topLeft() + QPoint(0, slide_px))
            pa.setEasingCurve(QEasingCurve.InCubic)
            group.addAnimation(pa)
        except Exception:  # noqa: BLE001
            pass
    widget._fade_group = group

    def _done():
        try:
            widget.setWindowOpacity(1.0)   # 复位，便于下次渐入
        except Exception:  # noqa: BLE001
            pass
        if on_done is not None:
            on_done()
        else:
            widget.hide()

    group.finished.connect(_done)
    group.start()
