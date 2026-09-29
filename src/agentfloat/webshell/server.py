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
import threading
import time
from mimetypes import guess_type

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from agentfloat.services.vault.accounts import VaultError

WEB_PORT = 3087


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
