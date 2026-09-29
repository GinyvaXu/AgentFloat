# -*- coding: utf-8 -*-
"""多平台预设 + 余额显示行预设 + 手动立即拉取（PATCH 3.5.2）"""

from types import SimpleNamespace


def test_endpoint_presets_cover_platforms():
    from agentfloat.services.api_monitor.presets import PRESETS
    by_id = {p["id"]: p for p in PRESETS}
    for pid in ("opencode-go", "deepseek", "moonshot", "siliconflow", "openrouter"):
        assert pid in by_id, pid
        ep = by_id[pid]["endpoint"]
        assert ep["url"].startswith("http")
        assert ep["fields"], pid


def test_row_presets_valid_and_match_endpoints():
    from agentfloat.services.api_monitor.presets import PRESETS, ROW_PRESETS
    ep_names = {p["endpoint"]["name"] for p in PRESETS}
    assert len(ROW_PRESETS) >= 5
    for rp in ROW_PRESETS:
        assert rp["id"] and rp["name"] and rp["rows"]
        if rp["endpoint"]:
            assert rp["endpoint"] in ep_names, rp["id"]
        for row in rp["rows"]:
            src = row["source"]
            assert src == "balance" or src.startswith(("progress:", "field:", "field_remain:"))


def test_opencode_go_rows_resolve():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    from agentfloat.services.api_monitor.presets import ROW_PRESETS
    rp = next(r for r in ROW_PRESETS if r["id"] == "opencode-go")
    res = [SimpleNamespace(
        endpoint_name="OpenCode Go",
        fields=[{"label": "滚动 5h 已用", "value": "8.0%", "unit": ""},
                {"label": "每周已用", "value": "14.0%", "unit": ""},
                {"label": "每月已用", "value": "17.0%", "unit": ""}],
        progress={"used": 8.0, "total": 100.0, "pct": 8.0, "remain": 92.0})]
    rows, _low, _err = build_badge_rows(res, {"badge_rows": rp["rows"]})
    assert rows == [("5h", "92%"), ("周", "86%"), ("月", "83%")]


def test_deepseek_rows_resolve():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    from agentfloat.services.api_monitor.presets import ROW_PRESETS
    rp = next(r for r in ROW_PRESETS if r["id"] == "deepseek")
    res = [SimpleNamespace(endpoint_name="DeepSeek",
                           fields=[{"label": "剩余额度", "value": "110.00", "unit": "元"}],
                           progress=None)]
    rows, _low, _err = build_badge_rows(res, {"badge_rows": rp["rows"]})
    assert rows == [("余额", "110.00元")]


def test_openrouter_rows_resolve():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    from agentfloat.services.api_monitor.presets import ROW_PRESETS
    rp = next(r for r in ROW_PRESETS if r["id"] == "openrouter")
    res = [SimpleNamespace(endpoint_name="OpenRouter",
                           fields=[{"label": "总额度", "value": 10.0, "unit": "$"}],
                           progress={"used": 3.5, "total": 10.0, "pct": 35.0, "remain": 65.0})]
    rows, _low, _err = build_badge_rows(res, {"badge_rows": rp["rows"]})
    assert rows == [("余额", "$6.50"), ("已用", "35.0%")]


def test_field_remain_and_remain_value_sources():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    res = [SimpleNamespace(endpoint_name="X",
                           fields=[{"label": "每周已用", "value": "14.0%"}],
                           progress={"used": 3.0, "total": 12.0, "pct": 25.0, "remain": 75.0})]
    cfg = {"badge_rows": [
        {"title": "周", "source": "field_remain:每周已用", "decimals": 0},
        {"title": "剩", "source": "progress:remain_value", "decimals": 1, "prefix": "$"},
    ]}
    rows, _low, _err = build_badge_rows(res, cfg)
    assert rows == [("周", "86%"), ("剩", "$9.0")]


def test_worker_request_refresh_flag():
    from agentfloat.services.api_monitor.worker import ApiMonitorWorker
    w = ApiMonitorWorker([], interval_seconds=60)
    assert w._refresh_now is False
    w.request_refresh()
    assert w._refresh_now is True


def test_floatball_refresh_api_monitor():
    from agentfloat.ui.floatball import FloatingWidget

    class _W:
        _api_worker = None
        restarted = False

        def _restart_api_monitor(self):
            self.restarted = True

    class _Worker:
        hit = False
        def isRunning(self):
            return True
        def request_refresh(self):
            self.hit = True

    w = _W()
    assert FloatingWidget.refresh_api_monitor(w) is False      # 未启动且重启后仍无 worker
    assert w.restarted

    w2 = _W()
    w2._api_worker = _Worker()
    assert FloatingWidget.refresh_api_monitor(w2) is True
    assert w2._api_worker.hit is True
