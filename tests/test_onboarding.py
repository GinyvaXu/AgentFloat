# -*- coding: utf-8 -*-
"""v3.9.0 新用户引导测试：步骤模型 / 气泡定位 / 聚光灯几何 / 覆盖层烟测"""
from PyQt5.QtCore import QRect

from agentfloat.ui import onboarding as ob


def test_steps_are_wellformed():
    assert len(ob.STEPS) >= 4, "引导步数太少"
    for i, s in enumerate(ob.STEPS, 1):
        assert s["title"] and s["desc"], "第 %d 步缺少标题或说明" % i
        assert s["anchor"] == "ball"
    titles = [s["title"] for s in ob.STEPS]
    assert len(set(titles)) == len(titles), "步骤标题不应重复"
    # 末步必须告诉用户如何重看
    assert "教程" in ob.STEPS[-1]["desc"]


def test_spotlight_wraps_ball_with_padding():
    ball = QRect(100, 200, 52, 52)
    hole = ob.spotlight_rect(ball)
    assert hole.contains(ball)
    assert hole.width() == 52 + ob.HOLE_PAD * 2


def _screen():
    return QRect(0, 0, 1920, 1080)


def test_bubble_prefers_right_then_left():
    screen = _screen()
    ball = QRect(900, 500, 52, 52)
    rect, side = ob.bubble_geometry(ball, screen)
    assert side == "right" and rect.left() > ball.right(), rect
    assert rect.right() <= screen.right() - ob.MARGIN
    # 贴右边时改放左侧
    ball2 = QRect(1860, 500, 52, 52)
    rect2, side2 = ob.bubble_geometry(ball2, screen)
    assert side2 == "left" and rect2.right() < ball2.left()


def test_bubble_falls_back_to_vertical_then_clamped():
    screen = QRect(0, 0, 700, 500)      # 窄屏：左右都放不下 → 下/上
    ball = QRect(324, 240, 52, 52)
    rect, side = ob.bubble_geometry(ball, screen)
    assert side in ("bottom", "top"), side
    # 极小屏幕：仍必须收在屏幕内
    tiny = QRect(0, 0, 320, 240)
    rect3, _side = ob.bubble_geometry(QRect(140, 110, 52, 52), tiny)
    assert rect3.left() >= tiny.left() + ob.MARGIN
    assert rect3.right() <= tiny.right() - ob.MARGIN
    assert rect3.top() >= tiny.top() + ob.MARGIN
    assert rect3.bottom() <= tiny.bottom() - ob.MARGIN


def test_overlay_step_flow(qapp):
    """覆盖层：走完 6 步触发 finished(True)；跳过触发 finished(False)"""
    seen = []
    overlay = ob.OnboardingOverlay(QRect(900, 500, 52, 52), _screen(), theme="dark")
    overlay.finished.connect(lambda ok: seen.append(ok))
    assert overlay._index == 0
    for _ in range(len(ob.STEPS) - 1):
        overlay._go(1)
    assert overlay._index == len(ob.STEPS) - 1
    overlay._go(1)                     # 最后一步 → 完成
    assert seen == [True]

    overlay2 = ob.OnboardingOverlay(QRect(900, 500, 52, 52), _screen())
    seen2 = []
    overlay2.finished.connect(lambda ok: seen2.append(ok))
    overlay2._go(-1)                   # 已在第一步，不越界
    assert overlay2._index == 0
    overlay2._finish(False)
    assert seen2 == [False]


def test_overlay_buttons_and_keys(qapp):
    overlay = ob.OnboardingOverlay(QRect(100, 100, 52, 52), _screen())
    assert overlay._prev.isVisible() is False or not overlay._prev.isEnabled()
    overlay._next.click()              # 下一步
    assert overlay._index == 1
    assert overlay._prev.isEnabled()
    overlay._prev.click()              # 上一步
    assert overlay._index == 0


def test_config_has_onboarding_flags(tmp_path, monkeypatch):
    """首次配置必须带 onboarding_done（否则每次启动都会弹引导）"""
    from agentfloat.core import config as cfgmod
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(cfgmod, "_OLD_CONFIG_PATH", str(tmp_path / "old.json"))
    cfg = cfgmod.load_config()
    assert cfg.get("onboarding_done") is False
    assert "onboarding_version" in cfg


def test_news_defaults_include_v2_fields():
    from agentfloat.services.news.fetcher import DEFAULT_NEWS
    for key in ("per_source", "ai_max_items", "blocked_keywords", "retention_days",
                "density"):
        assert key in DEFAULT_NEWS, "快报默认配置缺少 %s" % key

