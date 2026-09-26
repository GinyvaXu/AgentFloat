# -*- coding: utf-8 -*-
"""交互状态机测试：覆盖五路输入的历史冲突场景（v1.0.7–v2.2.1 修复过的坑）"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agentfloat.ui.interaction import (  # noqa: E402
    Actions, BallInteraction, CLICK_MOVE_PX,
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


def test_long_press_then_release_no_click():
    m = make()
    m.press(0.0)
    assert m.should_arm_long_press() is True
    assert m.long_press_fired(0.6) == [Actions.OPEN_MENU]
    assert m.release(0.7) == []          # 长按后释放不再触发点击


def test_drag_cancels_long_press_and_click():
    m = make()
    m.press(0.0)
    assert m.move(CLICK_MOVE_PX + 1, 0.1) == [Actions.BEGIN_DRAG]
    assert m.should_arm_long_press() is False
    assert m.long_press_fired(0.6) == []  # 拖拽中长按无效（防误弹菜单）
    assert m.release(0.9) == [Actions.END_DRAG]


def test_slow_press_below_threshold_is_long_press():
    m = make()
    m.press(0.0)
    m.move(2.0, 0.3)                      # 轻微抖动不判拖拽
    assert m.long_press_fired(0.6) == [Actions.OPEN_MENU]


def test_hover_open():
    m = make()
    m.hover_enter(1.0)
    assert m.hover_open_allowed(1.2) is True
    assert m.hover_timer_fired(1.4) == [Actions.OPEN_MENU]


def test_hover_suppressed_after_reveal():
    m = make()
    m.notify_reveal(10.0)
    assert m.hover_open_allowed(10.3) is False    # ① 600ms 抑制
    assert m.hover_timer_fired(10.5) == []        # 计时器到点也被最终校验拦下
    assert m.hover_open_allowed(10.7) is True     # 窗口结束后需重新进入才会重新计时


def test_hover_suppressed_after_drag_end():
    m = make()
    m.press(0.0)
    m.move(10, 0.1)
    m.release(0.2)                                 # 拖拽结束 → ② 400ms 抑制
    assert m.hover_open_allowed(0.5) is False
    assert m.hover_open_allowed(0.7) is True


def test_hover_suppressed_after_menu_closed():
    m = make()
    m.menu_opened(0.0)
    m.menu_closed(1.0)                             # ③ 500ms 抑制
    assert m.hover_open_allowed(1.4) is False
    assert m.hover_open_allowed(1.6) is True


def test_press_cancels_hover_open():
    m = make()
    m.hover_enter(0.0)
    m.press(0.1)                                   # 按压后计时器到点也不展开（④）
    assert m.hover_timer_fired(0.5) == []
    assert m.release(0.6) == [Actions.CLICK]


def test_menu_open_press_release_no_double_launch():
    m = make()
    m.menu_opened(0.0)
    m.press(1.0)                                   # 菜单打开时按压（交由菜单中心孔处理）
    assert m.release(1.1) == []                    # 不重复触发 CLICK


def test_mode_long_press_only():
    m = make(trigger_mode="long_press")
    assert m.hover_open_allowed(1.0) is False
    m.press(1.0)
    assert m.long_press_fired(1.6) == [Actions.OPEN_MENU]


def test_mode_hover_only():
    m = make(trigger_mode="hover")
    m.press(0.0)
    assert m.should_arm_long_press() is False
    assert m.long_press_fired(0.6) == []


def test_disabled_menu_keeps_click():
    m = make(enabled=False)
    assert m.hover_open_allowed(1.0) is False
    m.press(0.0)
    assert m.should_arm_long_press() is False
    assert m.release(0.1) == [Actions.CLICK]       # 菜单禁用不影响单击启动
