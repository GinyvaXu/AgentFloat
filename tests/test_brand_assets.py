# -*- coding: utf-8 -*-
"""v3.7.0 品牌图标 / 浮球图案 测试

覆盖：新品牌资源齐全且规格正确、浮球改用品牌渐变 + 白色旋涡 glyph、
资源缺失时矢量回退、掩码圆角与渲染实现同源、Web 控制台使用新图标。
"""
import os

from PyQt5.QtGui import QColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")


# ── 资源规格 ──────────────────────────────────────────────
def test_brand_icon_assets_present(qapp):
    from PyQt5.QtGui import QIcon, QImage
    ico = os.path.join(ASSETS, "agent_float_icon.ico")
    png = os.path.join(ASSETS, "agent_float_icon.png")
    swirl = os.path.join(ASSETS, "agent_float_swirl.png")
    for path in (ico, png, swirl):
        assert os.path.isfile(path), "缺少品牌资源: %s" % path

    sizes = sorted((s.width(), s.height()) for s in QIcon(ico).availableSizes())
    assert (16, 16) in sizes and (256, 256) in sizes, "ICO 需覆盖 16~256 多尺寸，实际 %s" % sizes

    icon = QImage(png)
    assert icon.width() == icon.height() >= 512
    # 施工单（docs/图标与浮窗更新-交接-2026-09-30.md）：agent_float_icon.png 用全出血方形母版
    assert icon.pixelColor(0, 0).alpha() == 255, "应用图标 PNG 应为全出血方形母版"
    assert icon.pixelColor(icon.width() // 2, icon.height() // 2).alpha() == 255


def test_swirl_glyph_is_white_on_transparent(qapp):
    from PyQt5.QtGui import QImage
    img = QImage(os.path.join(ASSETS, "agent_float_swirl.png"))
    assert not img.isNull() and img.hasAlphaChannel()
    assert img.pixelColor(0, 0).alpha() == 0, "旋涡四周应透明"

    def opaque(x, y):
        return img.pixelColor(x, y).alpha() > 200

    whites = 0
    min_x, min_y, max_x, max_y = img.width(), img.height(), 0, 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            if not opaque(x, y):
                continue
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
            r, g, b = (img.pixelColor(x, y).red(), img.pixelColor(x, y).green(),
                       img.pixelColor(x, y).blue())
            if min(r, g, b) > 240:
                whites += 1
    assert whites > 0, "旋涡应为白色"
    # glyph 占画布约 45%（与图标原稿同比例，居中）
    ratio = (max_x - min_x) / float(img.width())
    assert 0.40 < ratio < 0.52, "glyph 占比异常: %.2f" % ratio
    assert abs((min_x + max_x) / 2.0 - img.width() / 2.0) < 0.06 * img.width(), "glyph 应居中"


# ── 浮球渲染 ──────────────────────────────────────────────
def _sample(pm, size, fx, fy):
    """取球体内部相对坐标 (fx, fy ∈ 0..1) 的颜色"""
    off = int(round(size * 0.10))
    x = int(round(off + size * fx))
    y = int(round(off + size * fy))
    return pm.toImage().pixelColor(x, y)


def test_ball_uses_brand_gradient(qapp):
    from agentfloat.ui import ball_render
    size = 200
    pm = ball_render.render_ball_pixmap(size, QColor(10, 132, 255), hovered=False, dpr=1.0)
    start = _sample(pm, size, 0.16, 0.16)      # 左上：紫
    end = _sample(pm, size, 0.84, 0.84)        # 右下：蓝
    assert start.alpha() == 255 and end.alpha() == 255
    # 左上是紫（红>绿、蓝高），右下是蓝（绿 > 红）
    assert start.red() > start.green() and start.blue() > 150, "左上应为品牌紫"
    assert end.green() > end.red(), "右下应为品牌蓝"
    assert start.red() > end.red(), "渐变应从紫过渡到蓝"
    # 不再是旧版深色玻璃底
    assert start.red() + start.green() + start.blue() > 300


def test_ball_renders_white_swirl_glyph(qapp):
    from agentfloat.ui import ball_render
    size = 200
    pm = ball_render.render_ball_pixmap(size, QColor(10, 132, 255), hovered=False, dpr=1.0)
    img = pm.toImage()
    off = int(round(size * 0.10))
    cx = int(off + size / 2.0)
    found = False
    for dx in range(-22, 23, 2):
        for dy in range(-22, 23, 2):
            c = img.pixelColor(cx + dx, cx + dy)
            if c.alpha() > 200 and min(c.red(), c.green(), c.blue()) > 200:
                found = True
    assert found, "球体应绘制白色旋涡 glyph"


def test_ball_renderer_falls_back_to_vector(qapp, monkeypatch):
    """glyph 资源不可用时回退为矢量螺旋（渲染不崩、仍有白色图案）"""
    from agentfloat.ui import ball_render
    monkeypatch.setattr(ball_render, "_GLYPH_SOURCE", False, raising=True)
    monkeypatch.setattr(ball_render, "_GLYPH_SCALED", {}, raising=True)
    size = 200
    pm = ball_render.render_ball_pixmap(size, QColor(10, 132, 255), hovered=False, dpr=1.0)
    assert not pm.isNull()
    img = pm.toImage()
    off = int(round(size * 0.10))
    cx = int(off + size / 2.0)
    whites = 0
    for x in range(cx - 20, cx + 21, 2):
        for y in range(cx - 20, cx + 21, 2):
            c = img.pixelColor(x, y)
            if c.alpha() > 120 and min(c.red(), c.green(), c.blue()) > 180:
                whites += 1
    assert whites > 0, "矢量回退应画出白色螺旋"


def test_ball_radius_shared_between_mask_and_render():
    from agentfloat.ui import ball_render
    assert ball_render.ball_radius(100) == 100 * ball_render.BALL_RADIUS_RATIO
    assert ball_render.ball_radius(4) == 6.0          # 小尺寸下限

    import inspect
    from agentfloat.ui import floatball
    src = inspect.getsource(floatball.FloatingWidget._update_mask)
    assert "ball_radius" in src, "命中掩码需与渲染共用圆角，避免两份魔数"


def test_glyph_source_resolves_in_dev():
    from agentfloat.core.paths import SWIRL_PATH
    from agentfloat.ui import ball_render
    assert os.path.isfile(SWIRL_PATH), "随包应包含 glyph 资源"
    assert ball_render._glyph_source(), "开发模式下应能加载 glyph"


# ── Web 控制台 ────────────────────────────────────────────
def test_web_console_uses_brand_icon():
    index = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    css = open(os.path.join(ROOT, "web", "css", "style.css"), encoding="utf-8").read()
    assert "/icon.png" in index, "index.html 应使用新品牌图标作为 favicon"
    assert 'class="brand-dot" role="img"' in index
    assert "/icon.png" in css, "侧栏品牌块应使用新图标"
    assert os.path.isfile(os.path.join(ROOT, "web", "icon.png"))
