# -*- coding: utf-8 -*-
"""AgentFloat — 视觉设计令牌（v3.8.0）

统一圆角 / 字号 / 间距，避免各面板各写一套（改造前圆角出现过 4/6/7/8/9/10/12/14/16/17/22/36
共 12 种取值，同一层级的控件在不同面板里半径都不一样）。

用法（Qt 样式表）::

    from agentfloat.ui.tokens import RADIUS, FONT, SPACE
    css = "QDialog { border-radius: %dpx; }" % RADIUS.lg
    css += "QPushButton { border-radius: %dpx; padding: %dpx %dpx; font-size: %dpx; }" % (
        RADIUS.sm, SPACE.xs + 2, SPACE.md, FONT.body)

动效时长请用 ``ui.motion.Tokens``（PANEL_IN_MS / PANEL_OUT_MS 等），本模块只管静态视觉。
"""


class RADIUS(object):
    """圆角：只有四档 + 胶囊 + 细条"""
    bar = 4        # 进度条 / 滚动条等细长元素
    sm = 8         # 按钮 / 输入框 / 列表项
    md = 10        # 列表容器 / 卡片
    lg = 14        # 面板窗口
    xl = 16        # 大面板窗口（panel_style 基座）
    pill = 999     # 胶囊：圆形头像、状态点、徽标


class FONT(object):
    """字号：micro(10) caption(11) body(12) title(14) display(17) hero(32)"""
    micro = 10
    caption = 11
    body = 12
    title = 14
    display = 17
    hero = 32


class SPACE(object):
    """间距：4 的倍数为主（xs/sm/md/lg），另有 2px 微调与 6px 过渡档"""
    xxs = 2
    xs = 4
    sm = 8
    md = 12
    lg = 16


# 允许出现在样式表里的圆角取值（供一致性测试兜底；新增档位请同步这里）
ALLOWED_RADII = frozenset([RADIUS.bar, RADIUS.sm, RADIUS.md, RADIUS.lg, RADIUS.xl,
                           RADIUS.pill])
# 允许的字号取值
ALLOWED_FONTS = frozenset([0, FONT.micro, FONT.caption, FONT.body, FONT.title,
                           FONT.display, FONT.hero])
