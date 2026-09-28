# -*- coding: utf-8 -*-
"""环菜单测试（offscreen）：弹簧开合 / 扇区几何命中 / 磁吸滞回 / 点击宽容"""
import math
import time

from PyQt5.QtCore import QPoint

from agentfloat.ui.radial_menu import RadialMenu, RadialMenuItem

CENTER = QPoint(800, 500)


def pump(qapp, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)


def make_menu(qapp, items=6):
    m = RadialMenu()
    m.set_items([RadialMenuItem("i%d" % i, "项%d" % i) for i in range(items)], radius=120)
    m.set_theme("light")
    return m


def gp(phi_deg, r=80):
    """以环心为基准，沿 φ（顶部=0°，顺时针）取全局坐标点"""
    return QPoint(int(CENTER.x() + r * math.sin(math.radians(phi_deg))),
                  int(CENTER.y() - r * math.cos(math.radians(phi_deg))))


def test_open_close_spring(qapp):
    m = make_menu(qapp)
    closed = []
    m.closed.connect(lambda: closed.append(1))
    m.open_at(CENTER, anchor_rect=None)
    m._poll.stop()          # 无头环境：真实光标在窗口外，停掉自动关闭轮询
    m._close_timer.stop()
    pump(qapp, 1.2)
    assert abs(m._progress_state.value - 1.0) < 1e-3
    assert m.isVisible()

    m.close_menu()
    pump(qapp, 1.2)
    assert not m.isVisible()
    assert abs(m._progress_state.value) < 1e-6
    assert closed == [1]


def test_sector_geometry(qapp):
    m = make_menu(qapp)
    m.open_at(CENTER, anchor_rect=None)
    m._poll.stop()
    m._close_timer.stop()
    pump(qapp, 1.2)
    assert m._sector_at(gp(30)) == 0
    assert m._sector_at(gp(90)) == 1
    assert m._sector_at(gp(150)) == 2
    # 环带外 → 未命中
    assert m._sector_at(gp(30, r=300)) == -1


def test_magnet_hysteresis(qapp):
    m = make_menu(qapp)
    m.open_at(CENTER, anchor_rect=None)
    m._poll.stop()
    m._close_timer.stop()
    pump(qapp, 1.2)

    m._hover_idx = 5
    assert m._apply_magnet(gp(3), m._sector_at(gp(3))) == 5, "临近 5/0 边界应保持 5"
    m._hover_idx = 1
    assert m._apply_magnet(gp(57), m._sector_at(gp(57))) == 1, "临近 0/1 边界应保持 1"
    m._hover_idx = 5
    assert m._apply_magnet(gp(30), m._sector_at(gp(30))) == 0, "非边界区不应粘滞"


def test_click_index_tolerance(qapp):
    m = make_menu(qapp)
    m.open_at(CENTER, anchor_rect=None)
    m._poll.stop()
    m._close_timer.stop()
    pump(qapp, 1.2)
    m._hover_idx = 2
    assert m._click_index(gp(150)) == 2          # 命中扇区
    assert m._click_index(gp(150, r=130)) == 2   # 环带外 8~14px：沿用高亮扇区（磁吸宽容）


def test_sector_path(qapp):
    m = make_menu(qapp)
    path = m._sector_path(0)
    assert not path.isEmpty()
    assert m._sector_path(99).isEmpty(), "非法下标应返回空路径"
    empty = RadialMenu()
    assert empty._sector_path(0).isEmpty(), "无扇区时应返回空路径"


def test_polar_math(qapp):
    m = make_menu(qapp)
    p = m._polar(-90, 10)
    assert abs(p.x()) < 1e-6 and abs(p.y() + 10) < 1e-6   # -90° = 正上方（菜单绘制约定）
    p2 = m._polar(0, 10)
    assert abs(p2.x() - 10) < 1e-6 and abs(p2.y()) < 1e-6  # 0° = 右侧


def test_press_glow_progress_default(qapp):
    m = make_menu(qapp)
    assert m._press_progress == 0.0
    m._start_press(1)
    assert m._press_idx == 1
    m._reset_press()
    assert m._press_idx == 1   # 动画结束后才清除


# ── PATCH 3.2.0：按住选环 + 扇区预渲染 ──

def test_hold_select_flow(qapp):
    m = make_menu(qapp)
    got = []
    m.action_triggered.connect(lambda aid: got.append(aid))
    m.open_at(CENTER, anchor_rect=None)
    m._poll.stop()
    m._close_timer.stop()
    pump(qapp, 1.2)
    assert m.begin_hold() is True
    assert m._hold_active is True
    assert m.end_hold(gp(30)) is True       # 命中扇区 0（顶部）
    pump(qapp, 0.4)
    assert got == ["i0"]


def test_hold_select_disabled(qapp):
    m = make_menu(qapp)
    m.set_hold_mode(False)
    m.open_at(CENTER, anchor_rect=None)
    m._poll.stop()
    m._close_timer.stop()
    pump(qapp, 1.2)
    assert m.begin_hold() is False
    assert m.end_hold(gp(30)) is False       # 未进入选环模式：由点击选择负责


def test_hold_select_cancel_at_center(qapp):
    m = make_menu(qapp)
    got = []
    m.action_triggered.connect(lambda aid: got.append(aid))
    m.open_at(CENTER, anchor_rect=None)
    m._poll.stop()
    m._close_timer.stop()
    pump(qapp, 1.2)
    m.begin_hold()
    assert m.end_hold(QPoint(CENTER.x(), CENTER.y())) is True
    pump(qapp, 0.4)
    assert got == [], "中心孔松手应取消，不触发任何扇区"


def test_sector_pixmap_cache(qapp):
    m = make_menu(qapp)
    pm1 = m._sector_pixmap(0, False, 1.0)
    pm2 = m._sector_pixmap(0, False, 1.0)
    assert pm1 is pm2, "同键应命中预渲染缓存"
    assert not pm1.isNull()
    hover = m._sector_pixmap(0, True, 1.0)
    assert hover is not pm1
    m.set_items([RadialMenuItem("x", "X")])
    assert m._pixmaps == {}, "set_items 应清空预渲染缓存"


def test_render_with_pixmaps(qapp):
    """预渲染绘制冒烟：展开后能正常出图（含悬停高亮与配色切换）"""
    m = make_menu(qapp)
    m.open_at(CENTER, anchor_rect=None)
    m._poll.stop()
    m._close_timer.stop()
    pump(qapp, 1.2)
    m._hover_idx = 2
    m.update()
    pump(qapp, 0.2)
    grab = m.grab()
    assert not grab.isNull() and grab.width() > 0, "预渲染绘制应能正常出图"
    m.set_theme("dark")
    m.update()
    pump(qapp, 0.2)
    assert not m.grab().isNull()
