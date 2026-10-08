# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Web 套壳后端（FastAPI + uvicorn，参考 ProjectDock 技术栈）

职责：
- 静态托管 web/ 前端（PyInstaller 冻结模式兼容 _MEIPASS/web）
- 提供配置 / Agent / API 用量 / AI 快报 / Skills / 更新检查等 JSON API
- /api/events 通过 SSE 推送 Qt 主线程事件（news_done / api_updated / theme_changed ...）
- 所有需要触碰 Qt 界面的操作一律通过 bridge.command() 投递到 Qt 主线程执行
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from mimetypes import guess_type

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agentfloat.services.vault.accounts import VaultError

WEB_PORT = 3087

# ── 本地接口访问令牌（v3.8.0）──────────────────────────────────────
# 启动时由 app.py 生成随机令牌；Web 壳窗口/浏览器带 ?token= 打开，SPA 存
# sessionStorage 并在每个请求上带 X-AgentFloat-Token（SSE 用 ?token=）。
TOKEN_COOKIE = "AgentFloatToken"
_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")
_TOKEN = ""


def set_token(token: str):
    """设置访问令牌（app.py 启动时调用；空值表示不校验——仅用于单元测试）"""
    global _TOKEN
    _TOKEN = str(token or "")


def _current_token() -> str:
    return _TOKEN


def _host_allowed(host: str) -> bool:
    """Host 白名单：仅允许本机回环（防 DNS rebinding 用攻击者域名访问本服务）"""
    if not host:
        return False
    h = host.strip()
    if h.startswith("["):                  # [::1]:3087
        h = h[1:h.find("]")] if "]" in h else h
    elif h.count(":") == 1:                # 127.0.0.1:3087 / localhost:3087
        h = h.rsplit(":", 1)[0]
    return h.strip(".").lower() in _ALLOWED_HOSTS


def _origin_allowed(origin: str, host: str) -> bool:
    """Origin 必须与请求 Host 同源（浏览器跨站请求一律拒绝）"""
    try:
        from urllib.parse import urlparse
        return urlparse(origin).netloc.lower() == host.lower()
    except Exception:  # noqa: BLE001
        return False


def _query_token_ok(request) -> bool:
    supplied = request.query_params.get("token") or ""
    return bool(_TOKEN) and secrets.compare_digest(supplied, _TOKEN)


def _locate_web_dir() -> str:
    """定位前端目录：兼容源码运行与 PyInstaller 冻结模式（收敛到 core.paths）。"""
    from agentfloat.core.paths import web_dir
    return web_dir()


def _find_free_port(start=WEB_PORT, tries=12):
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def _sse(event):
    return "data: %s\n\n" % json.dumps(event, ensure_ascii=False)


def _api_test_fetch(endpoint):
    """在服务线程中直接测试端点（纯 urllib，不触碰 Qt）。"""
    from agentfloat.services.api_monitor.fetcher import FetchError, fetch_endpoint
    try:
        res = fetch_endpoint(endpoint)
        return True, {
            "name": res.endpoint_name,
            "fields": res.fields,
            "progress": res.progress,
            "raw_response": (res.raw_response or "")[:400],
        }
    except FetchError as e:
        return False, {"error": str(e), "status_code": getattr(e, "status_code", None)}
    except Exception as e:  # noqa: BLE001
        return False, {"error": "未知错误: %s" % e}


def _skills_payload(cfg):
    from agentfloat.services.skills.scanner import categorize_skills, default_skill_roots, scan_skills
    roots = [r for r in (cfg.get("roots") or []) if str(r).strip()] or default_skill_roots()
    try:
        skills = scan_skills(roots)
    except Exception as e:  # noqa: BLE001
        return {"roots": roots, "skills": [], "categories": {}, "error": str(e)}
    cats = {}
    try:
        cats = categorize_skills(skills)
    except Exception:  # noqa: BLE001
        cats = {"全部": skills}
    items = []
    for sk in skills:
        items.append({
            "name": getattr(sk, "name", "") or (sk.get("name") if isinstance(sk, dict) else ""),
            "description": getattr(sk, "description", "") or (sk.get("description") if isinstance(sk, dict) else ""),
            "trigger": getattr(sk, "trigger", "") or (sk.get("trigger") if isinstance(sk, dict) else ""),
            "path": getattr(sk, "path", "") or (sk.get("path") if isinstance(sk, dict) else ""),
            "category": getattr(sk, "category", "") or (sk.get("category") if isinstance(sk, dict) else ""),
        })
    return {"roots": roots, "skills": items, "categories": cats}


def _news_payload(config_dir_hint=None, date=None):
    """读取快报报告（指定日期或最新）+ 历史日期列表。"""
    from agentfloat.services.news.fetcher import news_storage_dir
    d = news_storage_dir()
    report = None
    fname = "%s.json" % date if date else "latest.json"
    try:
        with open(os.path.join(d, fname), encoding="utf-8") as f:
            report = json.load(f)
    except Exception:  # noqa: BLE001
        report = None
    dates = []
    try:
        for fn in sorted(os.listdir(d), reverse=True):
            if fn.endswith(".json") and fn != "latest.json":
                dates.append(fn[:-5])
    except Exception:  # noqa: BLE001
        pass
    return {"report": report, "dates": dates[:14]}


def create_app(bridge, handlers):
    app = FastAPI(title="AgentFloat Web UI", version=getattr(handlers, "version", ""))
    api = APIRouter(prefix="/api")

    # ── 本地接口防护（v3.8.0 安全加固）──────────────────────────────
    # 背景：本服务监听 127.0.0.1，但**浏览器里的任意网页**都能向它发请求：
    #   ① 跨站 fetch（旧版 CORS allow_origins=["*"] 直接放行，可读取响应）
    #   ② DNS rebinding（攻击者域名解析到 127.0.0.1，浏览器视为同源，连 CORS 都不过）
    # 一旦被调用：POST /api/vault/quick_login 可免密解锁保险箱，
    # GET /api/vault/keys?reveal=1 会返回全部密钥明文 —— 等于钥匙被隔空取走。
    # 因此这里加三道闸：Host 白名单 → Origin 校验 → /api 令牌校验。
    @app.middleware("http")
    async def _local_guard(request, call_next):
        from starlette.responses import JSONResponse

        token = _current_token()
        if not token:
            # 未配置令牌（单元测试 / 直接调用 create_app）→ 不做校验
            return await call_next(request)

        host = (request.headers.get("host") or "").strip()
        if not _host_allowed(host):
            return JSONResponse({"error": "invalid host"}, status_code=403)

        origin = (request.headers.get("origin") or "").strip()
        if origin and not _origin_allowed(origin, host):
            return JSONResponse({"error": "cross-origin request blocked"}, status_code=403)

        path = request.url.path
        if path.startswith("/api"):
            supplied = (request.headers.get("x-agentfloat-token")
                        or request.query_params.get("token")
                        or request.cookies.get(TOKEN_COOKIE)
                        or "")
            if not secrets.compare_digest(supplied, token):
                return JSONResponse({"error": "unauthorized", "code": "token_required"},
                                    status_code=401)

        response = await call_next(request)
        # 首页带 ?token= 打开时种一个同站 Cookie，刷新/新标签页免再拼令牌
        if path in ("/", "/index.html") and _query_token_ok(request):
            response.set_cookie(TOKEN_COOKIE, token, httponly=True, samesite="strict",
                                path="/", max_age=60 * 60 * 24 * 30)
        return response

    @api.get("/config")
    def get_config():
        return {"config": handlers.get_config()}

    @api.put("/config")
    def put_config(body: dict):
        cfg = body.get("config")
        if not isinstance(cfg, dict):
            return JSONResponse({"error": "配置格式错误"}, status_code=400)
        changed_keys = body.get("changed_keys") or []
        handlers.save_config(cfg)                           # 先原子落盘（兜底）
        applied = handlers.apply_config(cfg, changed_keys)  # 同步应用并回读（PATCH 3.1.1）
        return {"ok": True, "config": applied}

    @api.post("/preview")
    def post_preview(body: dict):
        cfg = body.get("config")
        if not isinstance(cfg, dict):
            return JSONResponse({"error": "配置格式错误"}, status_code=400)
        bridge.command("preview", {"config": cfg})
        return {"ok": True}

    @api.get("/state")
    def get_state():
        return handlers.get_app_state()

    @api.get("/api_state")
    def get_api_state():
        return handlers.get_api_state()

    @api.get("/api_monitor/presets")
    def get_api_monitor_presets():
        """内置端点预设 + 余额显示行预设（PATCH 3.4.0 / 3.5.2）"""
        from agentfloat.services.api_monitor.presets import PRESETS, ROW_PRESETS
        return {"presets": PRESETS, "row_presets": ROW_PRESETS}

    @api.post("/api_monitor/refresh")
    def api_monitor_refresh():
        """PATCH 3.5.2：手动立即拉取一次（用于首次配置后立刻看到余额）"""
        bridge.command("refresh_api_monitor")
        return {"ok": True}

    # ── v3.6.0：账户与密钥保险箱 ────────────────────────
    def _vault_call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except VaultError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": "内部错误：%s" % exc}, status_code=500)

    @api.get("/vault_state")
    def vault_state():
        return _vault_call(handlers.get_vault_state)

    @api.post("/vault/create")
    def vault_create(body: dict):
        return _vault_call(handlers.vault_create, body.get("name"), body.get("password"),
                           body.get("quick", True))

    @api.post("/vault/login")
    def vault_login(body: dict):
        return _vault_call(handlers.vault_login, body.get("name"), body.get("password"),
                           body.get("quick", True))

    @api.post("/vault/quick_login")
    def vault_quick_login():
        return _vault_call(handlers.vault_quick_login)

    @api.post("/vault/logout")
    def vault_logout():
        return _vault_call(handlers.vault_logout)

    @api.post("/vault/active")
    def vault_active(body: dict):
        return _vault_call(handlers.vault_set_active, body.get("id"))

    @api.post("/vault/delete")
    def vault_delete(body: dict):
        return _vault_call(handlers.vault_delete_account, body.get("name"), body.get("password"))

    @api.post("/vault/change_password")
    def vault_change_password(body: dict):
        return _vault_call(handlers.vault_change_password, body.get("name"),
                           body.get("old_password"), body.get("new_password"))

    @api.get("/vault/keys")
    def vault_keys(reveal: int = 0):
        return _vault_call(handlers.vault_list_keys, bool(reveal))

    @api.post("/vault/keys/set")
    def vault_key_set(body: dict):
        return _vault_call(handlers.vault_set_key, body.get("name"), body.get("value"),
                           body.get("note", ""))

    @api.post("/vault/keys/delete")
    def vault_key_delete(body: dict):
        return _vault_call(handlers.vault_delete_key, body.get("name"))

    @api.post("/vault/export")
    def vault_export(body: dict):
        return _vault_call(handlers.vault_export, body.get("password"),
                           body.get("include_secrets", True), body.get("path"))

    @api.post("/vault/import")
    def vault_import(body: dict):
        return _vault_call(handlers.vault_import, body.get("data_b64"), body.get("path"),
                           body.get("password", ""), body.get("dry_run", True),
                           body.get("apply_config", True), body.get("import_keys", True))

    @api.post("/api_monitor/test")
    def api_monitor_test(body: dict):
        endpoint = body.get("endpoint")
        if not isinstance(endpoint, dict) or not (endpoint.get("url") or "").strip():
            return JSONResponse({"error": "端点配置无效"}, status_code=400)
        ok, result = _api_test_fetch(endpoint)
        return {"ok": ok, "result": result}

    @api.post("/api_monitor/restart")
    def api_monitor_restart():
        bridge.command("restart_api_monitor")
        return {"ok": True}

    @api.get("/news/state")
    def get_news_state(date: str | None = None):
        return handlers.get_news_state(date)

    @api.post("/news/generate")
    def news_generate():
        bridge.command("generate_news")
        return {"ok": True}

    @api.post("/news/read")
    def news_read(body: dict | None = None):
        """标记已读：body.item_id 为空表示整期已读；read=false 可标未读"""
        body = body or {}
        try:
            return handlers.news_mark_read(body.get("item_id"), bool(body.get("read", True)))
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @api.post("/news/star")
    def news_star(body: dict):
        try:
            return handlers.news_star(body.get("item_id"))
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @api.post("/news/export")
    def news_export(body: dict | None = None):
        try:
            return handlers.news_export((body or {}).get("date"))
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @api.post("/news/retry_source")
    def news_retry_source(body: dict):
        try:
            return handlers.news_retry_source(body.get("source_id"))
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": str(e)[:200]}, status_code=500)

    @api.post("/news/cancel")
    def news_cancel():
        bridge.command("cancel_news")
        return {"ok": True}

    @api.get("/skills")
    def get_skills():
        cfg = handlers.get_config().get("skills") or {}
        return _skills_payload(cfg)

    @api.post("/check_update")
    def check_update():
        bridge.command("check_update")
        return {"ok": True}

    @api.post("/open_url")
    def open_url(body: dict):
        url = str(body.get("url") or "").strip()
        if url:
            handlers.open_url(url)
        return {"ok": True}

    @api.post("/launch_agent")
    def launch_agent(body: dict):
        aid = str(body.get("id") or "").strip()
        if aid:
            bridge.command("launch_agent", {"id": aid})
        return {"ok": True}

    @api.post("/run_ai_services")
    def run_ai_services(body: dict):
        auto = bool(body.get("auto", False))
        bridge.command("run_ai_services", {"auto": auto})
        return {"ok": True}

    @api.post("/dsh/stop")
    def dsh_stop():
        bridge.command("stop_dsh")
        return {"ok": True}

    # ── Agent 安装服务（设置页「Agent 安装」模块）──
    @api.get("/agent_install/status")
    def agent_install_status():
        from agentfloat.services.installer import detect_all
        return {"agents": detect_all()}

    @api.post("/agent_install/install")
    def agent_install_install(body: dict):
        from agentfloat.services.installer import install_agent
        aid = str(body.get("id") or "").strip()
        action = str(body.get("action") or "install").strip()
        if action not in ("install", "upgrade"):
            action = "install"
        ok, msg = install_agent(aid, action)
        return {"ok": ok, "message": msg}

    @api.post("/agent_install/uninstall")
    def agent_install_uninstall(body: dict):
        from agentfloat.services.installer import uninstall_agent
        aid = str(body.get("id") or "").strip()
        ok, msg = uninstall_agent(aid)
        return {"ok": ok, "message": msg}

    @api.get("/agent_install/status/{aid}")
    def agent_install_status_one(aid: str):
        from agentfloat.services.installer import status_of
        st = status_of(aid)
        if st is None:
            return JSONResponse({"error": "未知 Agent"}, status_code=404)
        return st

    @api.get("/events")
    def events():
        def gen():
            for ev in bridge.iter_events():
                yield _sse(ev)
        return StreamingResponse(gen(), media_type="text/event-stream")

    @api.get("/health")
    def health():
        return {"ok": True}

    app.include_router(api)

    web_dir = _locate_web_dir()
    # v3.9.2：本地控制台禁用浏览器缓存 —— 否则升级后前端资源要等约 4 小时或 Ctrl+F5 才更新
    NO_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}

    @app.get("/")
    def index():
        return FileResponse(os.path.join(web_dir, "index.html"), headers=NO_CACHE)

    static_dir = os.path.join(web_dir, "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        """非 API 路径回退到 index.html（SPA hash 路由用，排除静态资源）。"""
        full = os.path.join(web_dir, path)
        if os.path.isfile(full):
            ctype, _ = guess_type(full)
            return FileResponse(full, media_type=ctype, headers=NO_CACHE)
        return FileResponse(os.path.join(web_dir, "index.html"), headers=NO_CACHE)

    return app


def _run_server(bridge, handlers, port, debug):
    """后台线程：启动 uvicorn；任何异常写入 AgentFloat 日志（不再静默吞掉）。"""
    import logging
    logger = logging.getLogger("AgentFloat.WebServer")
    try:
        import uvicorn
        app = create_app(bridge, handlers)
        # log_config=None：禁用 uvicorn 的 logging.config.dictConfig。
        # uvicorn 0.52 在 PyInstaller 冻结环境下配置自身 formatter 会抛
        # "ValueError: Unable to configure formatter 'default'" 导致后端启动失败，
        # 设置页因此报 127.0.0.1 拒绝访问；禁用后日志走 AgentFloat 自身 logger。
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", log_config=None)
    except Exception as e:  # noqa: BLE001
        import traceback
        logger.error("Web 后端启动失败 (port=%s): %s", port, e)
        for line in traceback.format_exc().splitlines():
            logger.error("  | %s", line)


def start_server_thread(bridge, handlers, port=WEB_PORT, debug=False, wait_ready=True):
    """启动 FastAPI 后端守护线程。

    返回 (thread, port, ok)：
    - wait_ready=True 时等待端口真正就绪（最多 6 秒），ok 表示是否成功监听；
    - wait_ready=False 时立即返回（ok 恒为 False，调用方自行轮询）。
    """
    port = _find_free_port(port)
    thread = threading.Thread(
        target=_run_server, args=(bridge, handlers, port, debug), daemon=True, name="web-server"
    )
    thread.start()
    ok = False
    if wait_ready:
        deadline = time.time() + 6.0
        while time.time() < deadline and thread.is_alive():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    s.connect(("127.0.0.1", port))
                    ok = True
                    break
            except OSError:
                time.sleep(0.2)
    return thread, port, ok
