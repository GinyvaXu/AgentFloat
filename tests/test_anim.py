# -*- coding: utf-8 -*-
"""动效与面板风格单测（PATCH 3.3.0）"""
import time


def test_panel_css_contains_new_style():
    from agentfloat.ui.panel_style import panel_css
    dark = panel_css("dark")
    light = panel_css("light")
    for css in (dark, light):
        assert "QDialog {" in css
        assert "qlineargradient" in css            # 玻璃渐变底
        assert "#0a84ff" in css and "#af52de" in css  # 品牌渐变
        assert "QScrollBar" in css
    assert dark != light


def test_fade_helpers_smoke(qapp):
    from PyQt5.QtWidgets import QDialog
    from agentfloat.ui.anim import fade_in, fade_out

    d = QDialog()
    d.setWindowOpacity(1.0)
    d.show()
    fade_in(d)
    deadline = time.time() + 0.5
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    done = []
    fade_out(d, duration=60)                       # 默认 on_done=hide
    deadline = time.time() + 1.0
    while time.time() < deadline and d.isVisible():
        qapp.processEvents()
        time.sleep(0.01)
    assert not d.isVisible(), "渐出结束后应隐藏"


def test_fade_panel_mixin_contract():
    from agentfloat.ui.panel_style import FadePanelMixin
    assert hasattr(FadePanelMixin, "showEvent")
    assert hasattr(FadePanelMixin, "closeEvent")
