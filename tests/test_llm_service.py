# -*- coding: utf-8 -*-
"""AI 接入服务层测试：配置迁移 / CRUD / 激活 / 测试 / 余额解析 / Token 统计

全部使用 monkeypatch + 临时目录，不访问真实网络，不写用户 config。
"""
import json
from datetime import datetime

import pytest

from agentfloat.services import llm


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """隔离用量文件与余额缓存；清掉可能影响 Key 解析的环境变量。"""
    monkeypatch.setenv("AGENTFLOAT_LLM_USAGE", str(tmp_path / "usage.jsonl"))
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    llm.clear_balance_cache()
    yield
    llm.clear_balance_cache()


def _cfg(**providers):
    return {"llm": {"providers": list(providers.values()), "active": ""}}


DEEPSEEK = {
    "id": "deepseek", "name": "DeepSeek", "preset": "deepseek",
    "base_url": "https://api.deepseek.com/v1", "api_key": "sk-deepseek-secret-1234",
    "model": "deepseek-chat", "kind": "money",
    "balance_url": "https://api.deepseek.com/user/balance",
    "balance_field": "balance_infos[0].total_balance", "currency": "CNY",
}


# ── 配置归一化 / 迁移 ─────────────────────────────────
def test_normalize_adds_missing_llm():
    cfg = {}
    out, changed = llm.normalize_config(cfg)
    assert changed is True
    assert out["providers"] == [] and out["active"] == ""
    assert cfg["llm"] is out


def test_normalize_fills_provider_fields():
    cfg = {"llm": {"providers": [{"name": "My DS", "api_key": "k",
                                  "base_url": "https://api.deepseek.com/v1/",
                                  "model": "m"}]}}
    out, changed = llm.normalize_config(cfg, derive_from_api_monitor=False)
    p = out["providers"][0]
    assert changed is True
    assert p["id"] == "my-ds"
    assert p["base_url"] == "https://api.deepseek.com/v1"      # 去掉尾斜杠
    assert p["preset"] == "deepseek"
    assert p["kind"] == "money"
    assert out["active"] == "my-ds"                            # 自动设为当前


def test_normalize_migrates_from_api_monitor():
    cfg = {"api_monitor": {"endpoints": [{
        "name": "DeepSeek 余额",
        "url": "https://api.deepseek.com/user/balance",
        "base_url": "https://api.deepseek.com/v1",
        "headers": {"Authorization": "Bearer sk-migrated-9999"},
        "fields": [{"label": "余额", "jsonpath": "$.balance_infos[0].total_balance"}],
    }]}}
    out, _ = llm.normalize_config(cfg)
    assert len(out["providers"]) == 1
    p = out["providers"][0]
    assert p["api_key"] == "sk-migrated-9999"
    assert p["model"] == "deepseek-chat"
    assert p["balance_field"] == "balance_infos[0].total_balance"


def test_normalize_skips_endpoint_without_key_or_model():
    cfg = {"api_monitor": {"endpoints": [{"name": "X", "url": "https://x", "base_url": "https://x/v1"}]}}
    out, _ = llm.normalize_config(cfg)
    assert out["providers"] == []


def _monitor_cfg():
    return {"api_monitor": {"endpoints": [{
        "name": "DeepSeek 余额",
        "url": "https://api.deepseek.com/user/balance",
        "base_url": "https://api.deepseek.com/v1",
        "headers": {"Authorization": "Bearer sk-migrated-9999"},
        "fields": [{"label": "余额", "jsonpath": "$.balance_infos[0].total_balance"}],
    }]}}


def test_normalize_migration_runs_only_once():
    cfg = _monitor_cfg()
    out, _ = llm.normalize_config(cfg)
    assert [p["id"] for p in out["providers"]] == ["deepseek"]
    assert out["migrated_from_api_monitor"] is True

    # 删掉迁移出来的供应商后，再 GET / 归一化不得复活（P0）
    assert llm.delete_provider(cfg, "deepseek") is True
    again, _ = llm.normalize_config(cfg)
    assert again["providers"] == []
    assert again["active"] == ""
    # 连续多次也不会回来
    assert llm.normalize_config(cfg)[0]["providers"] == []


def test_normalize_does_not_revive_deleted_id_without_flag():
    """迁移标记丢失时，deleted_ids 仍能阻止同一个 id 被重新派生。"""
    cfg = _monitor_cfg()
    llm.normalize_config(cfg)
    llm.delete_provider(cfg, "deepseek")
    cfg["llm"].pop("migrated_from_api_monitor", None)
    out, _ = llm.normalize_config(cfg)
    assert out["providers"] == []
    assert "deepseek" in out["deleted_ids"]


def test_normalize_legacy_with_providers_does_not_derive_after_delete():
    cfg = _cfg(a=dict(DEEPSEEK, id="a"))
    cfg["api_monitor"] = _monitor_cfg()["api_monitor"]
    cfg["llm"]["active"] = "a"
    assert [p["id"] for p in llm.normalize_config(cfg)[0]["providers"]] == ["a"]
    assert llm.delete_provider(cfg, "a") is True
    assert llm.normalize_config(cfg)[0]["providers"] == []


def test_normalize_resets_dangling_active():
    cfg = {"llm": {"providers": [dict(DEEPSEEK)], "active": "nope"}}
    out, changed = llm.normalize_config(cfg, derive_from_api_monitor=False)
    assert changed is True
    assert out["active"] == "deepseek"


# ── CRUD / 激活 ──────────────────────────────────────
def test_upsert_create_update_and_activate():
    cfg = {}
    created = llm.upsert_provider(cfg, {"name": "DeepSeek", "preset": "deepseek",
                                        "api_key": "sk-1", "base_url": "https://api.deepseek.com/v1",
                                        "model": "deepseek-chat"})
    assert created["id"] == "deepseek"
    assert llm.active_provider_id(cfg) == "deepseek"
    assert created["created_at"]

    # 更新：留空 Key = 保留旧 Key
    updated = llm.upsert_provider(cfg, {"id": "deepseek", "name": "DeepSeek 主力",
                                        "model": "deepseek-reasoner", "api_key": ""})
    assert updated["api_key"] == "sk-1"
    assert updated["model"] == "deepseek-reasoner"
    assert len(llm.list_providers(cfg)) == 1

    second = llm.upsert_provider(cfg, {"name": "OpenRouter", "preset": "openrouter",
                                       "api_key": "sk-2"})
    assert second["id"] == "openrouter"
    assert llm.activate_provider(cfg, "openrouter")["id"] == "openrouter"
    assert llm.get_active_provider(cfg)["name"] == "OpenRouter"


def test_upsert_validation_errors():
    with pytest.raises(llm.LLMError):
        llm.upsert_provider({}, {"name": "", "base_url": "", "model": ""})
    with pytest.raises(llm.LLMError):
        llm.upsert_provider({}, {"name": "n", "base_url": "ftp://x", "model": "m"})


def test_sub_provider_forces_usage_endpoint():
    cfg = {}
    p = llm.upsert_provider(cfg, {"name": "OpenCode Go", "preset": "opencode-go",
                                 "api_key": "sk-go", "kind": "sub",
                                 "balance_url": "https://evil/x",
                                 "balance_field": "whatever"})
    assert p["kind"] == "sub"
    assert p["balance_url"] == llm.OPENCODE_GO_USAGE_URL
    assert p["balance_field"] == "usage.rolling.percent"


def test_delete_provider_falls_back_active():
    cfg = _cfg(a=dict(DEEPSEEK, id="a"), b=dict(DEEPSEEK, id="b", name="B"))
    cfg["llm"]["active"] = "a"
    assert llm.delete_provider(cfg, "a") is True
    assert llm.active_provider_id(cfg) == "b"
    assert llm.delete_provider(cfg, "missing") is False


def test_activate_unknown_and_disabled():
    cfg = _cfg(a=dict(DEEPSEEK, id="a", enabled=False))
    with pytest.raises(llm.LLMError):
        llm.activate_provider(cfg, "nope")
    with pytest.raises(llm.LLMError):
        llm.activate_provider(cfg, "a")
    assert llm.get_active_provider(cfg) is None
    assert llm.has_active_provider(cfg) is False


def test_has_active_provider_requires_usable_key(monkeypatch):
    cfg = _cfg(a=dict(DEEPSEEK, id="a", api_key=""))
    cfg["llm"]["active"] = "a"
    assert llm.has_active_provider(cfg) is False          # 无 Key 不算可用（回退 CLI Agent）

    cfg_env = _cfg(a=dict(DEEPSEEK, id="a", api_key="{{env:LLM_P1_KEY}}"))
    cfg_env["llm"]["active"] = "a"
    assert llm.has_active_provider(cfg_env) is False      # 环境变量未设置
    monkeypatch.setenv("LLM_P1_KEY", "sk-env-ok")
    assert llm.has_active_provider(cfg_env) is True

    cfg_ok = _cfg(a=dict(DEEPSEEK, id="a"))
    cfg_ok["llm"]["active"] = "a"
    assert llm.has_active_provider(cfg_ok) is True


def test_upsert_does_not_auto_activate_keyless_provider():
    cfg = {}
    first = llm.upsert_provider(cfg, {"name": "DeepSeek", "preset": "deepseek",
                                      "api_key": "", "base_url": "https://api.deepseek.com/v1",
                                      "model": "deepseek-chat"})
    assert first["id"] == "deepseek"
    assert llm.active_provider_id(cfg) == ""
    assert llm.has_active_provider(cfg) is False

    second = llm.upsert_provider(cfg, {"name": "OpenRouter", "preset": "openrouter",
                                       "api_key": "sk-or"})
    assert llm.active_provider_id(cfg) == second["id"]


def test_mask_provider_uses_env_fallback(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-env-5678")
    masked = llm.mask_provider({"id": "go", "preset": "opencode-go", "kind": "sub",
                                "api_key": ""})
    assert masked["api_key_set"] is True                  # 余额能用 env Key → 不显示未配置
    assert masked["api_key_hint"] == "…5678"             # 只给尾 4 位
    assert "sk-env" not in json.dumps(masked, ensure_ascii=False)


def test_mask_provider_hides_key():
    masked = llm.mask_provider(dict(DEEPSEEK))
    assert "api_key" not in masked
    assert masked["api_key_set"] is True
    assert masked["api_key_hint"].endswith("1234")
    assert "secret" not in json.dumps(masked, ensure_ascii=False)
    assert llm.mask_provider({"name": "x", "api_key": ""})["api_key_set"] is False


def test_resolve_api_key_env_template(monkeypatch):
    monkeypatch.setenv("LLM_TEST_KEY", "sk-from-env")
    assert llm.resolve_api_key({"api_key": "{{env:LLM_TEST_KEY}}"}) == "sk-from-env"
    assert llm.resolve_api_key({"api_key": "Bearer sk-direct "}) == "sk-direct"
    assert llm.resolve_api_key({"api_key": "{{env:NOT_SET_XYZ}}"}) == ""


# ── chat / 测试 / 用量 ───────────────────────────────
def test_chat_records_usage(monkeypatch):
    calls = []

    def fake_http(method, url, headers=None, body=None, timeout=30.0):
        calls.append({"method": method, "url": url, "headers": headers, "body": body})
        return {"choices": [{"message": {"content": "你好"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3}}

    monkeypatch.setattr(llm, "_http_json", fake_http)
    cfg = _cfg(a=dict(DEEPSEEK, id="a"))
    cfg["llm"]["active"] = "a"
    result = llm.chat(cfg, [{"role": "user", "content": "hi"}], purpose="news")
    assert result["content"] == "你好"
    assert result["usage"] == {"prompt_tokens": 12, "completion_tokens": 3,
                               "total_tokens": 15, "estimated": False}
    assert calls[0]["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-deepseek-secret-1234"
    assert calls[0]["body"]["model"] == "deepseek-chat"

    usage = llm.summarize_usage()
    assert usage["today"]["total_tokens"] == 15
    assert usage["by_purpose"]["news"]["calls"] == 1


def test_chat_estimates_without_usage(monkeypatch):
    monkeypatch.setattr(llm, "_http_json", lambda *a, **k: {
        "choices": [{"message": {"content": "abcdefgh"}}]})
    cfg = _cfg(a=dict(DEEPSEEK, id="a"))
    cfg["llm"]["active"] = "a"
    result = llm.chat(cfg, [{"role": "user", "content": "12345678"}], purpose="translate")
    assert result["usage"]["estimated"] is True
    assert result["usage"]["prompt_tokens"] == 2
    assert result["usage"]["completion_tokens"] == 2
    records = llm.read_usage()
    assert records[0]["estimated"] is True
    assert records[0]["purpose"] == "translate"


def test_chat_requires_provider_and_key():
    with pytest.raises(llm.LLMError):
        llm.chat({}, [{"role": "user", "content": "x"}])
    cfg = _cfg(a=dict(DEEPSEEK, id="a", api_key=""))
    cfg["llm"]["active"] = "a"
    with pytest.raises(llm.LLMError) as exc:
        llm.chat(cfg, [{"role": "user", "content": "x"}])
    assert "API Key" in str(exc.value)


def test_chat_bad_response(monkeypatch):
    monkeypatch.setattr(llm, "_http_json", lambda *a, **k: {"error": {"message": "额度不足"}})
    cfg = _cfg(a=dict(DEEPSEEK, id="a"))
    cfg["llm"]["active"] = "a"
    with pytest.raises(llm.LLMError) as exc:
        llm.chat(cfg, [{"role": "user", "content": "x"}])
    assert "额度不足" in str(exc.value)


def test_test_provider_uses_draft_without_switching(monkeypatch):
    seen = {}

    def fake_http(method, url, headers=None, body=None, timeout=30.0):
        seen["url"] = url
        seen["model"] = body["model"]
        seen["auth"] = headers.get("Authorization")
        return {"choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1}}

    monkeypatch.setattr(llm, "_http_json", fake_http)
    cfg = _cfg(a=dict(DEEPSEEK, id="a"))
    cfg["llm"]["active"] = "a"
    out = llm.test_provider(cfg, provider={"id": "a", "model": "deepseek-reasoner",
                                           "api_key": ""})
    assert out["ok"] is True and out["reply"] == "OK"
    assert seen["model"] == "deepseek-reasoner"
    assert seen["auth"] == "Bearer sk-deepseek-secret-1234"   # 留空沿用已保存 Key
    assert llm.get_active_provider(cfg)["model"] == "deepseek-chat"  # 未改动配置
    assert llm.summarize_usage()["by_purpose"]["test"]["calls"] == 1


def test_test_provider_draft_without_id(monkeypatch):
    """未保存的新供应商（无 id）也能直接测试，且不落盘、不切 active（P1）。"""
    seen = {}

    def fake_http(method, url, headers=None, body=None, timeout=30.0):
        seen["url"] = url
        seen["auth"] = headers.get("Authorization")
        seen["model"] = body["model"]
        return {"choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1}}

    monkeypatch.setattr(llm, "_http_json", fake_http)
    cfg = {"llm": {"providers": [], "active": ""}}
    out = llm.test_provider(cfg, provider={"name": "DeepSeek 草稿", "preset": "deepseek",
                                           "base_url": "https://api.deepseek.com/v1",
                                           "model": "deepseek-chat",
                                           "api_key": "sk-draft-0001"})
    assert out["ok"] is True and out["reply"] == "OK"
    assert out["provider_id"] == "deepseek"
    assert seen["auth"] == "Bearer sk-draft-0001"
    assert cfg["llm"]["providers"] == []                  # 草稿不落盘
    assert cfg["llm"]["active"] == ""
    assert llm.summarize_usage()["by_purpose"]["test"]["calls"] == 1


def test_balance_url_scheme_is_validated():
    with pytest.raises(llm.LLMError) as exc:
        llm.upsert_provider({}, {"name": "X", "base_url": "https://x.example/v1",
                                 "model": "m", "api_key": "sk-1",
                                 "balance_url": "file:///C:/Windows/win.ini"})
    assert "余额接口" in str(exc.value)
    # 空值仍然允许（没有余额接口）
    provider = llm.upsert_provider({}, {"name": "Y", "base_url": "https://y.example/v1",
                                        "model": "m", "api_key": "sk-1"})
    assert provider["balance_url"] == ""


def test_fetch_balance_rejects_file_url_without_leaking(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text('{"token":"sk-LOCAL-SECRET-9999"}', encoding="utf-8")
    url = secret.as_uri()
    provider = dict(DEEPSEEK, balance_url=url)
    out = llm.fetch_balance(provider)
    assert out["ok"] is False
    blob = json.dumps(out, ensure_ascii=False)
    assert "sk-LOCAL-SECRET-9999" not in blob             # 不回显本地文件内容
    assert "file" not in out["error"].lower()

    with pytest.raises(llm.LLMError) as exc:
        llm._http_json("GET", url)                        # 兜底：底层也拒绝非 http(s)
    assert "sk-LOCAL-SECRET-9999" not in str(exc.value)


# ── 余额：金额型 / 订阅型 ────────────────────────────
def test_fetch_balance_money_deepseek(monkeypatch):
    monkeypatch.setattr(llm, "_http_json", lambda *a, **k: {
        "is_available": True,
        "balance_infos": [{"currency": "CNY", "total_balance": "12.40",
                           "granted_balance": "0.00", "topped_up_balance": "12.40"}]})
    out = llm.fetch_balance(dict(DEEPSEEK))
    assert out["ok"] is True and out["kind"] == "money"
    assert out["balance"] == 12.4 and out["currency"] == "CNY"
    assert out["low"] is False


def test_fetch_balance_money_low(monkeypatch):
    monkeypatch.setattr(llm, "_http_json", lambda *a, **k: {
        "balance_infos": [{"currency": "CNY", "total_balance": "3.00"}]})
    out = llm.fetch_balance(dict(DEEPSEEK, low_balance_warn=5))
    assert out["ok"] is True and out["low"] is True


def test_fetch_balance_openrouter_credits(monkeypatch):
    monkeypatch.setattr(llm, "_http_json", lambda *a, **k: {
        "data": {"total_credits": 10.0, "total_usage": 6.8}})
    provider = {"id": "or", "kind": "money", "balance_url": "https://openrouter.ai/api/v1/credits",
                "balance_field": "data.total_credits", "currency": "USD", "api_key": "sk-or",
                "low_balance_warn": 2}
    out = llm.fetch_balance(provider)
    assert out["ok"] is True
    assert out["balance"] == 3.2 and out["currency"] == "USD"


def test_fetch_balance_missing_field(monkeypatch):
    monkeypatch.setattr(llm, "_http_json", lambda *a, **k: {"data": {}})
    out = llm.fetch_balance(dict(DEEPSEEK))
    assert out["ok"] is False and "余额字段未命中" in out["error"]


def test_fetch_balance_without_url_is_skipped():
    out = llm.fetch_balance({"id": "x", "kind": "money", "api_key": "k"})
    assert out["ok"] is False and out.get("skipped") is True


def test_fetch_balance_network_error_is_swallowed(monkeypatch):
    def boom(*a, **k):
        raise llm.LLMError("连接失败: 连接超时（检查网络或代理是否已开启）")

    monkeypatch.setattr(llm, "_http_json", boom)
    out = llm.fetch_balance(dict(DEEPSEEK))
    assert out["ok"] is False and "连接超时" in out["error"]


def test_fetch_balance_subscription_percent(monkeypatch):
    monkeypatch.setattr(llm, "_http_json", lambda *a, **k: {
        "usage": {"rolling": {"percent": 78}, "weekly": {"percent": 45.5},
                  "monthly": {"percent": 60}}})
    provider = {"id": "go", "preset": "opencode-go", "kind": "sub", "api_key": "sk-go",
                "balance_url": llm.OPENCODE_GO_USAGE_URL,
                "balance_field": "usage.rolling.percent", "low_balance_warn": 90}
    out = llm.fetch_balance(provider)
    assert out["ok"] is True and out["kind"] == "sub"
    assert out["percent"] == 78.0
    assert out["periods"] == {"rolling": 78.0, "weekly": 45.5, "monthly": 60.0}
    assert out["low"] is False
    assert "balance" not in out


def test_fetch_balance_subscription_uses_env_key(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "sk-env-go")
    seen = {}

    def fake_http(method, url, headers=None, body=None, timeout=8.0):
        seen["url"] = url
        seen["auth"] = headers.get("Authorization")
        return {"usage": {"rolling": {"percent": 91}}}

    monkeypatch.setattr(llm, "_http_json", fake_http)
    provider = {"id": "go", "preset": "opencode-go", "kind": "sub", "api_key": ""}
    out = llm.fetch_balance(provider)
    assert out["ok"] is True and out["low"] is True
    assert seen["url"] == llm.OPENCODE_GO_USAGE_URL
    assert seen["auth"] == "Bearer sk-env-go"


def test_fetch_balance_subscription_without_key(monkeypatch):
    # 本机可能真的配了 OPENCODE_GO_API_KEY（注册表兜底），这里强制解析为空
    monkeypatch.setattr(llm, "resolve_api_key", lambda provider: "")
    out = llm.fetch_balance({"id": "go", "preset": "opencode-go", "kind": "sub"})
    assert out["ok"] is False and "OPENCODE_GO_API_KEY" in out["error"]


def test_balance_cache_and_force(monkeypatch):
    counter = {"n": 0}

    def fake_http(*a, **k):
        counter["n"] += 1
        return {"balance_infos": [{"currency": "CNY", "total_balance": "9.00"}]}

    monkeypatch.setattr(llm, "_http_json", fake_http)
    provider = dict(DEEPSEEK)
    first = llm.fetch_balance_cached(provider, ttl=60)
    second = llm.fetch_balance_cached(provider, ttl=60)
    third = llm.fetch_balance_cached(provider, ttl=60, force=True)
    assert first.get("cached") is None
    assert second.get("cached") is True
    assert third.get("cached") is None
    assert counter["n"] == 2


def test_balances_for_parallel_and_summary(monkeypatch):
    def fake_http(method, url, headers=None, body=None, timeout=8.0):
        if "deepseek" in url:
            return {"balance_infos": [{"currency": "CNY", "total_balance": "12.40"}]}
        return {"data": {"total_credits": 10.0, "total_usage": 6.8}}

    monkeypatch.setattr(llm, "_http_json", fake_http)
    cfg = _cfg(a=dict(DEEPSEEK, id="a"),
               b={"id": "b", "name": "OR", "kind": "money", "api_key": "sk-or",
                  "balance_url": "https://openrouter.ai/api/v1/credits",
                  "balance_field": "data.total_credits", "currency": "USD",
                  "low_balance_warn": 2},
               c={"id": "c", "name": "GO", "kind": "sub", "preset": "opencode-go",
                  "api_key": "sk-go"})
    balances = llm.balances_for(cfg, force=True)
    assert set(balances) == {"a", "b", "c"}
    summary = llm.summarize_balances(llm.list_providers(cfg), balances)
    assert {"currency": "CNY", "amount": 12.4} in summary["money"]
    assert {"currency": "USD", "amount": 3.2} in summary["money"]
    assert summary["subscriptions"] == 1            # 订阅型不计入总余额
    assert summary["low_count"] == 0


def test_summarize_balances_unknown_currency_is_not_cny():
    providers = [{"id": "x", "kind": "money", "enabled": True, "currency": ""}]
    balances = {"x": {"ok": True, "balance": 7.5, "currency": ""}}
    summary = llm.summarize_balances(providers, balances)
    assert summary["money"] == [{"currency": "OTHER", "amount": 7.5}]
    assert all(row["currency"] != "CNY" for row in summary["money"])


# ── Token 统计 ──────────────────────────────────────
def test_estimate_tokens():
    assert llm.estimate_tokens("") == 1
    assert llm.estimate_tokens("12345678") == 2
    assert llm.estimate_tokens({"a": 1}) >= 1
    assert llm.estimate_tokens(None) == 1


def test_usage_summary_by_day_month_and_purpose():
    now = datetime(2026, 11, 2, 18, 30, 0)
    llm.record_usage("a", "m1", 100, 20, purpose="news", ts="2026-11-02T09:00:00")
    llm.record_usage("a", "m1", 50, 10, purpose="translate", ts="2026-11-02T10:00:00")
    llm.record_usage("b", "m2", 300, 0, purpose="test", estimated=True,
                     ts="2026-11-01T23:00:00")
    llm.record_usage("a", "m1", 999, 1, purpose="news", ts="2026-10-20T08:00:00")

    summary = llm.summarize_usage(now=now)
    assert summary["today"]["total_tokens"] == 180
    assert summary["today"]["calls"] == 2
    assert summary["month"]["total_tokens"] == 480
    assert summary["by_purpose"]["news"]["total_tokens"] == 1120
    assert summary["by_purpose"]["translate"]["total_tokens"] == 60
    assert summary["by_purpose"]["test"]["estimated_calls"] == 1
    assert summary["by_provider_today"]["a"]["total_tokens"] == 180
    assert summary["last_call_at"] == "2026-11-02T10:00:00"
    assert [r["model"] for r in summary["recent"]][:2] == ["m1", "m1"]


def test_summarize_usage_recent_includes_past_days():
    now = datetime(2026, 11, 2, 18, 30, 0)
    llm.record_usage("a", "old", 10, 1, purpose="news", ts="2026-10-20T08:00:00")
    llm.record_usage("a", "new", 20, 2, purpose="news", ts="2026-11-02T09:00:00")
    summary = llm.summarize_usage(now=now)
    # by_purpose 是累计口径；recent 不再只看今天（前端已标注「累计」）
    assert [r["model"] for r in summary["recent"]] == ["new", "old"]
    assert summary["by_purpose"]["news"]["total_tokens"] == 33


def test_read_usage_skips_bad_lines(tmp_path):
    path = tmp_path / "usage.jsonl"
    path.write_text('{"ts":"2026-11-02T10:00:00","total_tokens":5}\nnot-json\n\n',
                    encoding="utf-8")
    records = llm.read_usage(str(path))
    assert len(records) == 1


def test_summarize_usage_empty(tmp_path):
    summary = llm.summarize_usage(path=str(tmp_path / "missing.jsonl"))
    assert summary["today"]["total_tokens"] == 0
    assert summary["recent"] == []
