# -*- coding: utf-8 -*-
"""菜单样式单源（v3.14.0）

此前浮球右键菜单（`floatball._build_context_menu`）与托盘菜单（`app.py`）各存一份
同样的 QMenu 样式表，已经开始漂移。这里用令牌统一生成，两处共用。
"""
from agentfloat.core.theme import get_colors
from agentfloat.ui.tokens import FONT, RADIUS, SPACE


def menu_qss(theme="light"):
    """QMenu 样式表（深浅主题自适应；与原观感一致，值改用令牌表达）"""
    c = get_colors(theme)
    sfc, txt, acc, sep = c["SURFACE"], c["TEXT"], c["ACCENT"], c["SEPARATOR"]
    border = "rgba(255,255,255,0.12)" if theme == "dark" else "rgba(0,0,0,0.10)"
    return (
        "QMenu { background: rgba(%d,%d,%d,0.95); border: 1px solid %s;"
        " border-radius: %dpx; padding: %dpx 0; }"
        "QMenu::item { padding: %dpx %dpx %dpx %dpx; font-size: %dpx;"
        " color: #%02X%02X%02X; }"
        "QMenu::item:selected { background: #%02X%02X%02X; color: #FFF;"
        " border-radius: %dpx; margin: 1px 6px; }"
        "QMenu::separator { height: 1px; background: #%02X%02X%02X;"
        " margin: %dpx %dpx; }"
        % (sfc[0], sfc[1], sfc[2], border, RADIUS.md, SPACE.xs,
           SPACE.sm - 1, SPACE.lg * 2, SPACE.sm - 1, SPACE.lg, FONT.body,
           txt[0], txt[1], txt[2],
           acc[0], acc[1], acc[2], RADIUS.bar,
           sep[0], sep[1], sep[2], SPACE.xs, SPACE.sm)
    )
