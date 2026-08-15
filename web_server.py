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
import socket
import sys
import threading
import time
from mimetypes import guess_type

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

WEB_PORT = 3087


def _locate_web_dir() -> str:
    """定位前端目录：兼容源码运行与 PyInstaller 冻结模式。"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "web"))
    candidates.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"))
    candidates.append(os.path.join(os.path.dirname(sys.executable), "web"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, "index.html")):
            return cand
    return candidates[0]


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
    from api_fetcher import FetchError, fetch_endpoint
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
    from skills_scanner import categorize_skills, default_skill_roots, scan_skills
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
    from news_fetcher import news_storage_dir
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api = APIRouter(prefix="/api")

    @api.get("/config")
    def get_config():
        return {"config": handlers.get_config()}

    @api.put("/config")
    def put_config(body: dict):
        cfg = body.get("config")
        if not isinstance(cfg, dict):
            return JSONResponse({"error": "配置格式错误"}, status_code=400)
        changed_keys = body.get("changed_keys") or []
        handlers.save_config(cfg)
        bridge.command("apply", {"config": cfg, "changed_keys": changed_keys})
        return {"ok": True}

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
    def news_read():
        bridge.command("news_read")  # 清零未读数
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

    @app.get("/")
    def index():
        return FileResponse(os.path.join(web_dir, "index.html"))

    static_dir = os.path.join(web_dir, "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        """非 API 路径回退到 index.html（SPA hash 路由用，排除静态资源）。"""
        full = os.path.join(web_dir, path)
        if os.path.isfile(full):
            ctype, _ = guess_type(full)
            return FileResponse(full, media_type=ctype)
        return FileResponse(os.path.join(web_dir, "index.html"))

    return app


def _run_server(bridge, handlers, port, debug):
    import uvicorn
    app = create_app(bridge, handlers)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="debug" if debug else "warning")


def start_server_thread(bridge, handlers, port=WEB_PORT, debug=False):
    """启动 FastAPI 后端守护线程，返回 (thread, port)。"""
    port = _find_free_port(port)
    thread = threading.Thread(
        target=_run_server, args=(bridge, handlers, port, debug), daemon=True, name="web-server"
    )
    thread.start()
    return thread, port