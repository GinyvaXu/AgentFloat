# -*- coding: utf-8 -*-
"""自动更新测试：版本比较 / 错误码 / 镜像 URL / manifest 转换 / 标志文件 / 进程检测"""
import json
import os
import time
import urllib.error

import pytest

from agentfloat.services.update import updater as up


def test_parse_version():
    assert up.parse_version("v1.2.2") == (1, 2, 2)
    assert up.parse_version("1.2.2-rc1") == (1, 2, 2)
    assert up.parse_version("2") == (2, 0, 0)
    assert up.parse_version("bad") == (0, 0, 0)


def test_is_newer():
    assert up.is_newer("1.2.3", "1.2.2")
    assert not up.is_newer("1.2.2", "1.2.2")
    assert up.is_newer((2, 0, 0), (1, 9, 9))


def test_error_code():
    assert up.error_code(TimeoutError()) == "timeout"
    assert up.error_code(urllib.error.URLError("x")) == "network"
    assert up.error_code(ValueError("x")) == "unknown"


def test_mirror_urls():
    assert up.mirror_urls("") == []
    plain = "https://example.com/a.exe"
    assert up.mirror_urls(plain) == [plain]
    gh = up.mirror_urls("https://github.com/o/r/releases/download/v1/x.exe")
    assert gh[0].startswith("https://github.com/") and len(gh) > 1


def test_from_release_api():
    tag, url, notes = up._from_release_api({
        "tag_name": "v2.0.0",
        "assets": [{"name": "AgentFloat_Setup.exe", "browser_download_url": "https://x/y.exe"}],
        "body": "release notes",
    })
    assert tag == "2.0.0"
    assert isinstance(url, str)
    assert notes == "release notes"
    with pytest.raises(ValueError):
        up._from_release_api({})


def test_result_from_manifest():
    r = up._result_from_manifest(
        {"version": "9.9.9", "url": "u", "notes": "a\r\nb", "notes_zh": "中\r\n文"},
        "1.0.0")
    assert r["available"] is True
    assert r["notes"] == "a\nb" and r["notes_zh"] == "中\n文"
    with pytest.raises(ValueError):
        up._result_from_manifest({}, "1.0.0")


def test_custom_mirror(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "app_dir", lambda: str(tmp_path))
    (tmp_path / "mirror.json").write_text(
        json.dumps({"manifest": " https://m/x ", "installer": "https://m/i"}), encoding="utf-8")
    m = up.custom_mirror()
    assert m["manifest"] == "https://m/x" and m["installer"] == "https://m/i"
    (tmp_path / "mirror.json").write_text("[]", encoding="utf-8")
    assert up.custom_mirror() == {}


def test_pending_flag_state(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "download_dir", lambda: str(tmp_path))
    assert up._pending_flag_state() == (None, 0.0)
    (tmp_path / "update_pending.flag").write_text(
        "pid=%d\nts=%.3f\n" % (os.getpid(), time.time()), encoding="ascii")
    pid, age = up._pending_flag_state()
    assert pid == os.getpid()
    assert -1.0 < age < 10.0, "age 允许微小负值（时间戳精度）"


def test_flag_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "download_dir", lambda: str(tmp_path))
    assert up._flag_is_stale(None, 0.0) is True
    assert up._flag_is_stale(os.getpid(), 1.0) is False     # 存活且未过期
    assert up._flag_is_stale(os.getpid(), 10 ** 6) is True  # 超时
    assert up._flag_is_stale(999999999, 1.0) is True        # 进程不存在


def test_pid_alive():
    assert up._pid_alive(os.getpid()) is True
    assert up._pid_alive(999999999) is False
    assert up._pid_alive(None) is False


def test_mark_boot_ok(tmp_path, monkeypatch):
    marker = tmp_path / "boot_ok.flag"
    monkeypatch.setattr(up, "boot_marker", lambda: str(marker))
    monkeypatch.setattr(up, "download_dir", lambda: str(tmp_path))
    up.mark_boot_ok()
    assert marker.exists()
