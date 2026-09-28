# -*- coding: utf-8 -*-
"""services/webagent.py 测试：web 规格解析 / 列表过滤 / 端口状态（PATCH 3.1.0）"""
import socket

from agentfloat.services import webagent


def _agent(**over):
    a = {
        "id": "x", "name": "X", "launcher": "web",
        "web": {"command": ["x", "serve", "--port", "4567"], "port": 4567,
                "url": "http://127.0.0.1:4567", "log_prefix": "x"},
    }
    a.update(over)
    return a


def test_web_spec_parsing():
    spec = webagent.web_spec(_agent())
    assert spec["port"] == 4567
    assert spec["command"] == ["x", "serve", "--port", "4567"]
    assert spec["url"] == "http://127.0.0.1:4567"


def test_web_spec_invalid():
    assert webagent.web_spec({"id": "a"}) is None
    assert webagent.web_spec({"id": "a", "web": None}) is None
    assert webagent.web_spec({"id": "a", "web": {"command": []}}) is None
    assert webagent.web_spec({"id": "a", "web": {"command": ["x"], "port": "abc"}}) is None


def test_list_web_agents_filters():
    agents = [
        _agent(),
        {"id": "t", "command": "t", "launcher": "terminal"},
        {"id": "w", "command": "w", "launcher": "web"},          # 无规格 → 不算
    ]
    out = webagent.list_web_agents(agents)
    assert len(out) == 1 and out[0][0]["id"] == "x"


def test_status_running_and_stopped():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    live_port = srv.getsockname()[1]
    other = socket.socket()
    other.bind(("127.0.0.1", 0))
    free_port = other.getsockname()[1]
    other.close()
    try:
        st = webagent.status(_agent(web={"command": ["x"], "port": live_port,
                                        "url": "", "log_prefix": "x"}))
        assert st["running"] is True and st["port"] == live_port
        st2 = webagent.status(_agent(web={"command": ["x"], "port": free_port,
                                          "url": "", "log_prefix": "x"}))
        assert st2["running"] is False
    finally:
        srv.close()


def test_port_open_false_for_closed_port():
    assert webagent._port_open(1) is False
