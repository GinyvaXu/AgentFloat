# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone

from agentfloat.ui.progress_radar import (content_signature, current_step,
                                          display_name, qualifies, row_text,
                                          sort_key, step_counts)


def _task(**kw):
    base = {"sessionId": "s", "project": "P", "title": "T", "status": "running",
            "steps": [], "currentStepId": "s1", "eta": {"etaText": "~10–15m"},
            "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": ""}
    base.update(kw)
    return base


def test_qualifies_rules():
    now = datetime.now(timezone.utc)
    assert qualifies(_task(steps=[{"id": "s1", "status": "running"}] * 3), now) is False
    assert qualifies(_task(steps=[]), now) is False
    old = (now - timedelta(minutes=3)).isoformat()
    assert qualifies(_task(steps=[{"id": "s1"}], createdAt=old), now) is True
    assert qualifies(_task(steps=[{"id": "s1"}] * 3, createdAt=old), now) is True
    assert qualifies(_task(status="need_input", steps=[]), now) is True
    assert qualifies(_task(status="failed", steps=[]), now) is True
    assert qualifies(_task(status="done", steps=[]), now) is False


def test_row_text_and_counts():
    data = _task(steps=[{"id": "s1", "title": "设计", "status": "done"},
                        {"id": "s2", "title": "实现", "status": "running"},
                        {"id": "s3", "title": "验证", "status": "pending"}],
                 currentStepId="s2")
    assert step_counts(data) == (1, 3)
    assert current_step(data)["title"] == "实现"
    top, detail = row_text(data)
    assert "T" in top and "1/3" in detail and "实现" in detail


def test_sort_need_input_first():
    a = _task(sessionId="a", status="running", updatedAt="2026-01-01")
    b = _task(sessionId="b", status="need_input", updatedAt="2026-01-02")
    c = _task(sessionId="c", status="failed", updatedAt="2026-01-03")
    assert [x["sessionId"] for x in sorted([a, b, c], key=sort_key)] == ["b", "c", "a"]
    assert display_name(b) == "T"


def test_content_signature_stable_and_changes():
    a = _task(sessionId="a", updatedAt="2026-01-01")
    sig1 = content_signature([a], "")
    assert sig1 == content_signature([a], "")
    assert sig1 != content_signature([a], "a")
    a2 = dict(a, updatedAt="2026-01-02")
    assert sig1 != content_signature([a2], "")

