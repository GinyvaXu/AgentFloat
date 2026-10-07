# -*- coding: utf-8 -*-
"""浮窗位置收敛单测（PATCH 3.0.1）

覆盖：越界坐标校正 / 非法吸附边 / 多屏就近 / 贴边位置整球可见。
坐标均为逻辑坐标，(left, top, right, bottom) 右下为闭区间。
"""
from agentfloat.ui.placement import (
    EDGE_MARGIN, clamp_visible, edge_position, normalize_edge, screen_index_for,
)

# 单屏 1707x1067（与用户现场一致的 DPI 逻辑尺寸）
SCREENS = [(0, 0, 1706, 1066)]
# 双屏：主屏 1707x1067 + 右侧副屏同样大小
DUAL = [(0, 0, 1706, 1066), (1707, 0, 3413, 1066)]

SIZE = 52


def test_normalize_edge():
    assert normalize_edge("left") == "left"
    assert normalize_edge("right") == "right"
    assert normalize_edge("top") == "top"
    assert normalize_edge("bottom") == "bottom"
    # 非法/空值 → 自由位置
    assert normalize_edge("") == ""
    assert normalize_edge("middle") == ""
    assert normalize_edge(None) == ""


def test_offscreen_right_is_clamped_visible():
    """现场根因：保存坐标 2317 超出 1707 宽屏幕 → 必须收回可见区域"""
    x, y = clamp_visible(2317, 853, SIZE, SCREENS)
    assert x + SIZE <= SCREENS[0][2] - EDGE_MARGIN + 1
    assert EDGE_MARGIN <= x and EDGE_MARGIN <= y
    assert y + SIZE <= SCREENS[0][3] - EDGE_MARGIN + 1


def test_negative_and_far_offscreen_clamped():
    x, y = clamp_visible(-500, -200, SIZE, SCREENS)
    assert (x, y) == (EDGE_MARGIN, EDGE_MARGIN)
    x, y = clamp_visible(99999, 99999, SIZE, SCREENS)
    assert x == SCREENS[0][2] - SIZE - EDGE_MARGIN
    assert y == SCREENS[0][3] - SIZE - EDGE_MARGIN


def test_valid_position_untouched():
    x, y = clamp_visible(800, 400, SIZE, SCREENS)
    assert (x, y) == (800, 400)


def test_secondary_screen_position_kept():
    """副屏上的合法坐标不应被误吸回主屏"""
    x, y = clamp_visible(2400, 400, SIZE, DUAL)
    assert 1707 <= x <= 3413 - SIZE - EDGE_MARGIN
    assert (x, y) == (2400, 400)


def test_offscreen_far_right_goes_to_nearest_screen():
    """主屏右侧外的越界坐标 → 最近屏幕（副屏）而非主屏"""
    x, y = clamp_visible(3600, 400, SIZE, DUAL)
    assert 1707 <= x <= 3413 - SIZE - EDGE_MARGIN


def test_screen_index_for():
    assert screen_index_for(100, 100, SCREENS) == 0
    assert screen_index_for(2000, 400, DUAL) == 1
    # 均不包含 → 就近
    assert screen_index_for(-300, 400, DUAL) == 0
    assert screen_index_for(4000, 400, DUAL) == 1
    assert screen_index_for(0, 0, []) == -1


def test_edge_position_right_fully_visible():
    x, y = edge_position("right", 100, 400, SIZE, SCREENS[0])
    assert x == SCREENS[0][2] - SIZE - EDGE_MARGIN
    assert y == 400


def test_edge_position_clamps_other_axis():
    """贴边时另一轴越界也要收到可见范围"""
    x, y = edge_position("top", 5000, 5000, SIZE, SCREENS[0])
    assert y == EDGE_MARGIN
    assert x == SCREENS[0][2] - SIZE - EDGE_MARGIN
    x, y = edge_position("left", -100, -100, SIZE, SCREENS[0])
    assert x == EDGE_MARGIN
    assert y == EDGE_MARGIN


def test_placement_ring_room():
    """PATCH 3.4.0：贴边时环形菜单让位（向内收 need 半径；屏幕不足则居中）"""
    from agentfloat.ui.placement import ring_room_position
    screens = [(0, 0, 1706, 1066)]
    nx, ny = ring_room_position(1690, 500, 150, screens)
    assert nx == 1706 - 150 and ny == 500
    nx, ny = ring_room_position(10, 10, 150, screens)
    assert nx == 150 and ny == 150
    # 原地不动的情形
    assert ring_room_position(800, 500, 150, screens) == (800, 500)
    # 屏幕不足以容纳整环 → 居中兜底，不越界
    nx, ny = ring_room_position(100, 100, 900, screens)
    assert 0 <= nx <= 1706 and 0 <= ny <= 1066


def test_edge_position_empty_screens_safe():
    # 无屏幕信息时 clamp 原样返回（不抛异常）
    assert clamp_visible(10, 20, SIZE, []) == (10, 20)


# ── v3.8.0：显示器热插拔 / 分辨率变化 / 负坐标副屏 ──────────────
def test_monitor_unplugged_ball_returns_to_remaining_screen():
    """拔掉副屏后，原本在副屏上的浮窗必须回到主屏可见区"""
    was_on_second = (1800, 500)
    after = [SCREENS[0]]                 # 副屏消失
    x, y = clamp_visible(was_on_second[0], was_on_second[1], SIZE, after)
    l, t, r, b = after[0]
    assert l <= x <= r - SIZE and t <= y <= b - SIZE, "应整球落在剩余屏幕内"


def test_resolution_shrink_keeps_ball_visible():
    """分辨率调小后，浮窗不能停在旧坐标（右侧/下方越界）"""
    big = (0, 0, 2559, 1439)
    small = (0, 0, 1279, 719)
    x, y = clamp_visible(big[2] - SIZE - EDGE_MARGIN, big[3] - SIZE - EDGE_MARGIN,
                         SIZE, [small])
    assert x + SIZE <= small[2] and y + SIZE <= small[3]


def test_secondary_screen_with_negative_origin():
    """副屏在主屏左侧（负坐标）时，就近判断与贴边都要正确"""
    left_monitor = [(-1920, 0, -1, 1079), (0, 0, 1706, 1066)]
    assert screen_index_for(-960, 500, left_monitor) == 0
    x, y = edge_position("right", -960, 500, SIZE, left_monitor[0])
    assert left_monitor[0][0] <= x <= left_monitor[0][2] - SIZE + 1
    assert x + SIZE <= 0, "不能越过该屏幕的右边界"


def test_ring_room_position_on_small_screen():
    """小屏幕上环菜单放不下时居中，不返回屏外坐标"""
    from agentfloat.ui.placement import ring_room_position
    tiny = [(0, 0, 799, 599)]
    nx, ny = ring_room_position(10, 10, 400, tiny)
    assert 0 <= nx <= 799 and 0 <= ny <= 599


def test_display_change_handler_wired():
    """浮窗必须监听显示器变化（v3.8.0：热插拔/改分辨率自动收敛）"""
    import inspect
    from agentfloat.ui import floatball
    src = inspect.getsource(floatball)
    for token in ("screenAdded", "screenRemoved", "geometryChanged",
                  "_apply_display_change", "logicalDotsPerInchChanged"):
        assert token in src, "缺少显示器变化处理：%s" % token
    assert "_bind_display_signals" in inspect.getsource(
        floatball.FloatingWidget.__init__), "初始化时应绑定显示器信号"
