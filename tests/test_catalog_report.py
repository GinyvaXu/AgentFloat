# -*- coding: utf-8 -*-
"""目录只读载荷（/api/catalog）单测。"""
from agentfloat.services.catalog.report import catalog_payload

EXPECTED = {"opencode", "claude", "codex", "gemini", "qwen", "aider", "pi", "dsh",
            "opencode-desktop"}


def test_payload_shape_and_ids():
    got = catalog_payload(version_fetcher=lambda spec: "")
    assert got["ok"] is True
    assert got["count"] == len(got["items"]) == len(EXPECTED)
    ids = {i["id"] for i in got["items"]}
    assert ids == EXPECTED
    for item in got["items"]:
        assert item["command"] and item["package"]
        assert item["installType"] in ("npm", "pip", "download")
        assert isinstance(item["installed"], bool)
        assert item["sourceUrl"].startswith("http")
        assert isinstance(item["updateAvailable"], bool)
        assert "currentVersion" in item and "latestVersion" in item


def test_payload_isolated_base_reports_not_installed(tmp_path):
    got = catalog_payload(base=str(tmp_path), version_fetcher=lambda spec: "")
    assert all(i["installed"] in (True, False) for i in got["items"])
    assert all(i["installSource"] != "managed" for i in got["items"])
