# -*- coding: utf-8 -*-
"""AI 接入 Web API 测试：CRUD / 激活 / 测试 / 余额汇总 / Token 统计

用 FastAPI TestClient + 假 handlers + monkeypatch HTTP，不依赖真实网络。
"""
import copy
import json

import pytest
from fastapi.testclient import TestClient

from agentfloat.services import llm
from agentfloat.webshell.bridge import WebBridge
from agentfloat.webshell.server import create_app


class LlmHandlers:
    """最小 handlers 替身：配置保存在内存里，apply_config 返回同一份配置。"""

    version = "test"

    def __init__(self, cfg):
        self.cfg = cfg
        self.saved = 0
        self.applied = []

    def get_config(self):
        return self.cfg

    def save_config(self, cfg):
        self.saved += 1
        self.cfg = copy.deepcopy(cfg)

    def apply_config(self, cfg, changed_keys=None, timeout=3.0):
        self.cfg = copy.deepcopy(cfg)
        self.applied.append(changed_keys)
        return self.cfg

    def get_app_state(self):
        return {"version": "test", "theme": "light"}

    def get_api_state(self):
        return {"results": []}

    def get_news_state(self, date=None):
        return {"report": None, "dates": [], "date": date}

    def open_url(self, url):
        pass


DEEPSEEK = {
    "name": "DeepSeek", "preset": "deepseek",
    "base_url": "https://api.deepseek.com/v1", "api_key": "sk-secret-1234",
    "model": "deepseek-chat", "kind": "money",
    "balance_url": "https://api.deepseek.com/user/balance",
    "balance_field": "balance_infos[0].total_balance", "currency": "CNY",
}


def fake_http(method, url, headers=None, body=None, timeout=30.0):
    if "deepseek" in url and "balance" in url:
        return {"balance_infos": [{"currency": "CNY", "total_balance": "12.40"}]}
    if "opencode" in url and "usage" in url:
        return {"usage": {"rolling": {"percent": 78}, "weekly": {"percent": 45},
                          "monthly": {"percent": 60}}}
    return {"choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 2}}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTFLOAT_LLM_USAGE", str(tmp_path / "usage.jsonl"))
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_http_json", fake_http)
    llm.clear_balance_cache()
    cfg = {"theme": "light", "llm": {"providers": [], "active": ""}}
    h = LlmHandlers(cfg)
    app = create_app(WebBridge(), h)
    c = TestClient(app)
    yield c, h
    c.close()
    llm.clear_balance_cache()


def test_save_provider_masks_key(client):
    c, h = client
    r = c.post("/api/llm/providers", json={"provider": dict(DEEPSEEK)})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True
    p = body["provider"]
    assert p["id"] == "deepseek"
    assert p["api_key_set"] is True
    assert p["name"] == "DeepSeek"
    assert "sk-secret-1234" not in r.text, "API 响应不得回显 Key"
    assert h.saved == 1
    assert h.applied and h.applied[-1] == ["llm"]


def test_save_second_provider_and_activate(client):
    c, h = client
    c.post("/api/llm/providers", json={"provider": dict(DEEPSEEK)})
    r2 = c.post("/api/llm/providers", json={"provider": {
        "name": "OpenCode Go", "preset": "opencode-go", "api_key": "sk-go",
        "kind": "sub"}})
    assert r2.json()["provider"]["kind"] == "sub"
    assert r2.json()["provider"]["balance_url"] == llm.OPENCODE_GO_USAGE_URL

    act = c.post("/api/llm/providers/opencode-go/activate")
    assert act.json()["ok"] is True
    assert act.json()["active"] == "opencode-go"
    assert h.cfg["llm"]["active"] == "opencode-go"

    both = c.get("/api/llm/providers").json()
    assert both["active"] == "opencode-go"
    assert len(both["providers"]) == 2
    assert both["totals"]["subscriptions"] == 1


def test_provider_list_totals_and_balances(client):
    c, h = client
    c.post("/api/llm/providers", json={"provider": dict(DEEPSEEK)})
    body = c.get("/api/llm/providers").json()
    assert body["ok"] is True
    assert body["active"] == "deepseek"
    assert body["enabled_count"] == 1
    assert body["presets"] and any(p["id"] == "opencode-go" for p in body["presets"])
    p = body["providers"][0]
    assert p["balance"]["ok"] is True and p["balance"]["balance"] == 12.4
    assert p["today_tokens"] == 0
    assert body["totals"]["money"] == [{"currency": "CNY", "amount": 12.4}]
    assert "sk-secret-1234" not in json.dumps(body, ensure_ascii=False)


def test_test_endpoint_records_usage(client):
    c, h = client
    c.post("/api/llm/providers", json={"provider": dict(DEEPSEEK)})
    r = c.post("/api/llm/test", json={"id": "deepseek", "provider": {"model": "deepseek-chat"}})
    body = r.json()
    assert body["ok"] is True and body["reply"] == "OK"
    assert body["usage"]["total_tokens"] == 8

    usage = c.get("/api/llm/usage").json()
    assert usage["ok"] is True
    assert usage["today"]["total_tokens"] == 8
    assert usage["by_purpose"]["test"]["calls"] == 1

    lst = c.get("/api/llm/providers").json()
    assert lst["providers"][0]["today_tokens"] == 8
    assert lst["totals"]["today_tokens"] == 8


def test_delete_does_not_revive_migrated_provider(client):
    """P0：删掉的供应商不能被 api_monitor 迁移逻辑复活。"""
    c, h = client
    h.cfg["api_monitor"] = {"endpoints": [{
        "name": "DeepSeek 余额",
        "url": "https://api.deepseek.com/user/balance",
        "base_url": "https://api.deepseek.com/v1",
        "headers": {"Authorization": "Bearer sk-migrated-7777"},
        "fields": [{"label": "余额", "jsonpath": "$.balance_infos[0].total_balance"}],
    }]}
    first = c.get("/api/llm/providers").json()
    assert [p["id"] for p in first["providers"]] == ["deepseek"]
    assert first["active"] == "deepseek"

    d = c.post("/api/llm/providers/deepseek/delete").json()
    assert d == {"ok": True, "active": ""}

    after = c.get("/api/llm/providers").json()
    assert after["providers"] == []
    assert after["active"] == ""
    assert h.cfg["llm"]["migrated_from_api_monitor"] is True


def test_put_config_without_llm_key_keeps_providers(client):
    """P0 回归：设置页拿旧快照保存（changed_keys 不含 llm）不得回滚供应商 / Key。"""
    c, h = client
    c.post("/api/llm/providers", json={"provider": dict(DEEPSEEK)})
    assert [p["id"] for p in h.cfg["llm"]["providers"]] == ["deepseek"]

    stale = {"theme": "dark", "llm": {"providers": [], "active": ""}}
    r = c.put("/api/config", json={"config": stale, "changed_keys": ["theme"]})
    assert r.status_code == 200
    kept = r.json()["config"]["llm"]
    assert [p["id"] for p in kept["providers"]] == ["deepseek"]
    assert kept["active"] == "deepseek"
    assert kept["providers"][0]["api_key"] == "sk-secret-1234"

    # 已删除的供应商同样不能被旧快照复活
    c.post("/api/llm/providers/deepseek/delete")
    assert h.cfg["llm"]["providers"] == []
    r = c.put("/api/config", json={"config": stale, "changed_keys": ["theme"]})
    assert r.json()["config"]["llm"]["providers"] == []
    assert c.get("/api/llm/providers").json()["providers"] == []


def test_test_endpoint_accepts_unsaved_draft(client):
    """P1：未保存的新供应商可以直接测（不落盘、不切 active）。"""
    c, h = client
    r = c.post("/api/llm/test", json={"provider": {
        "name": "草稿 DeepSeek", "preset": "deepseek",
        "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
        "api_key": "sk-draft-123"}})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["reply"] == "OK"
    assert h.saved == 0
    assert c.get("/api/llm/providers").json()["providers"] == []


def test_saved_provider_without_key_is_not_active(client):
    c, h = client
    r = c.post("/api/llm/providers", json={"provider": {
        "name": "X", "base_url": "https://x.example/v1", "model": "m", "api_key": ""}})
    p = r.json()["provider"]
    assert p["api_key_set"] is False
    assert r.json()["active"] == ""
    assert c.get("/api/llm/providers").json()["active"] == ""


def test_refresh_and_delete(client):
    c, h = client
    c.post("/api/llm/providers", json={"provider": dict(DEEPSEEK)})
    assert c.post("/api/llm/refresh").json()["ok"] is True

    d = c.post("/api/llm/providers/deepseek/delete")
    assert d.json() == {"ok": True, "active": ""}
    assert c.get("/api/llm/providers").json()["providers"] == []
    assert c.post("/api/llm/providers/nope/delete").status_code == 404


def test_invalid_provider_returns_400(client):
    c, h = client
    r = c.post("/api/llm/providers", json={"provider": {"name": "", "base_url": "",
                                                         "model": ""}})
    assert r.status_code == 400
    assert r.json()["ok"] is False
    assert h.saved == 0


def test_subscription_provider_list_shows_percent(client):
    c, h = client
    c.post("/api/llm/providers", json={"provider": {
        "name": "OpenCode Go", "preset": "opencode-go", "api_key": "sk-go",
        "kind": "sub"}})
    body = c.get("/api/llm/providers").json()
    p = body["providers"][0]
    assert p["balance"]["kind"] == "sub"
    assert p["balance"]["percent"] == 78.0
    assert body["totals"]["money"] == []          # 订阅不计入总余额
    assert body["totals"]["subscriptions"] == 1
