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
    tag, url, notes, sha = up._from_release_api({
        "tag_name": "v2.0.0",
        "assets": [{"name": "AgentFloat_Setup.exe", "browser_download_url": "https://x/y.exe"}],
        "body": "release notes",
    })
    assert tag == "2.0.0"
    assert isinstance(url, str)
    assert notes == "release notes"
    assert sha == ""                      # 无 digest → 空（旧资产）
    with pytest.raises(ValueError):
        up._from_release_api({})


def test_from_release_api_picks_setup_and_digest():
    """多资产时优先 Setup，并带上 SHA256（v3.8.0 完整性校验用）"""
    tag, url, _notes, sha = up._from_release_api({
        "tag_name": "v3.8.0",
        "assets": [
            {"name": "AgentFloat.exe", "browser_download_url": "https://x/portable.exe",
             "digest": "sha256:aaaa"},
            {"name": "AgentFloat-Setup-3.8.0.exe",
             "browser_download_url": "https://x/setup.exe", "digest": "sha256:BBBBcc"},
        ],
    })
    assert tag == "3.8.0" and url.endswith("setup.exe")
    assert sha == "bbbbcc"                 # 归一化小写


def test_asset_sha256_helper():
    assert up._asset_sha256({"digest": "sha256:AbC"}) == "abc"
    assert up._asset_sha256({"digest": ""}) == ""
    assert up._asset_sha256({}) == ""


def test_sha256_file(tmp_path):
    import hashlib
    p = tmp_path / "a.bin"
    p.write_bytes(b"agentfloat")
    assert up.sha256_file(str(p)) == hashlib.sha256(b"agentfloat").hexdigest()


def test_download_installer_verifies_sha256(tmp_path, monkeypatch):
    """校验通过才返回；不匹配必须删文件并抛错（防投毒镜像）"""
    payload = b"FAKE-SETUP-BYTES"
    good = up.sha256_file.__wrapped__ if hasattr(up.sha256_file, "__wrapped__") else None
    import hashlib
    good = hashlib.sha256(payload).hexdigest()

    def fake_download(url, path, timeout, progress):
        with open(path, "wb") as f:
            f.write(payload)

    monkeypatch.setattr(up, "_download_once", fake_download)
    monkeypatch.setattr(up, "mirror_urls", lambda u: [u])
    monkeypatch.setattr(up, "custom_mirror", lambda: {})

    ok = up.download_installer("https://x/AgentFloat-Setup.exe", dest_dir=str(tmp_path),
                               expected_sha256=good)
    assert ok.endswith("AgentFloat-Setup.exe") and os.path.isfile(ok)

    with pytest.raises(ValueError) as ei:
        up.download_installer("https://x/AgentFloat-Setup.exe", dest_dir=str(tmp_path),
                              expected_sha256="0" * 64)
    assert "校验失败" in str(ei.value)
    assert not os.path.isfile(os.path.join(str(tmp_path), "AgentFloat-Setup.exe"))


def test_download_installer_without_hash_warns_but_works(tmp_path, monkeypatch, caplog):
    """来源未提供哈希时仍可下载（仅告警），不阻塞老版本升级"""
    def fake_download(url, path, timeout, progress):
        with open(path, "wb") as f:
            f.write(b"x")

    monkeypatch.setattr(up, "_download_once", fake_download)
    monkeypatch.setattr(up, "mirror_urls", lambda u: [u])
    monkeypatch.setattr(up, "custom_mirror", lambda: {})
    p = up.download_installer("https://x/AgentFloat-Setup.exe", dest_dir=str(tmp_path))
    assert os.path.isfile(p)


def test_r2_manifest_parsing():
    """v3.9.0：自有镜像（Cloudflare R2）作为首选更新源"""
    r = up._result_from_r2_manifest({
        "project": "agentfloat",
        "tag": "v3.9.0",
        "updatedAt": "2026-10-08T00:00:00Z",
        "base": "https://dl.ginyva.site/releases/agentfloat/latest/",
        "files": [{"name": "notes.txt", "size": 10, "sha256": "aaa"},
                  {"name": "AgentFloat-Setup-3.9.0.exe", "size": 43000000,
                   "sha256": "B24B"}],
    }, "3.8.0")
    assert r["version"] == "3.9.0" and r["available"] is True
    assert r["url"] == ("https://dl.ginyva.site/releases/agentfloat/latest/"
                        "AgentFloat-Setup-3.9.0.exe"), "应优先挑 Setup 安装包"
    assert r["sha256"] == "b24b", "sha256 归一化小写"
    assert r["source"] == "r2" and r["size"] == 43000000

    for bad in ({}, {"tag": "v3.9.0"}, {"tag": "v3.9.0", "base": "u"}):
        with pytest.raises(ValueError):
            up._result_from_r2_manifest(bad, "3.8.0")


def test_r2_source_is_first_priority():
    """R2 必须排在源列表首位（同版本时优先命中，且免代理最快）"""
    assert up.MANIFEST_SOURCES[0][0] == "r2"
    assert "dl.ginyva.site" in up.MANIFEST_SOURCES[0][1]


def test_merge_best_prefers_first_max_and_fills_fields():
    """同版本时取先出现者（R2），并用其它源补齐 notes/sha256"""
    r2 = {"version": "3.9.0", "available": True, "url": "https://dl/new.exe",
          "sha256": "abc", "notes": "", "notes_zh": "", "source": "r2",
          "current": "3.8.0", "error": None, "detail": ""}
    raw = {"version": "3.9.0", "available": True, "url": "https://gh/new.exe",
           "sha256": "", "notes": "N", "notes_zh": "中文更新说明", "source": "raw",
           "current": "3.8.0", "error": None, "detail": ""}
    m = up._merge_best([r2, raw])
    assert m["url"].startswith("https://dl/"), "同版本应保留先出现者（R2 的 URL）"
    assert m["sha256"] == "abc"
    assert m["notes"] == "N" and m["notes_zh"] == "中文更新说明"

    # 版本更高者胜出，即使它排在后面
    hi = dict(raw, version="3.10.0", url="https://hi/x.exe")
    assert up._merge_best([r2, hi])["version"] == "3.10.0"


def test_mirror_urls_does_not_wrap_non_github():
    """R2 直链不应被套上 GitHub 代理"""
    r2url = "https://dl.ginyva.site/releases/agentfloat/latest/AgentFloat-Setup-3.9.0.exe"
    assert up.mirror_urls(r2url) == [r2url]


def test_result_from_manifest():
    r = up._result_from_manifest(
        {"version": "9.9.9", "url": "u", "notes": "a\r\nb", "notes_zh": "中\r\n文",
         "sha256": "ABCDEF"},
        "1.0.0")
    assert r["available"] is True
    assert r["notes"] == "a\nb" and r["notes_zh"] == "中\n文"
    assert r["sha256"] == "abcdef"        # 归一化，供下载校验
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
