# -*- coding: utf-8 -*-
"""API 用量监控测试：模板变量 / JSONPath / 校验 / 序列化 / 本地 HTTP 端点集成"""
import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentfloat.services.api_monitor import config as cfg
from agentfloat.services.api_monitor.fetcher import (
    FetchError, FetchResult, fetch_endpoint, serialize_results,
)


# ── 模板引擎 ─────────────────────────────────────────
def test_resolve_template_env(monkeypatch):
    monkeypatch.setenv("AF_TEST_KEY_XYZ", "secret")
    assert cfg.resolve_template("Bearer {{env:AF_TEST_KEY_XYZ}}") == "Bearer secret"


def test_resolve_template_today():
    assert cfg.resolve_template("d={{today}}") == "d=" + date.today().isoformat()


def test_resolve_template_unknown_passthrough():
    assert cfg.resolve_template("{{nope:x}}") == "{{nope:x}}"


def test_resolve_headers():
    monkeypatch_key = "AF_HDR_XYZ"
    import os
    os.environ[monkeypatch_key] = "v"
    try:
        out = cfg.resolve_headers({"A": "{{env:%s}}" % monkeypatch_key})
        assert out == {"A": "v"}
    finally:
        os.environ.pop(monkeypatch_key, None)


# ── JSONPath ─────────────────────────────────────────
def test_jsonpath_cases():
    data = {"usage": {"used": 80, "limit": 200}, "items": [{"v": 1}, {"v": 2}]}
    assert cfg.jsonpath_get(data, "$.usage.used") == 80
    assert cfg.jsonpath_get(data, "usage.limit") == 200      # 自动补 $. 前缀
    assert cfg.jsonpath_get(data, "$.items[1].v") == 2
    assert cfg.jsonpath_get(data, "$.items[9].v") is None
    assert cfg.jsonpath_get(data, "$.items[*]") == data["items"]
    assert cfg.jsonpath_get(data, "$.missing.deep") is None
    assert cfg.jsonpath_get({"a": 1}, "$.a.b") is None        # 非 dict 继续取键


# ── 校验 ─────────────────────────────────────────────
def test_validate_endpoint_ok():
    ep = {"name": "n", "url": "https://x", "fields": [{"label": "l", "jsonpath": "$.a"}]}
    assert cfg.validate_endpoint(ep) == []


def test_validate_endpoint_errors():
    errs = cfg.validate_endpoint({})
    assert any("名称" in e for e in errs)
    assert any("URL" in e for e in errs)
    assert any("字段" in e for e in errs)
    errs2 = cfg.validate_endpoint({"name": "n", "url": "u", "method": "PATCH",
                                   "fields": [{"label": "", "jsonpath": ""}]})
    assert any("HTTP 方法" in e for e in errs2)


def test_validate_api_monitor_config_prefix():
    errs = cfg.validate_api_monitor_config({"endpoints": [{"name": "e", "url": "u", "fields": []}]})
    assert errs and errs[0].startswith("端点 1")


# ── 序列化 ───────────────────────────────────────────
def test_serialize_results():
    ok = FetchResult("A", [{"label": "已用量", "value": 5, "unit": "x", "display": "number"}],
                     {"used": 5, "total": 10, "pct": 50.0}, "raw")
    bad = FetchResult("B", [{"label": "错误", "value": "HTTP 500", "unit": "", "display": "text"}],
                      None, "")
    out = serialize_results([ok, bad])
    assert out[0]["ok"] is True and out[0]["progress"]["pct"] == 50.0
    assert out[1]["ok"] is False and out[1]["error"] == "HTTP 500"
    assert out[0]["index"] == 0 and out[1]["index"] == 1


# ── 本地 HTTP 端点集成 ───────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默
        pass

    def do_GET(self):
        if self.path.startswith("/bad"):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        if self.path.startswith("/notjson"):
            body = b"<html>nope</html>"
        else:
            body = json.dumps({"usage": {"used": 80, "limit": 200}}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def local_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def test_fetch_endpoint_success(local_server):
    ep = {
        "name": "local", "url": local_server + "/usage", "method": "GET",
        "fields": [
            {"label": "已用量", "jsonpath": "$.usage.used", "unit": "tokens", "display": "number"},
            {"label": "占比", "jsonpath": "$.usage.used", "display": "percent"},
        ],
        "progress_field": {"used": "$.usage.used", "total": "$.usage.limit"},
    }
    res = fetch_endpoint(ep)
    assert res.endpoint_name == "local"
    assert res.fields[0]["value"] == 80
    assert res.fields[1]["value"].endswith("%")
    assert res.progress == {"used": 80.0, "total": 200.0, "pct": 40.0}


def test_fetch_endpoint_http_error(local_server):
    with pytest.raises(FetchError) as ei:
        fetch_endpoint({"name": "e", "url": local_server + "/bad", "fields": []})
    assert ei.value.status_code == 500


def test_fetch_endpoint_bad_json(local_server):
    with pytest.raises(FetchError) as ei:
        fetch_endpoint({"name": "e", "url": local_server + "/notjson", "fields": []})
    assert "JSON" in str(ei.value)
