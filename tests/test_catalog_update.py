# -*- coding: utf-8 -*-
"""Agent 版本检查 / 升级判定单测（注入假 runner，不联网）。"""
import pytest

from agentfloat.services.catalog import installer, report
from agentfloat.services.catalog.builtin import BUILTIN_SPECS
from agentfloat.services.catalog.merge import merge_layers


def spec(agent_id="gemini"):
    return merge_layers(BUILTIN_SPECS).get(agent_id)


@pytest.fixture(autouse=True)
def clean_cache():
    report.clear_version_cache()
    yield
    report.clear_version_cache()


def runner_ok(out, calls=None):
    def _run(cmd, timeout, cwd=None):
        if calls is not None:
            calls.append((cmd, timeout, cwd))
        return {"rc": 0, "out": out, "sec": 0.0, "timeout": False}
    return _run


def installed_managed(spec_obj, base=None):
    return {"installed": True, "source": "managed", "path": ""}


def not_installed(spec_obj, base=None):
    return {"installed": False, "source": "", "path": ""}


def test_latest_version_uses_npm_view_with_8s_timeout():
    calls = []
    got = installer.latest_version(spec(), runner=runner_ok("1.2.3\n", calls))
    assert got == "1.2.3"
    cmd, timeout, _cwd = calls[0]
    assert "npm" in cmd and "view @google/gemini-cli version" in cmd
    assert timeout == installer.DEFAULT_VERSION_TIMEOUT == 8


def test_latest_version_handles_failure_and_non_npm():
    def fail(cmd, timeout, cwd=None):
        return {"rc": 1, "out": "network down", "sec": 0.0, "timeout": False}

    assert installer.latest_version(spec(), runner=fail) == ""

    called = []

    def should_not_run(cmd, timeout, cwd=None):
        called.append(cmd)
        return {"rc": 0, "out": "9.9.9", "sec": 0.0, "timeout": False}

    assert installer.latest_version(spec("aider"), runner=should_not_run) == ""
    assert called == []


def test_current_version_managed_and_not_installed(monkeypatch):
    monkeypatch.setattr(installer, "detect", installed_managed)
    calls = []
    assert installer.current_version(spec(), runner=runner_ok("gemini 0.65.0", calls)) == "0.65.0"
    assert '--version' in calls[0][0]

    monkeypatch.setattr(installer, "detect", not_installed)
    assert installer.current_version(spec(), runner=runner_ok("1.0.0")) == ""
    assert installer.current_version(spec(), runner=runner_ok("1.0.0")) == ""


def test_update_info_semver_newer_and_same(monkeypatch):
    monkeypatch.setattr(installer, "detect", installed_managed)
    runner = runner_ok("gemini 1.2.3")
    assert installer.update_info(spec(), runner=runner, latest="1.2.4")["updateAvailable"] is True
    assert installer.update_info(spec(), runner=runner, latest="1.2.3")["updateAvailable"] is False
    assert installer.update_info(spec(), runner=runner, latest="1.0.0")["updateAvailable"] is False


def test_update_info_non_semver_falls_back_to_string_compare(monkeypatch):
    monkeypatch.setattr(installer, "current_version", lambda spec_obj, base=None, runner=None: "nightly")
    got = installer.update_info(spec(), latest="nightly-2")
    assert got["current"] == "nightly"
    assert got["updateAvailable"] is True
    assert installer.update_info(spec(), latest="nightly")["updateAvailable"] is False


def test_report_adds_version_fields_and_caches_latest(monkeypatch):
    calls = []

    def detect_one(spec_obj, base=None):
        if spec_obj.id == "gemini":
            return installed_managed(spec_obj, base)
        return not_installed(spec_obj, base)

    def fake_latest(spec_obj):
        calls.append(spec_obj.id)
        return "9.9.9"

    monkeypatch.setattr(report.installer, "detect", detect_one)
    monkeypatch.setattr(report.installer, "current_version", lambda spec_obj, base=None, runner=None: "1.0.0")

    first = report.catalog_payload(base="unused", version_fetcher=fake_latest)
    second = report.catalog_payload(base="unused", version_fetcher=fake_latest)
    assert calls == ["gemini"], "普通目录请求应命中 TTL 缓存"

    item = {i["id"]: i for i in first["items"]}["gemini"]
    assert item["currentVersion"] == "1.0.0"
    assert item["latestVersion"] == "9.9.9"
    assert item["updateAvailable"] is True
    assert {i["id"]: i for i in second["items"]}["gemini"]["latestVersion"] == "9.9.9"

    report.catalog_payload(base="unused", refresh_versions=True, version_fetcher=fake_latest)
    assert calls == ["gemini", "gemini"], "refresh_versions 应清缓存并重查"


def test_report_uninstalled_has_empty_versions(monkeypatch):
    monkeypatch.setattr(report.installer, "detect", not_installed)
    calls = []
    got = report.catalog_payload(base="unused", version_fetcher=lambda s: calls.append(s.id) or "9.9.9")
    for item in got["items"]:
        assert item["currentVersion"] == ""
        assert item["latestVersion"] == ""
        assert item["updateAvailable"] is False
    assert calls == [], "未安装条目不应触发 npm 查询"
