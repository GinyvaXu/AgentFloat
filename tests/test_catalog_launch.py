# -*- coding: utf-8 -*-
"""Agent 快捷启动单测（注入假 Popen，不真的打开控制台窗口）。"""
import os
import subprocess

from fastapi.testclient import TestClient

from agentfloat.services.catalog import installer
from agentfloat.services.catalog.builtin import BUILTIN_SPECS
from agentfloat.services.catalog.merge import merge_layers
from agentfloat.webshell.handlers import WebAppHandlers
from agentfloat.webshell.server import create_app, set_token


class FakeProc:
    def __init__(self, pid):
        self.pid = pid


class FakePopen:
    """记录调用参数的 Popen 替身。"""

    def __init__(self, pid=4321):
        self.pid = pid
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeProc(self.pid)


def make_spec(agent_id="gemini"):
    return merge_layers(BUILTIN_SPECS).get(agent_id)


def installed(source, path=""):
    return lambda spec, base=None: {"installed": True, "source": source, "path": path}


def test_not_installed_skips_popen(tmp_path, monkeypatch):
    fake = FakePopen()
    monkeypatch.setattr(installer, "detect",
                        lambda spec, base=None: {"installed": False, "source": "", "path": ""})
    result = installer.launch(make_spec(), base=str(tmp_path), popen=fake)
    assert result == {"ok": False, "reason": "not-installed"}
    assert fake.calls == []


def test_installed_managed_launches_new_console(tmp_path, monkeypatch):
    fake = FakePopen(pid=4321)
    monkeypatch.setattr(installer, "detect", installed("managed", "ignored"))
    spec = make_spec()
    base = str(tmp_path)
    result = installer.launch(spec, base=base, popen=fake)
    expected = installer.bin_path(spec, installer.managed_prefix(spec, base))
    assert result == {"ok": True, "pid": 4321, "exe": expected, "method": "managed"}
    assert len(fake.calls) == 1
    args, kwargs = fake.calls[0]
    if os.name == "nt":
        assert args[0] == 'cmd.exe /k "%s"' % expected
        assert kwargs.get("creationflags") == getattr(
            subprocess, "CREATE_NEW_CONSOLE", installer.CREATE_NEW_CONSOLE)
    else:
        assert args[0] == [expected]


def test_installed_path_uses_resolved_path(monkeypatch):
    fake = FakePopen(pid=7)
    monkeypatch.setattr(installer, "detect", installed("path", r"C:\tools\opencode.cmd"))
    result = installer.launch(make_spec("opencode"), popen=fake)
    assert result == {"ok": True, "pid": 7, "exe": r"C:\tools\opencode.cmd", "method": "path"}
    assert len(fake.calls) == 1


def test_spawn_failure_is_returned_not_raised(monkeypatch):
    monkeypatch.setattr(installer, "detect", installed("path", "opencode"))

    def boom(*args, **kwargs):
        raise OSError("拒绝访问")

    result = installer.launch(make_spec("opencode"), popen=boom)
    assert result["ok"] is False
    assert "拒绝访问" in result["reason"]


def test_unknown_agent_handler_returns_unknown_agent():
    handler = WebAppHandlers(None, None)
    assert handler.catalog_launch("not-in-catalog") == {"ok": False, "reason": "unknown-agent"}
    assert handler.catalog_launch("") == {"ok": False, "reason": "unknown-agent"}


def test_launch_route_wiring():
    set_token("")
    client = TestClient(create_app(None, WebAppHandlers(None, None)))
    try:
        r = client.post("/api/catalog/launch", json={"id": "not-in-catalog"})
        assert r.status_code == 200
        assert r.json() == {"ok": False, "reason": "unknown-agent"}
    finally:
        client.close()
