# -*- coding: utf-8 -*-
"""启动偏好（窗口/后台 + 工作区）与 launch 参数单测；不写真实配置、不弹窗口。"""
import os

from fastapi.testclient import TestClient

from agentfloat.services.catalog import installer, prefs
from agentfloat.services.catalog.builtin import BUILTIN_SPECS
from agentfloat.services.catalog.merge import merge_layers
from agentfloat.webshell.handlers import WebAppHandlers
from agentfloat.webshell.server import create_app, set_token


def spec(agent_id="gemini"):
    return merge_layers(BUILTIN_SPECS).get(agent_id)


class FakeProc:
    def __init__(self, pid=99):
        self.pid = pid


class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeProc()


def installed(spec_obj, base=None):
    return {"installed": True, "source": "managed", "path": ""}


def test_get_pref_default_when_missing():
    cfg = {}
    assert prefs.get_pref("gemini", config=cfg) == {"mode": "window", "workdir": ""}
    assert cfg == {}


def test_get_pref_reads_stored_and_ignores_bad_mode():
    cfg = {"catalog": {"launch": {"gemini": {"mode": "background", "workdir": r"C:\work"}}}}
    assert prefs.get_pref("gemini", config=cfg) == {"mode": "background", "workdir": r"C:\work"}

    cfg["catalog"]["launch"]["gemini"] = {"mode": "hacked", "workdir": ""}
    assert prefs.get_pref("gemini", config=cfg)["mode"] == "window"


def test_set_pref_persists_and_returns_pref(tmp_path):
    cfg = {}
    saved = []
    original_load, original_save = prefs.load_config, prefs.save_config
    try:
        prefs.load_config = lambda: cfg
        prefs.save_config = lambda c: saved.append(c)
        got = prefs.set_pref("gemini", "background", str(tmp_path))
    finally:
        prefs.load_config, prefs.save_config = original_load, original_save

    assert got["ok"] is True
    assert got["pref"] == {"mode": "background", "workdir": str(tmp_path)}
    assert cfg["catalog"]["launch"]["gemini"]["mode"] == "background"
    assert saved and saved[0] is cfg


def test_set_pref_rejects_bad_input(tmp_path):
    saved = []
    original_save = prefs.save_config
    try:
        prefs.save_config = lambda c: saved.append(c)
        assert prefs.set_pref("", "window", "", config={})["ok"] is False
        assert prefs.set_pref("gemini", "terminal", "", config={})["ok"] is False
        missing = str(tmp_path / "not-here")
        got = prefs.set_pref("gemini", "window", missing, config={})
        assert got["ok"] is False and "不存在" in got["error"]
    finally:
        prefs.save_config = original_save
    assert saved == []


def test_set_pref_allows_empty_workdir():
    saved = []
    original_save = prefs.save_config
    try:
        prefs.save_config = lambda c: saved.append(c)
        got = prefs.set_pref("gemini", "window", "  ", config={})
    finally:
        prefs.save_config = original_save
    assert got["ok"] is True
    assert got["pref"]["workdir"] == ""
    assert saved


def test_launch_background_passes_mode_and_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "detect", installed)
    fake = FakePopen()
    result = installer.launch(spec(), base=str(tmp_path), popen=fake,
                              mode="background", workdir=str(tmp_path))
    assert result["ok"] is True
    assert result["method"] == "managed"
    assert "warning" not in result
    args, kwargs = fake.calls[0]
    assert kwargs["cwd"] == str(tmp_path)
    if os.name == "nt":
        assert args[0] == 'cmd.exe /c "%s"' % result["exe"]
        assert kwargs["creationflags"] == installer.CREATE_NO_WINDOW
    else:
        assert args[0] == [result["exe"]]


def test_launch_window_defaults_to_home(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "detect", installed)
    fake = FakePopen()
    result = installer.launch(spec(), base=str(tmp_path), popen=fake)
    assert result["ok"] is True
    _args, kwargs = fake.calls[0]
    assert kwargs["cwd"] == os.path.expanduser("~")
    if os.name == "nt":
        assert kwargs["creationflags"] == installer.CREATE_NEW_CONSOLE


def test_launch_missing_workdir_falls_back_with_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "detect", installed)
    fake = FakePopen()
    missing = str(tmp_path / "gone")
    result = installer.launch(spec(), base=str(tmp_path), popen=fake,
                              mode="window", workdir=missing)
    assert result["ok"] is True
    assert "warning" in result and missing in result["warning"]
    _args, kwargs = fake.calls[0]
    assert kwargs["cwd"] == os.path.expanduser("~")


def test_launch_rejects_unknown_mode(monkeypatch):
    monkeypatch.setattr(installer, "detect", installed)
    fake = FakePopen()
    result = installer.launch(spec(), popen=fake, mode="terminal")
    assert result["ok"] is False and "invalid-mode" in result["reason"]
    assert fake.calls == []


class _Widget:
    def __init__(self):
        self.config = {"theme": "light"}


def test_prefs_routes_read_write_without_touching_real_config(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(prefs, "save_config", lambda cfg: saved.append(cfg))
    set_token("")
    handler = WebAppHandlers(_Widget(), None)
    client = TestClient(create_app(None, handler))
    try:
        got = client.get("/api/catalog/prefs", params={"id": "gemini"}).json()
        assert got == {"ok": True, "id": "gemini",
                       "pref": {"mode": "window", "workdir": ""}}

        post = client.post("/api/catalog/prefs",
                           json={"id": "gemini", "mode": "background",
                                 "workdir": str(tmp_path)}).json()
        assert post["ok"] is True
        assert post["pref"]["mode"] == "background"
        assert handler.widget.config["catalog"]["launch"]["gemini"]["workdir"] == str(tmp_path)
        assert saved

        again = client.get("/api/catalog/prefs", params={"id": "gemini"}).json()
        assert again["pref"]["mode"] == "background"

        bad = client.post("/api/catalog/prefs",
                          json={"id": "gemini", "mode": "nope", "workdir": ""}).json()
        assert bad["ok"] is False

        unknown = client.get("/api/catalog/prefs", params={"id": "missing"}).json()
        assert unknown["ok"] is False
    finally:
        client.close()
