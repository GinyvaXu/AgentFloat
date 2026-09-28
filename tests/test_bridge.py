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


# ── PATCH 3.1.1：同步等待（保存设置时避免异步 apply 回读旧配置）──

def test_command_wait_roundtrip():
    import threading
    import time
    b = WebBridge()
    got = {}

    def fake_qt_thread():
        deadline = time.time() + 2
        while time.time() < deadline:
            cmds = b.drain_commands()
            if cmds:
                kind, payload = cmds[0]
                got["kind"] = kind
                got["token"] = payload.get("_wait_token")
                b.resolve_wait(payload.get("_wait_token"))
                return
            time.sleep(0.01)

    threading.Thread(target=fake_qt_thread, daemon=True).start()
    assert b.command_wait("apply", {"config": {"a": 1}}, timeout=2) is True
    assert got["kind"] == "apply" and got["token"]


def test_command_wait_timeout():
    b = WebBridge()
    assert b.command_wait("apply", {"config": {}}, timeout=0.2) is False


def test_resolve_wait_unknown_token_is_noop():
    WebBridge().resolve_wait("nope")   # 不应抛异常
