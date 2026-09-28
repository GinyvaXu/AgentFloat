# -*- coding: utf-8 -*-
"""Web 壳 FastAPI 路由测试（TestClient，无需真实网络/浏览器）"""
import pytest
from fastapi.testclient import TestClient

from agentfloat.webshell.bridge import WebBridge
from agentfloat.webshell.server import create_app


class FakeHandlers:
    version = "test"

    def __init__(self, skills_root=""):
        self.saved = []
        self.applied = []
        self.opened = []
        self.skills_root = skills_root

    def get_config(self):
        return {"theme": "light", "skills": {"roots": [self.skills_root] if self.skills_root else []}}

    def save_config(self, cfg):
        self.saved.append(cfg)

    def apply_config(self, cfg, changed_keys=None, timeout=3.0):
        """PATCH 3.1.1：同步应用并回读（测试替身：合并后返回）"""
        self.applied.append({"config": cfg, "changed_keys": changed_keys})
        merged = dict(self.get_config())
        merged.update(cfg)
        return merged

    def get_app_state(self):
        return {"version": "test", "theme": "light"}

    def get_api_state(self):
        return {"results": []}

    def get_news_state(self, date=None):
        return {"report": None, "dates": [], "date": date}

    def open_url(self, url):
        self.opened.append(url)


@pytest.fixture()
def client(tmp_path):
    root = tmp_path / "skills"
    d = root / "alpha-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: alpha-skill\ndescription: 示例。\n---\n",
                                encoding="utf-8")
    h = FakeHandlers(skills_root=str(root))
    b = WebBridge()
    app = create_app(b, h)
    c = TestClient(app)
    yield c, b, h
    c.close()


def test_health(client):
    c, b, h = client
    assert c.get("/api/health").json() == {"ok": True}


def test_config_get_and_put(client):
    c, b, h = client
    assert c.get("/api/config").json()["config"]["theme"] == "light"

    r = c.put("/api/config", json={"config": {"theme": "dark"}, "changed_keys": ["theme"]})
    body = r.json()
    assert body["ok"] is True
    assert body["config"]["theme"] == "dark", "PUT 应返回同步应用后的配置（PATCH 3.1.1）"
    assert h.saved == [{"theme": "dark"}]
    assert h.applied and h.applied[0]["changed_keys"] == ["theme"]


def test_config_put_invalid(client):
    c, b, h = client
    assert c.put("/api/config", json={"config": "nope"}).status_code == 400


def test_preview_route(client):
    c, b, h = client
    r = c.post("/api/preview", json={"config": {"theme": "dark"}})
    assert r.json() == {"ok": True}
    cmds = b.drain_commands()
    assert cmds == [("preview", {"config": {"theme": "dark"}})]


def test_state_news_and_skills(client):
    c, b, h = client
    assert c.get("/api/state").json()["version"] == "test"
    assert c.get("/api/news/state").json()["report"] is None

    skills = c.get("/api/skills").json()
    assert [s["name"] for s in skills["skills"]] == ["alpha-skill"]


def test_open_url_and_launch_agent(client):
    c, b, h = client
    c.post("/api/open_url", json={"url": "https://example.com/x"})
    assert h.opened == ["https://example.com/x"]

    c.post("/api/launch_agent", json={"id": "claude"})
    assert ("launch_agent", {"id": "claude"}) in b.drain_commands()


def test_check_update_dispatches(client):
    c, b, h = client
    c.post("/api/check_update")
    assert ("check_update", {}) in b.drain_commands()


def test_index_and_spa_fallback(client):
    c, b, h = client
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers.get("content-type", "")
    r2 = c.get("/some/hash/route")
    assert r2.status_code == 200
