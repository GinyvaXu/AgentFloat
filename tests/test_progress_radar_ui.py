# -*- coding: utf-8 -*-
"""4.0 进度贴边条 / 快面板 UX 回归（offscreen）。"""
from datetime import datetime, timedelta

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QFrame, QPushButton, QScrollArea, QWidget

import agentfloat.ui.progress_radar as pr


class _FakeSettings(object):
    def __init__(self, initial=None):
        self.store = dict(initial or {})

    def value(self, key, default=None):
        return self.store.get(key, default)

    def setValue(self, key, value):
        self.store[key] = value

    def remove(self, key):
        self.store.pop(key, None)


def _session(sid="s0", status="need_input", n_steps=3, updated=None,
             question="确认？", window=""):
    now = datetime.now().astimezone()
    updated = updated or (now - timedelta(minutes=1)).isoformat()
    steps = [{"id": "s%d" % (i + 1), "title": "步骤 %d" % (i + 1),
              "status": "done" if i == 0 else "pending"} for i in range(n_steps)]
    return {"sessionId": sid, "project": "P", "title": "任务 " + sid, "status": status,
            "steps": steps, "currentStepId": "",
            "question": question if status == "need_input" else "",
            "error": "boom" if status == "failed" else "",
            "window": window, "createdAt": (now - timedelta(minutes=10)).isoformat(),
            "updatedAt": updated,
            "eta": {"etaText": "~5m"}}


def _make(qapp, monkeypatch, sessions, theme="dark", settings=None):
    fake = settings or _FakeSettings()
    monkeypatch.setattr(pr, "QSettings", lambda *_a, **_k: fake)
    monkeypatch.setattr(pr.store, "list_sessions", lambda: list(sessions))
    anchor = QWidget()
    anchor.resize(52, 52)
    anchor.move(300, 260)
    anchor.show()
    radar = pr.ProgressRadar(anchor, theme=theme)
    radar._anchor_widget = anchor
    return radar, fake


def _close(radar):
    radar._timer.stop()
    radar._place_timer.stop()
    radar._hide_timer.stop()
    radar._panel.hide()
    radar.hide()
    radar._tab.hide()
    radar._anchor_widget.hide()
    radar.deleteLater()


def test_dismiss_persists_and_tick_does_not_undo(qapp, monkeypatch, tmp_path):
    """P1-2：没有 ×；Esc/关闭路径持久化后不被 1.2s tick 撤销，内容变化才重现。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    sessions = [_session("s0")]
    radar, fake = _make(qapp, monkeypatch, sessions)
    try:
        radar._panel_open = True
        radar._tick()
        assert radar.isVisible()
        assert not [b for b in radar.findChildren(QPushButton) if b.text() == "×"], \
            "设计约定：面板不提供 ×，关闭只走 Esc 与设置开关"
        radar._dismiss()
        assert radar.isVisible() is False
        assert radar._tab.isVisible() is False
        assert fake.store.get("dismissed")

        radar._tick()                       # 下一次定时 tick 不得把条子拉回来
        assert radar._tab.isVisible() is False
        assert radar.isVisible() is False

        sessions[0] = _session("s0", question="新问题")
        radar._tick()                       # 内容变化 → 重新出现
        assert radar._tab.isVisible() is True
        assert "dismissed" not in fake.store

        # Esc（未展开时）走同一条关闭路径：持久化，且下一次 tick 不撤销
        radar.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert radar._tab.isVisible() is False
        assert fake.store.get("dismissed")
        radar._tick()
        assert radar._tab.isVisible() is False

        # 设置页重新开启进度条：清除 dismissed 后条子回来
        radar.reset_dismissed()
        radar._tick()
        assert radar._tab.isVisible() is True
    finally:
        _close(radar)


def test_restored_dismissed_does_not_open_empty_panel(qapp, monkeypatch, tmp_path):
    """P1-2：QSettings 恢复 dismissed 后点条展开，必须正常渲染而不是空面板。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    sessions = [_session("s0")]
    sig = pr.content_signature(sessions, "")
    radar, fake = _make(qapp, monkeypatch, sessions,
                        settings=_FakeSettings({"dismissed": sig}))
    try:
        assert radar._dismiss_sig == sig
        radar._expand()
        assert radar._body.count() > 0, "展开后必须有内容"
        assert radar.isVisible()
        assert radar._dismiss_sig == ""
        assert "dismissed" not in fake.store
    finally:
        _close(radar)


def test_expand_animates_without_recentering(qapp, monkeypatch, tmp_path):
    """展开用高度动画，且保持顶边不动（不再强制垂直居中导致跳窗）。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    from PyQt5.QtTest import QTest

    radar, _fake = _make(qapp, monkeypatch, [_session("s0")])
    try:
        radar._panel_open = True
        radar._tick()
        radar.show()
        QTest.qWait(120)
        collapsed = radar.height()
        y_before = radar.y()

        radar._toggle("s0")
        QTest.qWait(60)
        mid = radar.height()
        QTest.qWait(400)
        final = radar.height()

        assert final > collapsed, (collapsed, final)
        assert collapsed <= mid <= final, (collapsed, mid, final)
        assert radar.y() == y_before, (y_before, radar.y())
    finally:
        _close(radar)


def test_detail_actions_are_one_primary_one_secondary_plus_more(qapp, monkeypatch, tmp_path):
    """P1-1：5 个按钮挤 238px → 1 主 + 1 次 + 「更多…」，复制/聚焦收进菜单。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    radar, _fake = _make(qapp, monkeypatch, [_session("s0")])
    try:
        data = _session("s0", status="failed", window="cmd.exe")
        radar._build_l1(data)
        box = radar.findChild(QFrame, "radarDetail")
        assert box is not None
        buttons = box.findChildren(QPushButton)
        texts = [b.text() for b in buttons]
        assert texts == ["重试", "驾驶舱", "更多…"], texts
        assert "复制 ID" not in texts and "聚焦" not in texts
        total = sum(b.sizeHint().width() for b in buttons) + 6 * (len(buttons) - 1)
        assert total <= pr.WIDTH - 20, total
        assert all(b.sizeHint().width() < 100 for b in buttons)
    finally:
        _close(radar)


def test_panel_height_clamped_and_steps_scroll(qapp, monkeypatch, tmp_path):
    """P1-3：4 任务 + 20 步不再 688px 出屏；明细区有滚动。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    sessions = [_session("s%d" % i, n_steps=20) for i in range(4)]
    radar, _fake = _make(qapp, monkeypatch, sessions)
    try:
        radar._panel_open = True
        radar._expanded = "s0"
        radar._tick()
        assert radar.height() <= radar._available_height()
        assert radar.height() < 688
        scrolls = radar.findChildren(QScrollArea)
        assert scrolls, "步骤明细区应为 QScrollArea"
        assert max(s.height() for s in scrolls) <= 160
    finally:
        _close(radar)


def test_light_theme_uses_black_overlays(qapp, monkeypatch, tmp_path):
    """P1-4：浅色主题下明细块/悬停/按钮描边不能白叠白。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    radar, _fake = _make(qapp, monkeypatch, [_session("s0")], theme="light")
    try:
        radar._build_l1(_session("s0", status="failed"))
        box = radar.findChild(QFrame, "radarDetail")
        assert "rgba(0,0,0,0.035)" in box.styleSheet()
        assert "rgba(255,255,255" not in box.styleSheet()
        assert "rgba(0,0,0,0.05)" in radar._action_style(False)
        assert "rgba(0,0,0,0.09)" in radar._action_style(False)

        radar._panel_open = True
        radar._tick()
        compact = next(b for b in radar.findChildren(QPushButton) if b.text() == "简略")
        assert "rgba(0,0,0,0.06)" in compact.styleSheet()
        assert "rgba(255,255,255" not in compact.styleSheet()
    finally:
        _close(radar)


def test_panel_background_is_opaque(qapp, monkeypatch, tmp_path):
    """回归：WA_TranslucentBackground 下 QFrame 必须真正画出面板底色。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    radar, _fake = _make(qapp, monkeypatch, [_session("s0")])
    try:
        radar._panel_open = True
        radar._tick()
        qapp.processEvents()
        image = radar._panel.grab().toImage()
        color = image.pixelColor(image.width() // 2, image.height() // 2)
        assert color.alpha() >= 200, "面板中心像素透明（回到旧 bug）"
    finally:
        _close(radar)


def test_seg_bar_six_segments_and_fill(qapp):
    seg = pr.SegBar("running", "dark")
    assert pr.SEGMENTS == 6
    seg.set_progress(0, 6)
    assert seg.fill_count() == 0
    seg.set_progress(2, 6)
    assert seg.fill_count() == 2
    seg.set_progress(6, 6)
    assert seg.fill_count() == 6
    seg.set_progress(99, 6)
    assert seg.fill_count() == 6


def test_tab_shows_dots_and_count(qapp, monkeypatch, tmp_path):
    """贴边条不再是 ⋮ + 数字，而是横排 ••• + 数量。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    sessions = [_session("s0"), _session("s1", status="running", question="")]
    radar, _fake = _make(qapp, monkeypatch, sessions)
    try:
        radar._tick()
        text = radar._tab.text()
        assert "•••" in text
        assert "2" in text
        assert "⋮" not in text
    finally:
        _close(radar)


def test_task_row_elides_long_title(qapp, monkeypatch, tmp_path):
    """长标题必须省略号截断，不能硬截断或撑破行宽。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    data = _session("s0")
    data["title"] = "非常长的任务标题" * 12
    radar, _fake = _make(qapp, monkeypatch, [data])
    try:
        radar._panel_open = True
        radar._tick()
        qapp.processEvents()
        row = radar.findChildren(pr.TaskRow)[0]
        label = row.findChildren(pr._ElideLabel)[0]
        assert label.full_text() == data["title"]
        assert label.text().endswith("…")
        assert len(label.text()) < len(data["title"])
    finally:
        _close(radar)


def test_rows_are_task_widgets_not_buttons(qapp, monkeypatch, tmp_path):
    """每行是 TaskRow：状态点 + 省略标题 + 分段进度，不再是整行文本按钮。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    radar, _fake = _make(qapp, monkeypatch, [_session("s0", n_steps=6)])
    try:
        radar._panel_open = True
        radar._tick()
        rows = radar.findChildren(pr.TaskRow)
        assert len(rows) == 1
        assert rows[0].findChild(pr.SegBar) is not None
        assert [b.text() for b in rows[0].findChildren(QPushButton)] == []
    finally:
        _close(radar)
