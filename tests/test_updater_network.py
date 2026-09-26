# -*- coding: utf-8 -*-
"""自动更新网络流测试（本地 HTTP 服务器，无外网依赖）：manifest 探测 / 并行取最高版本 / 失败降级"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentfloat.services.update import updater as up


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/manifest_old"):
            payload = {"version": "1.0.0", "url": "https://x/old.exe", "notes": "old"}
        elif self.path.startswith("/manifest"):
            payload = {"version": "9.9.9", "url": "https://x/Setup.exe",
                       "notes": "new", "notes_zh": "中文说明"}
        else:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        body = json.dumps(payload).encode("utf-8")
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


def test_check_for_update_custom_mirror(local_server, monkeypatch):
    monkeypatch.setattr(up, "custom_mirror",
                        lambda: {"manifest": local_server + "/manifest", "installer": ""})
    res = up.check_for_update("1.0.0", timeout=5)
    assert res["available"] is True
    assert res["version"] == "9.9.9"
    assert res["notes_zh"] == "中文说明"


def test_check_parallel_picks_highest(local_server, monkeypatch):
    monkeypatch.setattr(up, "custom_mirror", lambda: {})
    monkeypatch.setattr(up, "MANIFEST_SOURCES", [
        ("manifest", local_server + "/manifest_old"),
        ("manifest", local_server + "/manifest"),
    ])
    res = up.check_for_update("1.0.0", timeout=5)
    assert res["available"] is True and res["version"] == "9.9.9"


def test_check_all_sources_fail(local_server, monkeypatch):
    monkeypatch.setattr(up, "custom_mirror", lambda: {})
    monkeypatch.setattr(up, "MANIFEST_SOURCES", [("manifest", local_server + "/bad")])
    res = up.check_for_update("1.0.0", timeout=5)
    assert res["available"] is False
    assert res["error"] in ("network", "unknown", "timeout")
    assert res["detail"]


def test_custom_mirror_falls_back_to_builtin(local_server, monkeypatch):
    """自建镜像 manifest 不可达 → 回退内置源（此处内置源同样指向本地坏路径，验证不抛异常）"""
    monkeypatch.setattr(up, "custom_mirror",
                        lambda: {"manifest": local_server + "/bad", "installer": ""})
    monkeypatch.setattr(up, "MANIFEST_SOURCES", [("manifest", local_server + "/bad")])
    res = up.check_for_update("1.0.0", timeout=5)
    assert res["available"] is False and res["error"]


def test_probe_one_api_kind(local_server, monkeypatch):
    """api 类型源（GitHub Releases API 响应格式）"""
    def fake_fetch(url, timeout):
        return json.dumps({
            "tag_name": "v3.0.0",
            "assets": [{"name": "AgentFloat_Setup.exe",
                        "browser_download_url": "https://x/dl.exe"}],
            "body": "notes",
        }).encode("utf-8")
    monkeypatch.setattr(up, "_fetch", fake_fetch)
    ok, payload = up._probe_one("api", "https://api.example/x", 3, "1.0.0")
    assert ok is True and payload["version"] == "3.0.0" and payload["available"] is True
