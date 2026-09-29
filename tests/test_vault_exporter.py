# -*- coding: utf-8 -*-
"""v3.6.0 配置/密钥导出导入（.afpack）测试"""

import pytest

from agentfloat.services.vault import crypto, exporter


CFG = {
    "theme": "dark",
    "window_x": 100, "window_y": 200, "snap_edge": "right",
    "widget_size": 60,
    "agents": [{"id": "claude", "name": "Claude Code", "command": "claude"}],
    "api_monitor": {"enabled": True, "endpoints": [{"name": "OpenCode Go", "url": "https://x"}]},
}
KEYS = [
    {"name": "OPENCODE_GO_API_KEY", "value": "sk-abcdefghijklmnop", "note": "Go"},
    {"name": "DEEPSEEK_API_KEY", "value": "sk-0123456789abcdef", "note": ""},
]


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_export_import_roundtrip():
    blob = exporter.export_bundle(CFG, KEYS, "pw-123456", account_name="alice", app_version="3.6.0")
    assert blob.startswith(exporter.BUNDLE_MAGIC)
    assert b"sk-abcdefghijklmnop" not in blob          # 密文里不含明文
    payload = exporter.import_bundle(blob, "pw-123456")
    assert payload["format"] == exporter.BUNDLE_FORMAT
    assert payload["account"]["name"] == "alice"
    assert payload["app_version"] == "3.6.0"
    # 机器相关键被剥离
    assert "window_x" not in payload["config"] and "snap_edge" not in payload["config"]
    assert payload["config"]["theme"] == "dark"
    assert payload["config"]["agents"][0]["name"] == "Claude Code"
    assert [k["name"] for k in payload["secrets"]["keys"]] == ["OPENCODE_GO_API_KEY", "DEEPSEEK_API_KEY"]
    assert payload["secrets"]["keys"][0]["value"] == "sk-abcdefghijklmnop"


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_wrong_password_and_corrupt():
    blob = exporter.export_bundle(CFG, KEYS, "pw-123456")
    with pytest.raises(exporter.BundleError):
        exporter.import_bundle(blob, "pw-654321")
    bad = bytearray(blob)
    bad[20] ^= 0xFF
    with pytest.raises(exporter.BundleError):
        exporter.import_bundle(bytes(bad), "pw-123456")
    with pytest.raises(exporter.BundleError):
        exporter.import_bundle(b"NOTABUNDLE" + b"\x00" * 40, "pw-123456")


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_export_without_secrets_and_keep_local():
    blob = exporter.export_bundle(CFG, KEYS, "pw-123456", include_secrets=False, keep_local=True)
    payload = exporter.import_bundle(blob, "pw-123456")
    assert payload["secrets"]["keys"] == []
    assert payload["config"]["window_x"] == 100


def test_export_password_rules():
    with pytest.raises(exporter.BundleError):
        exporter.export_bundle(CFG, KEYS, "")
    with pytest.raises(exporter.BundleError):
        exporter.export_bundle(CFG, KEYS, "12345")
    with pytest.raises(exporter.BundleError):
        exporter.export_bundle(CFG, KEYS, None)


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_describe_bundle():
    blob = exporter.export_bundle(CFG, KEYS, "pw-123456", account_name="alice", app_version="3.6.0")
    info = exporter.describe_bundle(exporter.import_bundle(blob, "pw-123456"))
    assert info["account"] == "alice"
    assert info["agents"] == 1
    assert info["endpoints"] == 1
    assert info["keys"] == ["OPENCODE_GO_API_KEY", "DEEPSEEK_API_KEY"]


def test_sanitize_config_does_not_mutate_source():
    original = dict(CFG)
    out = exporter.sanitize_config(CFG)
    assert CFG == original
    assert "window_x" not in out
