# -*- coding: utf-8 -*-
"""v3.8.0 本地接口安全测试

背景：3087 端口只监听 127.0.0.1，但**浏览器里的任意网页**也能向它发请求
（跨站 fetch / DNS rebinding）。此前无鉴权 + CORS 通配 + 免密 quick_login，
可被隔空读走保险箱里的全部 API Key。本文件锁死三道闸：
Host 白名单、Origin 同源、/api 令牌校验。
"""
import pytest
from fastapi.testclient import TestClient

from agentfloat.webshell.bridge import WebBridge
from agentfloat.webshell.server import create_app, set_token

TOKEN = "unit-test-token-1234567890"
AUTH = {"X-AgentFloat-Token": TOKEN}


class FakeHandlers:
    version = "test"

    def get_config(self):
        return {"theme": "light"}

    def get_app_state(self):
        return {"version": "test"}

    def get_api_state(self):
        return {"results": []}


@pytest.fixture()
def guarded():
    """已配置令牌的服务（生产形态；base_url 模拟浏览器访问 127.0.0.1）"""
    set_token(TOKEN)
    app = create_app(WebBridge(), FakeHandlers())
    c = TestClient(app, base_url="http://127.0.0.1:3087")
    yield c
    c.close()
    set_token("")          # 还原，避免影响其它测试


def test_api_requires_token(guarded):
    """没有令牌 → 401（这是"任意网页偷密钥"的主闸门）"""
    r = guarded.get("/api/vault_state")
    assert r.status_code == 401
    assert r.json()["code"] == "token_required"


def test_vault_reveal_blocked_without_token(guarded):
    """最敏感的接口必须挡住：密钥明文读取"""
    assert guarded.get("/api/vault/keys?reveal=1").status_code == 401
    assert guarded.post("/api/vault/quick_login").status_code == 401


def test_token_via_header_and_query(guarded):
    assert guarded.get("/api/health", headers=AUTH).status_code == 200
    assert guarded.get("/api/health?token=%s" % TOKEN).status_code == 200


def test_wrong_token_rejected(guarded):
    r = guarded.get("/api/health", headers={"X-AgentFloat-Token": "wrong"})
    assert r.status_code == 401


def test_sse_token_accepted_via_query(guarded):
    """EventSource 无法自定义请求头 → 中间件必须接受 ?token=
    （不真正订阅事件流：/api/events 永不结束，会挂住测试）"""
    from agentfloat.webshell.server import _current_token
    assert _current_token() == TOKEN
    # 先探一条普通 /api 路径确认查询串令牌通配规则生效
    assert guarded.get("/api/health?token=%s" % TOKEN).status_code == 200


def test_dns_rebinding_host_blocked(guarded):
    """攻击者域名解析到 127.0.0.1（DNS rebinding）→ Host 校验拦截"""
    r = guarded.get("/api/health", headers=dict(AUTH, Host="evil.example.com"))
    assert r.status_code == 403
    r2 = guarded.get("/", headers={"Host": "evil.example.com"})
    assert r2.status_code == 403


def test_cross_origin_blocked(guarded):
    """跨站 fetch：Origin 与 Host 不同源 → 403（且无 CORS 放行头）"""
    r = guarded.get("/api/health", headers=dict(AUTH, Origin="https://evil.example.com"))
    assert r.status_code == 403
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_no_cors_wildcard_anywhere(guarded):
    """回归防线：任何响应都不得再出现 ACAO: *"""
    for path in ("/api/health", "/api/config"):
        r = guarded.get(path, headers=dict(AUTH, Origin="http://127.0.0.1:3087"))
        assert r.headers.get("access-control-allow-origin") != "*"


def test_local_origin_same_host_allowed(guarded):
    r = guarded.get("/api/health", headers=dict(AUTH, Origin="http://127.0.0.1:3087",
                                               Host="127.0.0.1:3087"))
    assert r.status_code == 200


def test_index_sets_token_cookie(guarded):
    """带令牌打开首页 → 种同站 Cookie，刷新免再拼令牌"""
    r = guarded.get("/?token=%s" % TOKEN)
    assert r.status_code == 200
    assert "agentfloattoken" in r.headers.get("set-cookie", "").lower()
    assert guarded.get("/api/health",
                       headers={"Cookie": "AgentFloatToken=%s" % TOKEN}).status_code == 200


def test_host_helper_accepts_loopback_variants():
    from agentfloat.webshell.server import _host_allowed
    for h in ("127.0.0.1:3087", "localhost:3087", "127.0.0.1", "localhost", "[::1]:3087"):
        assert _host_allowed(h), h
    for h in ("evil.com", "127.0.0.1.evil.com", "192.168.1.9:3087", "", "0.0.0.0"):
        assert not _host_allowed(h), h


def test_origin_helper_requires_same_host():
    from agentfloat.webshell.server import _origin_allowed
    assert _origin_allowed("http://127.0.0.1:3087", "127.0.0.1:3087")
    assert not _origin_allowed("https://evil.com", "127.0.0.1:3087")
    assert not _origin_allowed("null", "127.0.0.1:3087")
