# -*- coding: utf-8 -*-
"""v3.9.0 新用户引导测试：步骤模型 / 气泡定位 / 聚光灯几何 / 覆盖层烟测"""
import io
import re

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



# ── v3.9.2：教程体验（滚动 / 动画 / 浮球状态联动）──────────────
def test_guide_page_has_scroll_container():
    """指南页必须放在 .content 容器里（否则 overflow-y:auto 不生效，滚轮无法翻动）"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = io.open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()
    m = re.search(r'id="page-guide">\s*<div([^>]*)id="guideContent"', html)
    assert m, "未找到指南页容器"
    assert "content" in m.group(1), "指南页缺少 .content（会导致无法滚动）: %r" % m.group(1)


def test_other_pages_also_use_content_container():
    """其它页同样要有 .content（保持一致，避免再次出现不可滚动页）"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = io.open(os.path.join(root, "web", "index.html"), encoding="utf-8").read()
    for pid in ("page-settings", "page-install", "page-api", "page-news", "page-guide"):
        seg = html.split('id="%s"' % pid, 1)
        assert len(seg) == 2, "缺少页面 %s" % pid
        head = seg[1][:900]
        assert "content" in head, "%s 缺少 .content 容器" % pid


def test_steps_map_to_ball_demos():
    """每一步都要有对应的浮球演示状态（介绍功能时小球处于该状态）"""
    from agentfloat.ui import floatball
    demos = floatball.FloatingWidget.ONBOARDING_DEMOS
    assert len(demos) == len(ob.STEPS), "演示状态数量应与步骤一致"
    assert demos[0] == "hover" and demos[-1] == "restore"
    for name in ("ripple", "hold", "menu", "context", "snap"):
        assert name in demos, "缺少演示状态 %s" % name


def test_overlay_emits_step_changed(qapp):
    """覆盖层切步时通知外层（用于驱动浮球状态）"""
    overlay = ob.OnboardingOverlay(QRect(900, 500, 52, 52), _screen(), theme="dark")
    seen = []
    overlay.step_changed.connect(lambda i: seen.append(i))
    overlay._go(1)
    overlay._go(1)
    overlay._go(-1)
    assert seen == [1, 2, 1], seen


def test_overlay_has_animations(qapp):
    """聚光灯脉冲与气泡滑入动画就绪（v3.9.2）"""
    overlay = ob.OnboardingOverlay(QRect(900, 500, 52, 52), _screen())
    assert overlay._pulse_timer.isActive(), "脉冲定时器应已启动"
    assert overlay._bubble_anim.duration() > 0, "气泡滑入动画应配置时长"
    overlay._on_pulse()          # 单帧推进不抛异常
    overlay._on_pulse()


def test_onboarding_demo_cleanup_is_safe(qapp):
    """演示还原在无菜单/无隐藏状态下也不能抛异常"""
    from agentfloat.ui.floatball import FloatingWidget

    class _Stub(object):
        _radial_menu = None
        _demo_menu = None
        _hidden_now = False
        _onboarding_saved_pos = None
        is_hovered = True

        def _reveal_now(self):
            pass

        def _remove_edge_detector(self):
            pass

        def _animate_scale(self, *a, **k):
            pass

    stub = _Stub()
    FloatingWidget._onboarding_demo_cleanup(stub)
    assert stub.is_hovered is False


def test_web_console_disables_browser_cache():
    """本地控制台静态资源禁用缓存（升级后不必等 4 小时或 Ctrl+F5）"""
    import inspect
    from agentfloat.webshell import server
    src = inspect.getsource(server.create_app)
    assert "no-store" in src, "应给本地页面/静态资源加 no-store"
