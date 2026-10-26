# -*- coding: utf-8 -*-
"""安装适配器单测（不联网、不写用户目录）。"""
from agentfloat.services.catalog import installer
from agentfloat.services.catalog.builtin import BUILTIN_SPECS
from agentfloat.services.catalog.merge import merge_layers


def specs():
    return merge_layers(BUILTIN_SPECS)


def fake_ok(calls):
    def _run(cmd, timeout, cwd=None):
        calls.append(cmd)
        return {"rc": 0, "out": "", "sec": 0.0, "timeout": False}
    return _run


def test_managed_prefix(tmp_path):
    spec = specs().get("gemini")
    assert installer.managed_prefix(spec, str(tmp_path)) == str(tmp_path / "gemini")


def test_install_npm_uses_prefix_and_cache(tmp_path):
    spec = specs().get("gemini")
    calls = []
    r = installer.install(spec, base=str(tmp_path), runner=fake_ok(calls))
    assert r["ok"] is True
    assert len(calls) == 1
    assert "--prefix" in calls[0] and "@google/gemini-cli" in calls[0]
    assert ".npm-cache" in calls[0]


def test_install_pip_bootstraps_setuptools(tmp_path):
    spec = specs().get("aider")
    calls = []
    r = installer.install(spec, base=str(tmp_path), runner=fake_ok(calls))
    assert r["ok"] is True
    assert len(calls) == 3
    assert "venv" in calls[0]
    assert "setuptools" in calls[1] and "wheel" in calls[1]
    assert "aider-chat" in calls[2]


def test_install_reports_failure(tmp_path):
    spec = specs().get("gemini")

    def fail(cmd, timeout, cwd=None):
        return {"rc": 1, "out": "boom", "sec": 0.0, "timeout": False}

    r = installer.install(spec, base=str(tmp_path), runner=fail)
    assert r["ok"] is False and "boom" in r["reason"]


def test_uninstall_only_removes_managed_prefix(tmp_path):
    spec = specs().get("gemini")
    prefix = tmp_path / "gemini"
    prefix.mkdir()
    (prefix / "x.txt").write_text("1", encoding="utf-8")
    r = installer.uninstall(spec, base=str(tmp_path))
    assert r["ok"] is True and not prefix.exists()


def test_classify_probe():
    assert installer.classify_probe(0, "hi") == "ok"
    assert installer.classify_probe(1, "HTTP error: 401 Unauthorized") == "needs-login"
    assert installer.classify_probe(1, "something broke") == "error"
    assert installer.classify_probe(None, "", True) == "timeout"


def test_detect_not_installed(tmp_path):
    spec = specs().get("gemini")
    got = installer.detect(spec, base=str(tmp_path))
    assert got["installed"] is False


def test_auth_probe_unsupported_for_qwen(tmp_path):
    spec = specs().get("qwen")
    assert installer.auth_probe(spec, base=str(tmp_path)) == "unsupported"

def test_install_winget_builds_command(tmp_path):
    spec = specs().get("cursor-desktop")
    calls = []
    r = installer.install(spec, base=str(tmp_path), runner=fake_ok(calls))
    assert r["ok"] is True
    assert "winget install" in calls[0] and "Anysphere.Cursor" in calls[0]
    assert "--silent" in calls[0]


def test_install_script_builds_irm(tmp_path):
    spec = specs().get("cursor-cli")
    calls = []
    r = installer.install(spec, base=str(tmp_path), runner=fake_ok(calls))
    assert r["ok"] is True
    assert "irm" in calls[0] and "cursor.com/install" in calls[0]


def test_install_download_returns_page(tmp_path):
    spec = specs().get("goose")
    calls = []
    r = installer.install(spec, base=str(tmp_path), runner=fake_ok(calls))
    assert r["ok"] is False and r["reason"] == "download-page"
    assert r["url"].startswith("http") and calls == []
