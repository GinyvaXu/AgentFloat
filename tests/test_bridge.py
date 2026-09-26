# -*- coding: utf-8 -*-
"""WebBridge 测试：命令队列 / 事件推送与心跳 / 快照深拷贝隔离"""
from agentfloat.webshell.bridge import WebBridge


def test_command_queue_roundtrip():
    b = WebBridge()
    b.command("apply", {"config": {"a": 1}})
    assert b.drain_commands() == [("apply", {"config": {"a": 1}})]
    assert b.drain_commands() == []


def test_command_deepcopy_isolation():
    b = WebBridge()
    payload = {"x": [1]}
    b.command("k", payload)
    payload["x"].append(2)
    (kind, got), = b.drain_commands()
    assert kind == "k" and got == {"x": [1]}


def test_events_and_ping():
    b = WebBridge()
    b.publish("theme_changed", {"theme": "dark"})
    gen = b.iter_events(timeout=0.05)
    ev = next(gen)
    assert ev["event"] == "theme_changed"
    assert ev["payload"]["theme"] == "dark"
    assert "ts" in ev
    ping = next(gen)
    assert ping["event"] == "ping"


def test_snapshot_isolation():
    b = WebBridge()
    b.set_snapshot("k", {"v": 1})
    snap = b.get_snapshot("k")
    snap["v"] = 2
    assert b.get_snapshot("k")["v"] == 1
    allsnap = b.get_snapshot()
    assert "version" in allsnap and "api_results" in allsnap
