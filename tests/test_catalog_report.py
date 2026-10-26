# -*- coding: utf-8 -*-
"""目录只读载荷（/api/catalog）单测。"""
from agentfloat.services.catalog.report import catalog_payload


def test_payload_shape_and_ids():
    got = catalog_payload()
    assert got["ok"] is True
    assert got["count"] == len(got["items"]) == 6
    ids = {i["id"] for i in got["items"]}
    assert ids == {"opencode", "claude", "codex", "gemini", "qwen", "aider"}
    for item in got["items"]:
        assert item["command"] and item["package"] and item["installType"] in ("npm", "pip")
        assert isinstance(item["installed"], bool)
        assert item["sourceUrl"].startswith("http")


def test_payload_isolated_base_reports_not_installed(tmp_path):
    got = catalog_payload(base=str(tmp_path))
    assert all(i["installed"] in (True, False) for i in got["items"])
    # 受管前缀为空时，至少不会误报 managed
    assert all(i["installSource"] != "managed" for i in got["items"])
