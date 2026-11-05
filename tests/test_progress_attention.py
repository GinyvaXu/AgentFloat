# -*- coding: utf-8 -*-
from agentfloat.services.progress.attention import new_attention


def test_attention_only_once_per_state():
    seen = set()
    a = {"sessionId": "a", "status": "need_input", "updatedAt": "t1"}
    assert [x["sessionId"] for x in new_attention([a], seen)] == ["a"]
    assert new_attention([a], seen) == []
    b = dict(a, updatedAt="t2")
    assert len(new_attention([b], seen)) == 1


def test_failed_and_running_filtered():
    seen = set()
    rows = [{"sessionId": "f", "status": "failed", "updatedAt": "t"},
            {"sessionId": "r", "status": "running", "updatedAt": "t"}]
    assert [x["sessionId"] for x in new_attention(rows, seen)] == ["f"]
