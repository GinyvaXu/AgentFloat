# -*- coding: utf-8 -*-
"""Web 壳适配层测试：WebAppHandlers 状态聚合 / 配置读写 / 新闻状态 / 打开链接"""
from agentfloat.webshell.bridge import WebBridge


class FakeWidget:
    def __init__(self):
        self.theme = "dark"
        self.config = {"api_monitor": {"enabled": True, "endpoints": []}, "news": None}
        self._news_generating = False
        self._news_cfg = None


def test_handlers_app_state():
    from agentfloat.webshell.handlers import WebAppHandlers
    b = WebBridge()
    b.set_snapshot("api_results", [{"ok": True}])
    h = WebAppHandlers(FakeWidget(), b)
    st = h.get_app_state()
    assert st["version"]
    assert st["theme"] == "dark"
    assert st["api_enabled"] is True
    assert st["dsh_running"] in (True, False)

    api = h.get_api_state()
    assert api["results"] == [{"ok": True}]
    assert api["config"]["enabled"] is True


def test_handlers_config_io(tmp_path, monkeypatch):
    from agentfloat.core import config as cfgmod
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", str(tmp_path / "config.json"))
    from agentfloat.webshell.handlers import WebAppHandlers
    h = WebAppHandlers(FakeWidget(), WebBridge())
    cfg = h.get_config()
    assert isinstance(cfg, dict) and cfg["agents"]
    cfg["theme"] = "light"
    h.save_config(cfg)
    assert (tmp_path / "config.json").exists()


def test_handlers_news_state(tmp_path, monkeypatch):
    from agentfloat.services.news import fetcher as nf
    monkeypatch.setattr(nf, "news_storage_dir", lambda: str(tmp_path))
    from agentfloat.webshell.handlers import WebAppHandlers
    h = WebAppHandlers(FakeWidget(), WebBridge())
    st = h.get_news_state(None)
    assert st["report"] is None
    assert st["generating"] is False
    assert isinstance(st["cfg"], dict)


def test_handlers_open_url(monkeypatch):
    from agentfloat.webshell import handlers as hd
    opened = []
    monkeypatch.setattr(hd, "_open_url", lambda u: opened.append(u))
    h = hd.WebAppHandlers(FakeWidget(), WebBridge())
    h.open_url("https://example.com/x")
    assert opened == ["https://example.com/x"]
