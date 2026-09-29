# -*- coding: utf-8 -*-
"""API 用量页重构（PATCH 3.5.3）：端点清理迁移 / 显示框预览 / 页面数据"""

import json
from types import SimpleNamespace

from agentfloat.core import config as cfgmod


def _isolate(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", str(p))
    monkeypatch.setattr(cfgmod, "_OLD_CONFIG_PATH", str(tmp_path / "old.json"))
    return p


def test_first_run_has_no_sample_endpoint(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    cfg = cfgmod.load_config()
    assert cfg["api_monitor"]["endpoints"] == []      # 不再预置「My API」示例占位端点


def test_load_removes_placeholder_and_duplicates(tmp_path, monkeypatch):
    p = _isolate(tmp_path, monkeypatch)
    ep = {"name": "OpenCode Go", "url": "https://opencode.ai/zen/go/v1/usage",
          "fields": [{"label": "a", "jsonpath": "$.a"}]}
    p.write_text(json.dumps({
        "api_monitor": {
            "enabled": True,
            "endpoints": [
                {"name": "My API", "url": "https://api.example.com/v1/usage?date={{today}}", "fields": []},
                ep,
                dict(ep),
            ],
        },
    }, ensure_ascii=False), encoding="utf-8")
    cfg = cfgmod.load_config()
    eps = cfg["api_monitor"]["endpoints"]
    assert len(eps) == 1
    assert eps[0]["name"] == "OpenCode Go"


def test_get_api_state_badge_preview():
    from agentfloat.webshell.handlers import WebAppHandlers

    class Bridge:
        def __init__(self, results):
            self._r = results

        def get_snapshot(self, _key):
            return self._r

    class Widget:
        config = {
            "api_monitor": {
                "endpoints": [],
                "badge_rows": [{"title": "5h", "source": "progress:remain_pct",
                                "decimals": 0, "suffix": "%"}],
            }
        }

    results = [SimpleNamespace(
        endpoint_name="OpenCode Go",
        fields=[{"label": "滚动 5h 已用", "value": "8.0%", "unit": ""}],
        progress={"used": 8.0, "total": 100.0, "pct": 8.0, "remain": 92.0})]
    h = WebAppHandlers(Widget(), Bridge(results))
    st = h.get_api_state()
    assert st["badge_preview"] == [{"title": "5h", "value": "92%"}]
    assert st["results"] == results


def test_badge_rows_accept_serialized_dicts():
    """Web 快照是 dict（serialize_results）→ 预览必须照常工作（回归）"""
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    # 与 services/api_monitor/fetcher.serialize_results 同构
    results = [{
        "index": 0, "name": "OpenCode Go", "ok": True, "error": "",
        "fields": [{"label": "滚动 5h 已用", "value": "13.0%", "unit": "", "display": "percent"},
                   {"label": "每周已用", "value": "20.0%", "unit": "", "display": "percent"}],
        "progress": {"used": 13.0, "total": 100.0, "pct": 13.0, "remain": 87.0},
        "raw_response": "{}", "ts": "12:00:00",
    }]
    cfg = {"badge_rows": [
        {"title": "5h", "source": "progress:remain_pct", "decimals": 0, "suffix": "%"},
        {"title": "周", "source": "field_remain:每周已用", "decimals": 0, "suffix": "%"},
    ]}
    rows, low, err = build_badge_rows(results, cfg)
    assert rows == [("5h", "87%"), ("周", "80%")]
    assert err is False and low is False


def test_badge_rows_accept_serialized_error_dict():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    results = [{"index": 0, "name": "My API", "ok": False, "error": "HTTP 401: Authorization Required",
                "fields": [{"label": "错误", "value": "HTTP 401: Authorization Required", "unit": "", "display": "text"}],
                "progress": None, "raw_response": "", "ts": "12:00:00"}]
    rows, low, err = build_badge_rows(results, {"badge_rows": [{"title": "x", "source": "balance"}]})
    assert err is True
    assert rows == [("", "HTTP 401: Authorization Required")]


def test_get_api_state_badge_preview_with_serialized_results():
    from agentfloat.webshell.handlers import WebAppHandlers

    class Bridge:
        def __init__(self, results):
            self._r = results

        def get_snapshot(self, _key):
            return self._r

    class Widget:
        config = {"api_monitor": {
            "endpoints": [],
            "badge_rows": [{"title": "5h", "source": "progress:remain_pct", "decimals": 0, "suffix": "%"}],
        }}

    st = WebAppHandlers(Widget(), Bridge([{
        "index": 0, "name": "OpenCode Go", "ok": True, "error": "",
        "fields": [], "progress": {"used": 13.0, "total": 100.0, "pct": 13.0, "remain": 87.0},
        "raw_response": "", "ts": "12:00:00",
    }])).get_api_state()
    assert st["badge_preview"] == [{"title": "5h", "value": "87%"}]


def test_get_api_state_preview_single_line_mode():
    from agentfloat.webshell.handlers import WebAppHandlers

    class Bridge:
        def __init__(self, results):
            self._r = results

        def get_snapshot(self, _key):
            return self._r

    class Widget:
        config = {"api_monitor": {"endpoints": [], "badge_mode": "balance"}}

    results = [SimpleNamespace(
        endpoint_name="DeepSeek",
        fields=[{"label": "剩余额度", "value": "110.00", "unit": "元"}],
        progress=None)]
    st = WebAppHandlers(Widget(), Bridge(results)).get_api_state()
    assert st["badge_preview"] == [{"title": "", "value": "110.00元"}]
