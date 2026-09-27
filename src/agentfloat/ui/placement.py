# -*- coding: utf-8 -*-
"""浮窗位置收敛（纯逻辑，可单测）

坐标体系与 Qt 顶层窗口一致（逻辑坐标）；屏幕可用区域表示为
``(left, top, right, bottom)``，right / bottom 与 QRect 一致为闭区间
（即 ``right = left + width - 1``）。

PATCH 3.0.1 背景：更换显示器 / 修改 DPI 缩放后，配置里保存的浮窗坐标
可能落在所有屏幕之外，且 ``snap_edge`` 可能是空串等非法值，导致浮窗
「失踪」且扇形菜单无法唤出。这里的函数负责把任意坐标收敛到可见区域，
并规范吸附边取值。
"""
VALID_EDGES = ("left", "right", "top", "bottom")
EDGE_MARGIN = 2          # 球体与屏幕边缘的最小间距（与既有贴边逻辑一致）


def normalize_edge(edge):
    """规范吸附边：合法值原样返回，非法/空值返回 ""（表示自由位置）"""
    return edge if edge in VALID_EDGES else ""


def screen_index_for(cx, cy, screens):
    """返回包含点 (cx, cy) 的屏幕下标；都不包含时返回距离最近的屏幕下标。

    无屏幕时返回 -1。
    """
    if not screens:
        return -1
    for i, (l, t, r, b) in enumerate(screens):
        if l <= cx <= r and t <= cy <= b:
            return i
    best, best_d = 0, None
    for i, (l, t, r, b) in enumerate(screens):
        dx = max(l - cx, 0, cx - r)
        dy = max(t - cy, 0, cy - b)
        d = dx * dx + dy * dy
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def _bounds(size, screen):
    """某屏幕内球体左上角的允许范围（整球可见 + 边缘留白）"""
    l, t, r, b = screen
    min_x, min_y = l + EDGE_MARGIN, t + EDGE_MARGIN
    max_x = max(min_x, r - size - EDGE_MARGIN)
    max_y = max(min_y, b - size - EDGE_MARGIN)
    return min_x, min_y, max_x, max_y


def clamp_visible(x, y, size, screens):
    """把球体左上角 (x, y) 收进最近屏幕的可用区域，保证整球可见。

    screens 为空时原样返回。
    """
    if not screens:
        return int(x), int(y)
    idx = screen_index_for(x + size / 2.0, y + size / 2.0, screens)
    min_x, min_y, max_x, max_y = _bounds(size, screens[idx])
    return int(min(max(x, min_x), max_x)), int(min(max(y, min_y), max_y))


def edge_position(edge, x, y, size, screen):
    """按吸附边计算球体坐标；另一轴保持原值并钳制在屏幕内（整球可见）。

    edge 应为合法值（先经 normalize_edge）；未知值按 bottom 处理。
    """
    min_x, min_y, max_x, max_y = _bounds(size, screen)
    if edge == "left":
        return min_x, int(min(max(y, min_y), max_y))
    if edge == "right":
        return max_x, int(min(max(y, min_y), max_y))
    if edge == "top":
        return int(min(max(x, min_x), max_x)), min_y
    return int(min(max(x, min_x), max_x)), max_y
