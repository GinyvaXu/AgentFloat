# -*- coding: utf-8 -*-
import json

from datetime import datetime, timedelta, timezone

from agentfloat.services.progress import store
from agentfloat.ui.progress_cockpit import (fmt_duration, session_elapsed,
                                            sessions_signature, step_seconds)


def _iso(dt):
    return dt.isoformat()


def test_duration_helpers():
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    step = {"startedAt": _iso(now - timedelta(minutes=3)),
            "finishedAt": _iso(now)}
    assert int(step_seconds(step, now)) == 180
    running = {"startedAt": _iso(now - timedelta(seconds=45))}
    assert int(step_seconds(running, now)) == 45
    assert fmt_duration(45) == "45s"
    assert fmt_duration(180) == "3m"
    assert fmt_duration(3720) == "1h02m"


def test_session_elapsed_and_signature():
    now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    data = {"createdAt": _iso(now - timedelta(minutes=10)), "finishedAt": _iso(now)}
    assert int(session_elapsed(data, now)) == 600
    # 旧数据没有 finishedAt：终态回退 updatedAt，不再按当前时间持续增长
    legacy = {"createdAt": _iso(now - timedelta(minutes=10)),
              "updatedAt": _iso(now - timedelta(minutes=5)), "status": "done"}
    assert int(session_elapsed(legacy, now)) == 300
    a = {"sessionId": "a", "status": "running", "updatedAt": "x"}
    assert sessions_signature([a]) == sessions_signature([dict(a)])
    assert sessions_signature([a]) != sessions_signature([dict(a, status="done")])


def test_session_elapsed_uses_store_finished_at(tmp_path, monkeypatch):
    """只走 store.update：done 后写完 finishedAt，「已用」在 5 小时后仍不涨。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    store.update("t", {"action": "plan", "steps": ["a"]})
    store.update("t", {"action": "step", "title": "a"})
    path = tmp_path / "t.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    started = datetime.now(timezone.utc) - timedelta(minutes=10)
    state["createdAt"] = started.isoformat()
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    done = store.update("t", {"action": "done"})
    assert done["finishedAt"]
    finished = datetime.fromisoformat(done["finishedAt"])
    assert abs(int(session_elapsed(done, finished + timedelta(hours=5))) - 600) <= 3


def test_cockpit_retry_does_not_add_step(tmp_path, monkeypatch, qapp):
    """驾驶舱「重试」复位原失败步骤（旧实现会追加「步骤 4」）。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    store.update("c1", {"action": "plan", "steps": ["a", "b", "c"]})
    store.update("c1", {"action": "step", "title": "a"})
    store.update("c1", {"action": "fail", "error": "x"})

    from agentfloat.ui.progress_cockpit import ProgressCockpit
    win = ProgressCockpit(theme="dark", session_id="c1")
    try:
        win._refresh(force=True)
        win._resume()
        data = store.load("c1")
        assert len(data["steps"]) == 3, data["steps"]
        assert [s["title"] for s in data["steps"]] == ["a", "b", "c"]
        assert data["steps"][0]["status"] == "running"
        assert data["status"] == "running"
    finally:
        win._timer.stop()
        win._replay_timer.stop()
        win.hide()
        win.deleteLater()


def test_cockpit_replay_is_not_interrupted_by_refresh(tmp_path, monkeypatch, qapp):
    """回放期间暂停 1.5s 刷新，否则 StepRow 重建会抹掉高亮。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    store.update("c2", {"action": "plan", "steps": ["a", "b", "c"]})

    from agentfloat.ui.progress_cockpit import ProgressCockpit
    win = ProgressCockpit(theme="dark", session_id="c2")
    try:
        win._refresh(force=True)
        win._replay()
        assert win._replaying is True
        assert win._timer.isActive() is False
        win._refresh()                       # 定时刷新：回放中直接跳过
        assert win._replaying is True and win._timer.isActive() is False
        for _ in range(5):
            win._replay_next()
        assert win._replaying is False
        assert win._timer.isActive() is True
    finally:
        win._timer.stop()
        win._replay_timer.stop()
        win.hide()
        win.deleteLater()
