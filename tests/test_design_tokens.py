# -*- coding: utf-8 -*-
"""v3.8.0 设计令牌一致性测试

背景：改造前圆角散落 4/6/7/8/9/10/12/14/16/17/22/36 共 12 种取值，
同一层级控件在不同面板里半径都不同。这里锁死「只用 token 档位」。
"""
import os
import re

from agentfloat.ui.tokens import ALLOWED_FONTS, ALLOWED_RADII, FONT, RADIUS, SPACE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "agentfloat")

RADIUS_RE = re.compile(r"border-radius:\s*(\d+)px")
FONT_RE = re.compile(r"font-size:\s*(\d+)px")


def _iter_style_files():
    for base, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(base, fn)


def test_tokens_scale_is_sane():
    assert RADIUS.bar < RADIUS.sm < RADIUS.md < RADIUS.lg < RADIUS.xl < RADIUS.pill
    assert FONT.micro < FONT.caption < FONT.body < FONT.title < FONT.display < FONT.hero
    assert SPACE.xxs < SPACE.xs < SPACE.sm < SPACE.md < SPACE.lg


def test_no_stray_border_radius_values():
    """所有样式表圆角必须落在 token 档位内"""
    bad = []
    for path in _iter_style_files():
        text = open(path, encoding="utf-8").read()
        for m in RADIUS_RE.finditer(text):
            value = int(m.group(1))
            if value not in ALLOWED_RADII:
                line = text[:m.start()].count("\n") + 1
                bad.append("%s:%d → %dpx" % (os.path.relpath(path, ROOT), line, value))
    assert not bad, "圆角超出 token 档位（请用 ui.tokens.RADIUS）: %s" % bad


def test_no_stray_font_size_values():
    """样式表字号必须落在 token 档位内（0 用于隐藏文本）"""
    bad = []
    for path in _iter_style_files():
        text = open(path, encoding="utf-8").read()
        for m in FONT_RE.finditer(text):
            value = int(m.group(1))
            if value not in ALLOWED_FONTS:
                line = text[:m.start()].count("\n") + 1
                bad.append("%s:%d → %dpx" % (os.path.relpath(path, ROOT), line, value))
    assert not bad, "字号超出 token 档位（请用 ui.tokens.FONT）: %s" % bad


def test_panel_style_uses_tokens():
    """共享面板样式必须走 token，而不是写死数值"""
    from agentfloat.ui import panel_style
    css = panel_style.panel_css("dark") + panel_style.panel_css("light")
    assert "%dpx" % RADIUS.xl in css
    assert "%dpx" % RADIUS.sm in css
    assert "%dpx" % FONT.body in css
    for value in RADIUS_RE.findall(css):
        assert int(value) in ALLOWED_RADII, "panel_css 出现非 token 圆角 %s" % value


def test_panel_style_radii_match_tokens_exactly():
    """回归：面板窗口 16 / 控件 8 / 列表容器 10"""
    from agentfloat.ui import panel_style
    css = panel_style.panel_css("light")
    assert "QDialog { background: qlineargradient" in css and "border-radius: 16px" in css
    assert "border-radius: 8px; padding: 6px 13px" in css      # 按钮
    assert "border-radius: 10px; padding: 5px" in css          # 列表容器
