# -*- coding: utf-8 -*-
"""弹簧动效引擎测试：收敛性 / 可打断 / 速度继承 / dt 截断 / reduced-motion"""
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from agentfloat.ui.motion import (  # noqa: E402
    SpringState, Tokens, set_reduced_motion,
)


def test_spring_converges():
    s = SpringState(0.0, *Tokens.SPEED)
    s.to(1.0)
    for _ in range(600):
        if not s.step(1 / 60.0):
            break
    assert abs(s.value - 1.0) < 1e-6
    assert s.velocity == 0.0


def test_spring_interrupt_keeps_velocity():
    s = SpringState(0.0, *Tokens.SPEED)
    s.to(1.0)
    for _ in range(6):
        s.step(1 / 60.0)
    v_before = s.velocity
    assert v_before > 0
    s.to(0.0)                          # 打断重定向
    assert s.goal == 0.0
    assert s.velocity == v_before      # 速度继承（无突变）


def test_spring_large_dt_is_capped():
    s = SpringState(0.0, *Tokens.SPEED)
    s.to(1.0)
    s.step(10.0)                       # 超大 dt 被截断，不炸
    assert 0.0 <= s.value <= 1.0
    assert abs(s.velocity) < 30.0


def test_spring_jump_resets():
    s = SpringState(0.5, *Tokens.SPEED)
    s.to(1.0)
    s.step(1 / 60.0)
    s.jump(0.2)
    assert s.value == 0.2
    assert s.velocity == 0.0
    assert s.goal == 0.2


def test_reduced_motion_jumps():
    set_reduced_motion(True)
    try:
        s = SpringState(0.0, *Tokens.SPEED)
        s.to(1.0)
        assert s.step(1 / 60.0) is False
        assert s.value == 1.0
    finally:
        set_reduced_motion(False)
