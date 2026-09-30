# -*- coding: utf-8 -*-
"""v3.6.2 启动动画 / 音效 / 共用球体渲染 测试"""

import random
import struct

import pytest


# ── 音效合成 ──────────────────────────────────────────────
def test_chime_wav_header_and_length():
    from agentfloat.ui import chime
    data = chime.make_wav(0.6)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE" and data[12:16] == b"fmt "
    assert struct.unpack("<I", data[4:8])[0] + 8 == len(data)
    audio_format, channels = struct.unpack("<HH", data[20:24])
    sample_rate = struct.unpack("<I", data[24:28])[0]
    bits = struct.unpack("<H", data[34:36])[0]
    assert audio_format == 1 and channels == 1 and bits == 16
    assert sample_rate == chime.SAMPLE_RATE
    data_size = struct.unpack("<I", data[40:44])[0]
    assert len(data) == 44 + data_size
    seconds = data_size / (sample_rate * channels * bits // 8)
    assert abs(seconds - chime.TOTAL_SECONDS) < 0.02


def test_chime_volume_scaling_and_cache():
    from agentfloat.ui import chime
    loud = chime.make_wav(1.0)
    quiet = chime.make_wav(0.2)
    assert loud != quiet
    # 最大振幅随音量缩放（且不削顶）
    def peak(wav):
        pcm = wav[44:]
        return max(abs(v) for (v,) in struct.iter_unpack("<h", pcm))
    assert peak(loud) > peak(quiet)
    assert peak(loud) <= 32767
    assert chime.make_wav(1.0) is loud          # 命中缓存
    assert chime.make_wav(-5) == chime.make_wav(0.0)   # 音量下限


def test_chime_play_never_raises(monkeypatch):
    from agentfloat.ui import chime
    called = {}

    def fake_play(data, flags):
        called["len"] = len(data)
        called["flags"] = flags

    import winsound
    monkeypatch.setattr(winsound, "PlaySound", fake_play)
    assert chime.play(0.5) is True
    assert called["len"] > 1000
    assert called["flags"] & winsound.SND_ASYNC


def test_chime_play_failure_is_silent(monkeypatch):
    from agentfloat.ui import chime

    def boom(*_a, **_k):
        raise RuntimeError("no audio device")

    import winsound
    monkeypatch.setattr(winsound, "PlaySound", boom)
    assert chime.play(0.5) is False


# ── 启动动画时间线（纯函数）────────────────────────────────
def test_intro_title_and_greeting():
    from agentfloat.ui.intro_animation import GREETINGS, intro_title, pick_greeting
    assert pick_greeting("自定义") == "自定义"
    assert pick_greeting("  ") in GREETINGS
    title = intro_title("3.6.2", "", random.Random(7))
    assert title.startswith("v3.6.2 · ") and len(title) > 9
    assert intro_title("3.6.2", "开工", random.Random(1)) == "v3.6.2 · 开工"


def test_timeline_phases():
    from agentfloat.ui import intro_animation as ia
    s0 = ia.timeline(0)
    assert s0["phase"] == "intro" and s0["overlay_a"] == 0 and s0["text_a"] == 0
    assert s0["ball_scale"] < 0.2                       # 从很小开始
    mid = ia.timeline(ia.POP_END)
    assert mid["ball_scale"] > 1.05                     # 回弹后比基准大
    assert mid["ring1"][1] > 0 or mid["ring1"][0] == 0.0
    late = ia.timeline(ia.TEXT_IN[1] + 100)
    assert late["text_a"] == 255 and late["text_dy"] == 0
    assert late["phase"] == "intro"


def test_timeline_fly_and_done():
    from agentfloat.ui import intro_animation as ia
    t_fly = 2200
    fly = ia.timeline(t_fly + ia.FLY_MS // 2, t_fly)
    assert fly["phase"] == "fly" and 0 < fly["fly_p"] < 1
    assert fly["ring1"] == (0.0, 0) and fly["sparkles"] == 0.0
    done = ia.timeline(t_fly + ia.FLY_MS + 1, t_fly)
    assert done["phase"] == "done"


def test_timeline_scale_monotonic_until_settle():
    from agentfloat.ui import intro_animation as ia
    scales = [ia.ball_scale_at(t) for t in range(0, ia.SETTLE_END, 20)]
    assert scales[-1] > scales[0]
    assert max(scales) <= 1.20 and min(scales) >= 0.14      # 回弹峰值约 1.17×，不夸张
    # 回弹：中途出现过冲（>1.12 的目标值）
    assert max(scales) > 1.12


def test_easing_helpers():
    from agentfloat.ui.intro_animation import ease_out_back, ease_out_cubic
    assert ease_out_back(0) == pytest.approx(0.0, abs=1e-6)
    assert ease_out_back(1) == pytest.approx(1.0, abs=1e-6)
    assert ease_out_back(0.5) > 1.0                      # 过冲
    assert ease_out_cubic(0) == 0.0 and ease_out_cubic(1) == 1.0
    assert 0 < ease_out_cubic(0.5) < 1


# ── 共用球体渲染 ──────────────────────────────────────────
def test_ball_render_pixmap(qapp):
    from PyQt5.QtGui import QColor
    from agentfloat.ui import ball_render
    pm = ball_render.render_ball_pixmap(120, QColor(10, 132, 255), hovered=False, dpr=1.0)
    assert not pm.isNull()
    assert pm.width() == pm.height()
    assert pm.width() == 120 + int(120 * 0.10) * 2


def test_floatball_uses_shared_renderer(qapp):
    """主浮球渲染委托给共用实现（保证与启动动画视觉一致）"""
    import inspect
    from agentfloat.ui import floatball
    src = inspect.getsource(floatball.FloatingWidget._render_ball_pixmap)
    assert "ball_render" in src


def test_intro_render_frame_paints(qapp):
    """离屏渲染能画出内容（球体/光环/星点），不同时刻画面不同"""
    from PyQt5.QtCore import QPointF, QRectF, QSize
    from agentfloat.ui.intro_animation import IntroAnimation
    intro = IntroAnimation(version="3.6.2", theme="dark", greeting="测试", sound=False)
    intro._big = 240.0
    intro._center = QPointF(300, 220)
    intro._target_size = 52.0
    intro._target_rect = QRectF(520, 400, 52, 52)
    intro._ready_ms = 2000
    early = intro.render_frame(1000, QSize(600, 480))
    late = intro.render_frame(2500, QSize(600, 480))
    assert not early.isNull() and not late.isNull()
    assert early.toImage() != late.toImage()          # 动画在变化
    # 球体附近有不透明像素（中心区域）
    img = early.toImage()
    center_alpha = img.pixelColor(300, 220).alpha()
    assert center_alpha > 200                          # 球体本体（深色玻璃）
    corner_alpha = img.pixelColor(4, 4).alpha()
    assert corner_alpha < 255                          # 边缘不是实心块


# ── 配置默认值 ────────────────────────────────────────────
def test_intro_defaults(tmp_path):
    import agentfloat.core.config as cfgmod
    old_path, old_old = cfgmod.CONFIG_PATH, cfgmod._OLD_CONFIG_PATH
    tmp = str(tmp_path / "config.json")
    try:
        cfgmod.CONFIG_PATH = tmp
        cfgmod._OLD_CONFIG_PATH = tmp + ".old"
        cfg = cfgmod.load_config()
        assert cfg["intro"]["enabled"] is True
        assert cfg["intro"]["sound"] is True
        assert 0 <= cfg["intro"]["volume"] <= 1
        assert cfg["intro"]["greeting"] == ""
    finally:
        cfgmod.CONFIG_PATH, cfgmod._OLD_CONFIG_PATH = old_path, old_old
