# -*- coding: utf-8 -*-
"""AgentFloat — 空态 / 加载态 / 错误态统一（v3.8.0）

改造前各面板各写一套：「暂无剪贴板记录」「没有正在进行的 Agent 进程」
「未找到匹配的 skill」「还没有保存的密钥」——同一类状态四种说法，
字号/颜色也各写各的。

本模块提供统一文案前缀与样式片段：

    from agentfloat.ui import states
    label.setText(states.empty("运行中的 Agent 进程", "启动任意 Agent 后会在这里显示"))
    label.setStyleSheet(states.css("dark"))
"""
from agentfloat.core.theme import get_colors
from agentfloat.ui.tokens import FONT, RADIUS, SPACE

EMPTY_PREFIX = "暂无"
LOADING_PREFIX = "正在"
ERROR_SUFFIX = "失败"


def empty(what, hint=""):
    """空态：`暂无<what>`（+ 可选第二行引导）"""
    text = "%s%s" % (EMPTY_PREFIX, what)
    return "%s\n%s" % (text, hint) if hint else text


def loading(what, hint=""):
    """加载态：`正在<what>…`"""
    text = "%s%s…" % (LOADING_PREFIX, what)
    return "%s\n%s" % (text, hint) if hint else text


def error(what, hint="可稍后重试"):
    """错误态：`<what>失败`（+ 引导；默认提示可重试）"""
    text = "%s%s" % (what, ERROR_SUFFIX)
    return "%s\n%s" % (text, hint) if hint else text


def css(theme="light"):
    """三种状态共用的样式片段（挂在 objectName 为 state/stateHint 的控件上）"""
    c = get_colors(theme)
    hint = "#%02X%02X%02X" % tuple(c["HINT"])
    text = "#%02X%02X%02X" % tuple(c["TEXT"])
    warn = "#FF9F0A" if theme == "dark" else "#C77700"
    return (
        "QLabel#state { color: %(tx)s; font-size: %(f)dpx; padding: %(p)dpx %(p)dpx; }"
        "QLabel#stateHint { color: %(hi)s; font-size: %(fc)dpx; padding: 0px %(p)dpx %(p)dpx %(p)dpx; }"
        "QLabel#stateError { color: %(warn)s; font-size: %(f)dpx; padding: %(p)dpx; }"
        "QFrame#stateCard { background: transparent; border: 1px dashed %(hi)s;"
        " border-radius: %(r)dpx; }"
        % {"tx": text, "hi": hint, "warn": warn, "f": FONT.body, "fc": FONT.caption,
           "p": SPACE.md, "r": RADIUS.md}
    )
