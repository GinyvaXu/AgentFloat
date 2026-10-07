# -*- coding: utf-8 -*-
"""v3.8.0 空态/加载态/错误态一致性测试

改造前同一类状态有四种说法：暂无 / 没有 / 未找到 / 还没有。
这里锁死统一前缀，并保证样式片段覆盖三种状态。
"""
import os
import re

from agentfloat.ui import states

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "agentfloat")
WEB = os.path.join(ROOT, "web", "js")

# 禁止再出现的旧写法（空态文案里）
LEGACY = re.compile(r"(没有正在进行的|未找到匹配的|还没有保存的|还没有监控端点)")


def test_state_text_format():
    assert states.empty("剪贴板记录") == "暂无剪贴板记录"
    assert states.empty("匹配的 Skill", "换个关键词") == "暂无匹配的 Skill\n换个关键词"
    assert states.loading("拉取用量") == "正在拉取用量…"
    assert states.error("检查更新") == "检查更新失败\n可稍后重试"
    assert states.error("检查更新", "") == "检查更新失败"


def test_state_css_covers_three_states():
    for theme in ("light", "dark"):
        css = states.css(theme)
        for sel in ("QLabel#state", "QLabel#stateHint", "QLabel#stateError",
                    "QFrame#stateCard"):
            assert sel in css, "%s 缺少 %s" % (theme, sel)


def test_no_legacy_empty_phrasing_in_source():
    bad = []
    for base, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(base, fn)
            if fn == "states.py":
                continue      # 该模块文档里刻意引用了改造前的旧写法作为对照
            text = open(p, encoding="utf-8").read()
            for m in LEGACY.finditer(text):
                line = text[:m.start()].count("\n") + 1
                bad.append("%s:%d → %s" % (os.path.relpath(p, ROOT), line, m.group(0)))
    assert not bad, "空态文案应统一为「暂无…」（见 ui/states.py）: %s" % bad


def test_no_legacy_empty_phrasing_in_web():
    text = open(os.path.join(WEB, "app.js"), encoding="utf-8").read()
    assert "还没有保存的密钥" not in text
    assert "还没有监控端点" not in text
    assert "暂无保存的密钥" in text and "暂无监控端点" in text


def test_process_panel_uses_shared_states():
    import inspect
    from agentfloat.ui import process_panel
    src = inspect.getsource(process_panel)
    assert "states.empty(" in src, "进程面板空态应走 ui.states"
    assert "没有正在进行的" not in src
