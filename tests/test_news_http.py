# -*- coding: utf-8 -*-
"""AI 快报网络抓取测试（本地 HTTP 服务器）：_http / RSS 解析 / fetch_all 并发与容错"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentfloat.services.news import fetcher as nf

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>测试频道</title>
  <item>
    <title>条目一</title>
    <link>https://example.com/a1</link>
    <pubDate>Wed, 01 Jan 2026 00:00:00 GMT</pubDate>
    <description>摘要一</description>
  </item>
  <item>
    <title>条目二</title>
    <link>https://example.com/a2</link>
    <pubDate>Thu, 02 Jan 2026 00:00:00 GMT</pubDate>
    <description>摘要二</description>
  </item>
</channel></rss>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/rss"):
            body = _RSS.encode("utf-8")
            ctype = "application/rss+xml"
        elif self.path.startswith("/json"):
            body = json.dumps({"a": 1}).encode("utf-8")
            ctype = "application/json"
        else:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
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


def test_http_json(local_server):
    assert nf._http_json(local_server + "/json") == {"a": 1}


def test_http_get_error(local_server):
    with pytest.raises(Exception):
        nf._http_get(local_server + "/bad")


def test_fetch_rss_parses_items(local_server):
    items = nf._fetch_rss(local_server + "/rss", "测试源", limit=10)
    assert len(items) == 2
    assert items[0]["title"] == "条目一"
    assert items[0]["url"] == "https://example.com/a1"
    assert items[0]["source"] == "测试源"
    assert items[0]["ts"] > 1700000000


def test_fetch_rss_limit(local_server):
    items = nf._fetch_rss(local_server + "/rss", "测试源", limit=1)
    assert len(items) == 1


def test_fetch_all_stubbed(monkeypatch):
    fake = [{
        "id": "x", "name": "X源", "zh": "X",
        "fetch": lambda limit: [{"title": "t1", "url": "u1", "ts": 2},
                                {"title": "t2", "url": "u2", "ts": 1}],
    }]
    monkeypatch.setattr(nf, "SOURCES", fake)
    monkeypatch.setattr(nf, "SOURCE_MAP", {s["id"]: s for s in fake})
    items, errors = nf.fetch_all(["x"], per_source=5, timeout=3)
    assert [i["title"] for i in items] == ["t1", "t2"]
    assert errors == []


def test_fetch_all_source_error(monkeypatch):
    def boom(limit):
        raise RuntimeError("抓取炸了")
    fake = [{"id": "x", "name": "X源", "zh": "X", "fetch": boom}]
    monkeypatch.setattr(nf, "SOURCES", fake)
    monkeypatch.setattr(nf, "SOURCE_MAP", {s["id"]: s for s in fake})
    items, errors = nf.fetch_all(["x"], per_source=5, timeout=3)
    assert items == []
    assert errors and errors[0].startswith("X源")


def test_fetch_all_empty(monkeypatch):
    monkeypatch.setattr(nf, "SOURCE_MAP", {})
    assert nf.fetch_all([]) == ([], [])
