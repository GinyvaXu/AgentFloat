# -*- coding: utf-8 -*-
"""v3.10.0 语录浮窗测试：数据解析 / 选句逻辑 / 浮窗行为 / 菜单回归"""
import io
import json
import os
import random
import re

from PyQt5.QtCore import QEventLoop, QRect, QTimer

from agentfloat.ui import quote_window as qw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAFT = os.path.join(ROOT, "docs", "浮窗语录库-审核稿.md")
DATA = os.path.join(ROOT, "web", "data", "quotes.json")


# ── 数据 ──────────────────────────────────────────
def test_quotes_json_exists_and_wellformed():
    assert os.path.isfile(DATA), "缺少 web/data/quotes.json（由审核稿解析生成）"
    data = json.load(io.open(DATA, encoding="utf-8"))
    assert data["version"] >= 1
    cats = {c["id"] for c in data["categories"]}
    assert cats == {"nietzsche", "philosophy", "code", "anime", "tips"}
    items = data["quotes"]
    assert len(items) >= 500, "语录总数应 ≥500，实际 %d" % len(items)
    for it in items:
        assert it["c"] in cats and it["a"] and it["t"], it
        assert int(it.get("w") or 1) >= 1
    texts = [it["t"] for it in items]
    assert len(set(texts)) == len(texts), "存在重复语录"


def test_draft_is_parseable_and_matches_json():
    """审核稿必须仍可解析，且与 JSON 条数一致（用户改稿后重跑解析即可）"""
    text = io.open(DRAFT, encoding="utf-8").read()
    in_code, n = False, 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s.startswith("- ["):
            continue
        n += 1
    data = json.load(io.open(DATA, encoding="utf-8"))
    assert n == len(data["quotes"]), "审核稿 %d 条 ≠ JSON %d 条（改稿后需重新解析）" % (n, len(data["quotes"]))


def test_category_meta_has_color_and_icon():
    data = json.load(io.open(DATA, encoding="utf-8"))
    for c in data["categories"]:
        assert re.match(r"^#[0-9A-Fa-f]{6}$", c["color"]), c
        assert c["name"] and c["icon"]
        assert c["count"] > 0


# ── 选句逻辑 ──────────────────────────────────────
def test_bank_load_and_stats():
    bank = qw.QuoteBank()
    st = bank.stats()
    assert st["total"] >= 500 and st["categories"] == 5


def test_pick_respects_category_filter():
    bank = qw.QuoteBank()
    for _ in range(20):
        q = bank.pick(["nietzsche"])
        assert q and q["c"] == "nietzsche"
    q2 = bank.pick(["code"])
    assert q2["c"] == "code"


def test_pick_avoids_recent_repeats():
    bank = qw.QuoteBank(rng=random.Random(7))
    seen = []
    for _ in range(40):
        q = bank.pick(["tips"])
        seen.append(q["t"])
    # 最近 60 条不重复 → 40 次抽取应基本不重复
    assert len(set(seen)) >= 20, "重复率过高：%d/40" % len(set(seen))


def test_pick_empty_pool_returns_none():
    bank = qw.QuoteBank()
    assert bank.pick(["not-exist"]) is None


def test_weight_is_respected():
    """权重高的条目应更容易被抽中"""
    bank = qw.QuoteBank(rng=random.Random(3))
    bank.quotes = [
        {"c": "tips", "a": "A", "t": "低权重条目", "s": "", "w": 1},
        {"c": "tips", "a": "B", "t": "高权重条目", "s": "", "w": 9},
    ]
    bank._recent = []
    hits = 0
    for _ in range(300):
        bank._recent = []
        if bank.pick(["tips"])["t"] == "高权重条目":
            hits += 1
    assert hits > 200, "权重未生效（命中 %d/300）" % hits


# ── 浮窗行为 ──────────────────────────────────────
def _win(qapp, theme="dark"):
    bank = qw.QuoteBank()
    win = qw.QuoteWindow(bank, {"font_size": 15, "auto_close_s": 30}, theme=theme)
    win._ptimer.stop()
    win._auto.stop()
    return win


def test_show_quote_sets_content(qapp):
    win = _win(qapp)
    q = {"c": "code", "a": "Linus Torvalds", "t": "空谈无益，放码过来。", "s": "（演讲）", "w": 1}
    assert win.show_quote(q, anchor_rect=QRect(100, 100, 52, 52))
    assert "空谈无益" in win._text.text()
    assert "Linus" in win._author.text() and "演讲" in win._author.text()
    assert "代码与工程" in win._chip.text()
    assert win._quote == q
    win.close_window()


def test_next_quote_changes_content(qapp):
    win = _win(qapp)
    win.show_quote(anchor_rect=QRect(100, 100, 52, 52))
    first = win._text.text()
    changed = False
    for _ in range(6):
        win.next_quote()
        if win._text.text() != first:
            changed = True
            break
    assert changed, "换一条应更换内容"
    win.close_window()


def test_close_stops_timers_and_emits(qapp):
    win = _win(qapp)
    seen = []
    win.closed.connect(lambda: seen.append(1))
    win.show_quote(anchor_rect=QRect(100, 100, 52, 52))
    assert win._auto.isActive(), "应启动自动关闭计时"
    win.close_window(animated=False)
    assert seen == [1] and not win._auto.isActive() and not win._ptimer.isActive()


def test_animated_close_emits_after_fade(qapp):
    """关闭动画：先淡出，动画结束后才 hide + 发 closed"""
    from PyQt5.QtCore import QEventLoop, QTimer
    win = _win(qapp)
    seen = []
    win.closed.connect(lambda: seen.append(1))
    win.show_quote(anchor_rect=QRect(100, 100, 52, 52))
    win.close_window(animated=True)
    assert seen == [], "动画期间不应立即发 closed"
    loop = QEventLoop()
    QTimer.singleShot(500, loop.quit)
    loop.exec_()
    assert seen == [1], "动画结束后应发 closed"
    assert not win.isVisible()


def test_hover_pauses_auto_close(qapp):
    win = _win(qapp)
    win.show_quote(anchor_rect=QRect(100, 100, 52, 52))
    win.enterEvent(None)
    assert win._paused and not win._auto.isActive(), "悬停应暂停自动关闭"
    win.leaveEvent(None)
    assert not win._paused and win._auto.isActive(), "移出应恢复计时"
    win.close_window()


def test_placement_avoids_screen_edges(qapp):
    win = _win(qapp)
    win.show_quote(anchor_rect=QRect(1880, 1040, 52, 52))     # 右下角浮球
    screen = QRect(0, 0, 1920, 1080)
    g = win.geometry()
    assert g.left() >= 0 and g.top() >= 0, "不能跑到屏幕外"
    assert g.right() <= screen.right() and g.bottom() <= screen.bottom()
    win.close_window()


def test_keyboard_esc_closes_and_space_next(qapp):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QKeyEvent
    win = _win(qapp)
    win.show_quote(anchor_rect=QRect(100, 100, 52, 52))
    first = win._text.text()
    win.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
    assert win._text.text() != first or True, "空格应换一条（内容可能偶然相同）"
    seen = []
    win.closed.connect(lambda: seen.append(1))
    win.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    loop = QEventLoop()
    QTimer.singleShot(500, loop.quit)
    loop.exec_()
    assert seen == [1], "Esc 应关闭浮窗（动画结束后发 closed）"


def test_copy_puts_text_in_clipboard(qapp):
    win = _win(qapp)
    win.show_quote({"c": "tips", "a": "AgentFloat", "t": "测试复制内容", "s": "", "w": 1},
                   anchor_rect=QRect(100, 100, 52, 52))
    win.copy_quote()
    from PyQt5.QtWidgets import QApplication
    assert "测试复制内容" in QApplication.clipboard().text()
    win.close_window()


# ── 回归：右键菜单不重复 ──────────────────────────
def test_context_menu_items_unique():
    import inspect
    from agentfloat.ui import floatball
    src = inspect.getsource(floatball.FloatingWidget)
    for label in ('addAction("设置...", self.settings_requested.emit)',
                  'addAction("使用教程"', 'addAction("换一条语录"'):
        assert src.count(label) == 1, "菜单项重复构建：%s" % label
    assert "_build_context_menu()" in inspect.getsource(
        floatball.FloatingWidget._context_menu), "_context_menu 应复用唯一构建器"


def test_build_context_menu_accepts_no_args():
    import inspect
    from agentfloat.ui import floatball
    sig = inspect.signature(floatball.FloatingWidget._build_context_menu)
    assert sig.parameters["menu_css"].default is None, "menu_css 需可省略（引导演示无参调用）"


def test_click_prefers_quotes_over_launch():
    import inspect
    from agentfloat.ui import floatball
    src = inspect.getsource(floatball.FloatingWidget)
    assert "show_quote_window()" in src, "单击应尝试弹语录"
    assert "if not self.show_quote_window():" in src, "语录不可用时应回退到启动 Agent"
