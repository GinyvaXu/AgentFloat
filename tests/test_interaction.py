# -*- coding: utf-8 -*-
"""交互状态机测试：覆盖五路输入的历史冲突场景（v1.0.7–v2.2.1 修复过的坑）"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agentfloat.ui.interaction import (  # noqa: E402
    Actions, BallInteraction,
)

CFG = {"enabled": True, "hover_delay_ms": 400, "long_press_delay_ms": 500,
       "trigger_mode": "both"}


def make(**over):
    cfg = dict(CFG)
    cfg.update(over)
    return BallInteraction(cfg)


def test_click():
    m = make()
    m.press(1.0)
    assert m.release(1.2) == [Actions.CLICK]


def test_long_press_replaced_by_hold_launch():
    """PATCH 3.3.0：长按不再开菜单——按住不动到时长触发默认启动"""
    m = make(hold_launch_ms=1000, move_delay_ms=350)
    m.press(0.0)
    assert m.hold_progress(0.5) == 0.5
    assert m.hold_tick(0.9) == []
    assert m.hold_tick(1.0) == [Actions.LAUNCH_HOLD]
    assert m.release(1.2) == []                  # 已启动：松手不再触发点击


def test_hold_release_before_finish_is_click():
    m = make(hold_launch_ms=1000)
    m.press(0.0)
    assert m.release(0.4) == [Actions.CLICK]      # 提前松手 = 单击启动


def test_wheel_on_early_outward_drag():
    """按住立即外滑（未超移动延迟）→ 轮盘；松手由菜单执行"""
    m = make(move_delay_ms=350, wheel_enabled=True)
    m.press(0.0)
    assert m.move(2, 0.05) == []                  # 中心区内微动不打断
    assert m.move(20, 0.10) == [Actions.BEGIN_WHEEL]
    assert m.state == "wheel"
    assert m.release(0.2) == []


def test_outward_move_always_wheel_when_enabled():
    """PATCH 3.3.1：轮盘开启时外滑始终开轮盘（移动浮窗改由轮盘扇区提供）"""
    m = make(wheel_enabled=True)
    m.press(0.0)
    assert m.move(20, 5.0) == [Actions.BEGIN_WHEEL]   # 按住很久后外滑仍是轮盘
    assert m.state == "wheel"


def test_wheel_disabled_falls_back_to_drag():
    m = make(wheel_enabled=False)
    m.press(0.0)
    assert m.move(20, 0.1) == [Actions.BEGIN_DRAG]


def test_slow_press_below_zone_no_drag():
    m = make()
    m.press(0.0)
    m.move(2.0, 0.3)                              # 轻微抖动不判拖拽/轮盘
    assert m.state == "pressed"
    assert m.hold_progress(1.0) > 0


def test_hover_never_opens_menu():
    """PATCH 3.3.1：悬停唤出已取消（只保留按住启动 / 按住外滑轮盘）"""
    m = make()
    m.hover_enter(1.0)
    assert m.hover_channel is False
    assert m.hover_open_allowed(1.2) is False
    m.notify_reveal(2.0)                           # 贴边唤出后同样不展开
    assert m.hover_open_allowed(3.0) is False
    m.press(0.1)
    assert m.release(0.6) == [Actions.CLICK]


def test_menu_open_press_release_no_double_launch():
    m = make()
    m.menu_opened(0.0)
    m.press(1.0)                                   # 菜单打开时按压（交由菜单中心孔处理）
    assert m.release(1.1) == []                    # 不重复触发 CLICK


def test_disabled_menu_keeps_click():
    m = make(enabled=False)
    assert m.hover_open_allowed(1.0) is False
    m.press(0.0)
    assert m.release(0.1) == [Actions.CLICK]       # 菜单禁用不影响单击启动


def test_v330_defaults():
    """PATCH 3.3.0：按住启动 2000ms / 移动延迟 350ms / 轮盘开启 / 按住选环开启"""
    m = BallInteraction({})
    assert m.hold_launch_ms == 2000
    assert m.move_delay_ms == 350
    assert m.wheel_enabled is True
    assert m.hold_select is True
    assert m.hover_delay_ms == 180


def test_hold_select_state_machine():
    """轮盘状态：外滑打开后不再进入拖拽，松手不触发点击（由菜单执行扇区）"""
    m = make(wheel_enabled=True, move_delay_ms=350)
    m.press(0.0)
    assert m.move(40, 0.1) == [Actions.BEGIN_WHEEL]
    assert m.state == "wheel"
    assert m.move(80, 0.2) == []                 # 已进入轮盘：不转拖拽
    assert m.release(0.3) == []
