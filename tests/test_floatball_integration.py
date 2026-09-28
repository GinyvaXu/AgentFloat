# -*- coding: utf-8 -*-
"""浮球集成冒烟（offscreen）：交互全链路 + 渲染 + 弹簧缩放 + 退出动画

注意：本文件内测试共享一个 FloatingWidget 实例（module 级），
按文件内顺序执行；最后一项（退出）会结束 widget 生命周期。
"""
import time

import pytest
from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent


@pytest.fixture(scope="module")
def ball(qapp):
    import agentfloat.ui.floatball as fb
    orig = fb.save_config
    fb.save_config = lambda cfg: None          # 测试期间不落盘
    w = fb.FloatingWidget()
    w.move(500, 400)
    _pump(qapp, 0.3)
    yield w
    try:
        w.close()
    finally:
        fb.save_config = orig


def _pump(qapp, seconds=0.4):
    deadline = time.time() + seconds
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)


def _mev(kind, local, gx, gy):
    btn = Qt.LeftButton
    return QMouseEvent(kind, QPointF(*local), QPointF(gx, gy), btn, btn, Qt.NoModifier)


def test_interaction_flow(ball, qapp):
    w = ball
    launched = []
    w.launch_requested.connect(lambda: launched.append(1))
    gx, gy = w.pos().x() + 20, w.pos().y() + 20

    # 单击 → 启动
    w.mousePressEvent(_mev(QEvent.MouseButtonPress, (20, 20), gx, gy))
    assert w._interaction.state == "pressed"
    w.mouseReleaseEvent(_mev(QEvent.MouseButtonRelease, (20, 20), gx, gy))
    assert launched == [1]

    # 长按 → 环菜单（释放不再启动）
    w.mousePressEvent(_mev(QEvent.MouseButtonPress, (20, 20), gx, gy))
    w._on_long_press_fired()
    _pump(qapp, 0.3)
    assert w._interaction.state == "menu_held"
    assert w._radial_menu is not None and w._radial_menu.isVisible()
    w.mouseReleaseEvent(_mev(QEvent.MouseButtonRelease, (20, 20), gx, gy))
    assert launched == [1]
    w._close_radial_menu()
    _pump(qapp, 0.5)
    assert w._interaction.hover_open_allowed(time.monotonic()) is False  # 菜单关闭冷却

    # 拖拽 → 不弹菜单、不触发启动
    w.mousePressEvent(_mev(QEvent.MouseButtonPress, (20, 20), gx, gy))
    w.mouseMoveEvent(_mev(QEvent.MouseMove, (44, 44), gx + 24, gy + 24))
    assert w._interaction.state == "dragging" and w._drag_active is True
    w._on_long_press_fired()
    assert w._radial_menu is None or not w._radial_menu.isVisible()
    w.mouseReleaseEvent(_mev(QEvent.MouseButtonRelease, (44, 44), gx + 24, gy + 24))
    assert launched == [1]
    assert w._interaction.hover_open_allowed(time.monotonic()) is False  # 拖拽冷却
    assert w._interaction.hover_open_allowed(time.monotonic() + 0.5) is True

    # 贴边唤出抑制
    w._interaction.notify_reveal(time.monotonic())
    assert w._interaction.hover_open_allowed(time.monotonic() + 0.2) is False


def test_render_and_scale(ball, qapp):
    w = ball
    grab = w.grab()
    assert not grab.isNull() and grab.width() > 0, "paintEvent 应能渲染"
    assert w.width() > w.current_size, "窗口应含留白（P2 固定窗口）"

    w._animate_scale(1.05, None)
    _pump(qapp, 0.8)
    assert abs(w._visual_scale - 1.05) < 0.02
    w._animate_scale(1.0, None)
    _pump(qapp, 0.8)
    assert abs(w._visual_scale - 1.0) < 0.02


def test_apply_settings_merges_plain_keys(ball, qapp):
    """PATCH 3.1.1：check_updates / hide_delay_ms 等顶层键必须真正合并，

    否则保存收尾的 save_config(self.config) 会把它们写回旧值（改了存不住）。
    """
    w = ball
    new_cfg = dict(w.config)
    new_cfg["check_updates"] = not w.config.get("check_updates", True)
    new_cfg["hide_delay_ms"] = 1234
    new_cfg["auto_start"] = w.config.get("auto_start", False)   # 保持不变，避免真去创建快捷方式
    w.apply_settings(new_cfg, preview_only=False)
    assert w.config["check_updates"] == new_cfg["check_updates"]
    assert w.config["hide_delay_ms"] == 1234


def test_quit_spring(ball, qapp):
    w = ball
    got = []
    w.quit_requested.connect(lambda: got.append(1))
    w._animate_quit()
    deadline = time.time() + 4
    while time.time() < deadline and not got:
        qapp.processEvents()
        time.sleep(0.02)
    assert got == [1], "退出弹簧动画应发出 quit_requested"
