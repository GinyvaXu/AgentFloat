# -*- coding: utf-8 -*-
"""AgentFloat — Web 壳后端适配层（只读状态 + 命令投递，不直接触碰 Qt）"""
import copy
import os
from typing import Any, Dict

from agentfloat.core.autostart import is_auto_start_enabled
from agentfloat.core.config import load_config, save_config
from agentfloat.core.sysutil import _open_url
from agentfloat.core.version import VERSION, version_label
from agentfloat.services.api_monitor.config import DEFAULTS as API_MONITOR_DEFAULTS
from agentfloat.services.dsh import is_running as dsh_running
from agentfloat.services.news.fetcher import DEFAULT_NEWS as _NEWS_DEFAULTS
from agentfloat.services.vault.accounts import VaultError


class WebAppHandlers(object):
    """Web 壳后端与主程序之间的适配层（只读状态 + 命令投递，不直接触碰 Qt）。"""

    def __init__(self, widget, bridge):
        self.widget = widget
        self.bridge = bridge
        self.version = VERSION

    def get_config(self):
        # PATCH 3.1.0：返回主进程内存中的配置（深拷贝），不再每次读文件——
        # 既避免与保存并发读到半截文件，也保证 Web 页看到最新改动
        return copy.deepcopy(getattr(self.widget, "config", None) or load_config())

    def save_config(self, cfg):
        save_config(cfg)

    def apply_config(self, cfg, changed_keys=None, timeout=3.0):
        """同步应用配置（等待 Qt 主线程 apply 完成）并回读应用后的完整配置

        PATCH 3.1.1：此前 apply 是异步投递，前端保存后立即 GET 会拿到旧配置，
        导致「切换选项无法保存」（开关被打回）。
        """
        self.bridge.command_wait("apply", {"config": cfg, "changed_keys": changed_keys or []},
                                 timeout=timeout)
        return copy.deepcopy(getattr(self.widget, "config", None) or cfg)

    def get_app_state(self):
        return {
            "version": VERSION,
            "version_label": version_label(),
            "channel": "beta" if version_label().endswith("测试版") else "stable",
            "theme": getattr(self.widget, "theme", "light"),
            "dsh_running": dsh_running(),
            "news_generating": bool(getattr(self.widget, "_news_generating", False)),
            "auto_start": is_auto_start_enabled(),
            "api_enabled": bool((self.widget.config.get("api_monitor") or {}).get("enabled")),
            "quote_stats": self.widget.quote_stats() if hasattr(self.widget, "quote_stats")
            else {"total": 0, "categories": 0},
        }

    def get_api_state(self):
        cfg = self.widget.config.get("api_monitor") or API_MONITOR_DEFAULTS
        results = self.bridge.get_snapshot("api_results")
        # PATCH 3.5.3：服务端按同一套规则生成显示框预览（设置页所见即小框所得）
        preview = []
        try:
            from agentfloat.services.api_monitor.badge_rows import build_badge_rows
            rows, _low, _err = build_badge_rows(results, cfg)
            preview = [{"title": t, "value": v} for t, v in rows]
        except Exception:  # noqa: BLE001
            preview = []
        return {
            "version": VERSION,
            "config": cfg,
            "results": results,
            "badge_preview": preview,
        }

    # ── v3.6.0：账户与密钥保险箱 ────────────────────────
    def _vault(self):
        from agentfloat.services.vault.accounts import get_store
        return get_store()

    def get_vault_state(self):
        from agentfloat.services.vault import crypto as vc
        store = self._vault()
        return {
            "accounts": store.list_accounts(),
            "unlocked": store.unlocked(),
            "active": (store.active_account() or {}).get("name") or "",
            "has_quick": store.has_quick_login(),
            "crypto": bool(vc.HAVE_CRYPTO),
            "keys_count": len(store.list_keys()) if store.unlocked() else 0,
        }

    def vault_create(self, name, password, quick=True):
        store = self._vault()
        store.create_account(name, password)
        store.login(name, password, quick=bool(quick))
        return {"ok": True, "active": store.active_account().get("name")}

    def vault_login(self, name, password, quick=True):
        store = self._vault()
        store.login(name, password, quick=bool(quick))
        return {"ok": True, "active": store.active_account().get("name")}

    def vault_quick_login(self):
        store = self._vault()
        return {"ok": bool(store.quick_login())}

    def vault_logout(self):
        self._vault().logout()
        return {"ok": True}

    def vault_set_active(self, account_id):
        return {"ok": True, "active": self._vault().set_active(account_id)}

    def vault_delete_account(self, name, password):
        self._vault().delete_account(name, password)
        return {"ok": True}

    def vault_change_password(self, name, old_password, new_password):
        self._vault().change_password(name, old_password, new_password)
        return {"ok": True}

    def vault_list_keys(self, reveal=False):
        return {"keys": self._vault().list_keys(reveal=bool(reveal))}

    def vault_set_key(self, name, value, note=""):
        store = self._vault()
        store.set_key(name, value, note)
        return {"ok": True, "keys": store.list_keys()}

    def vault_delete_key(self, name):
        store = self._vault()
        store.delete_key(name)
        return {"ok": True, "keys": store.list_keys()}

    @staticmethod
    def _default_export_path():
        import time as _t
        from agentfloat.core.paths import config_dir as _cfg_dir
        name = "AgentFloat备份_%s.afpack" % _t.strftime("%Y%m%d_%H%M")
        for folder in (os.path.join(os.path.expanduser("~"), "Desktop"),
                       os.path.expanduser("~"), _cfg_dir()):
            if os.path.isdir(folder):
                return os.path.join(folder, name)
        return name

    def vault_export(self, password, include_secrets=True, path=None):
        """导出配置+密钥为口令保护的 .afpack 单文件（默认保存到桌面）"""
        from agentfloat.services.vault import exporter
        store = self._vault()
        if not store.unlocked():
            raise VaultError("请先登录账户后再导出（密钥随账户加密保存）")
        keys = []
        if include_secrets:
            for item in store.list_keys():
                keys.append({"name": item["name"],
                             "value": store.get_key(item["name"]) or "",
                             "note": item.get("note", "")})
        cfg = copy.deepcopy(getattr(self.widget, "config", None) or load_config())
        blob = exporter.export_bundle(
            cfg, keys, password,
            account_name=(store.active_account() or {}).get("name") or "",
            app_version=self.version, include_secrets=bool(include_secrets))
        target = path or self._default_export_path()
        exporter.write_bundle(target, blob)
        return {"ok": True, "path": target, "bytes": len(blob),
                "keys": [k["name"] for k in keys]}

    def vault_import(self, data_b64=None, path=None, password="", dry_run=True,
                     apply_config=True, import_keys=True):
        """导入：dry_run=True 仅返回预览；否则合并配置并写入密钥"""
        import base64 as _b64
        from agentfloat.services.vault import exporter
        if data_b64:
            try:
                raw = _b64.b64decode(str(data_b64).encode("ascii"))
            except Exception as exc:  # noqa: BLE001
                raise VaultError("文件内容无法解析：%s" % exc) from exc
        elif path:
            raw = exporter.read_bundle(path)
        else:
            raise VaultError("请选择要导入的 .afpack 文件")
        payload = exporter.import_bundle(raw, password)
        info = exporter.describe_bundle(payload)
        if dry_run:
            return {"ok": True, "preview": info}
        applied = {"config": False, "keys": 0}
        if apply_config:
            current = copy.deepcopy(getattr(self.widget, "config", None) or load_config())
            incoming = dict(payload.get("config") or {})
            for key in ("window_x", "window_y", "snap_edge"):
                incoming.pop(key, None)          # 本机相关键不从文件覆盖
            current.update(incoming)
            self.bridge.command_wait("apply", {"config": current, "changed_keys": sorted(incoming.keys())},
                                     timeout=5.0)
            applied["config"] = True
        store = self._vault()
        if import_keys and (payload.get("secrets") or {}).get("keys"):
            if not store.unlocked():
                raise VaultError("导入密钥需要先登录账户（配置可直接导入）")
            applied["keys"] = store.import_secrets(payload["secrets"]["keys"])
        return {"ok": True, "applied": applied, "preview": info}

    def skills_workshop(self, tab="installed", query="", category=""):
        """Skill 车间（只读）：workshop.list_entries 的载荷"""
        from agentfloat.services.skills.report import workshop_payload
        return workshop_payload(tab=tab or "installed", query=query or "",
                                category=category or "")

    def skills_install(self, body=None):
        """异步安装：立即返回，前端轮询 /skills/job"""
        from agentfloat.services.skills import jobs
        body = body or {}
        return jobs.start(str(body.get("id") or ""), body.get("targets"))

    def skills_job(self):
        from agentfloat.services.skills import jobs
        return jobs.status()

    def skills_uninstall(self, body=None):
        from agentfloat.services.skills.report import uninstall_skill
        body = body or {}
        return uninstall_skill(str(body.get("id") or ""), body.get("target_id"))

    def get_catalog(self):
        """Agent 目录（只读）：内置条目 + 本机安装状态"""
        from agentfloat.services.catalog.report import catalog_payload
        return catalog_payload()

    @staticmethod
    def _catalog_spec(agent_id):
        """按 id 取合并后的 spec；不存在返回 None。"""
        from agentfloat.services.catalog.builtin import builtin_specs
        from agentfloat.services.catalog.merge import merge_layers
        aid = str(agent_id or "").strip()
        if not aid:
            return None
        return merge_layers(builtin_specs()).get(aid)

    def catalog_install(self, agent_id):
        """启动后台安装任务，立即返回（实际安装由 jobs 线程执行）。"""
        from agentfloat.services.catalog import jobs
        spec = self._catalog_spec(agent_id)
        if spec is None:
            return {"ok": False, "busy": False, "error": "未知 Agent：%s" % (agent_id or "")}
        return jobs.start(spec, "install")

    def catalog_upgrade(self, agent_id):
        """启动后台升级任务（重新全局安装）；下载型条目引导去官网。"""
        from agentfloat.services.catalog import installer, jobs
        spec = self._catalog_spec(agent_id)
        if spec is None:
            return {"ok": False, "busy": False, "error": "未知 Agent：%s" % (agent_id or "")}
        if installer.install_type(spec) not in ("npm", "pip"):
            return {"ok": False, "busy": False,
                    "error": "该条目为官网下载安装，请打开官网手动更新"}
        return jobs.start(spec, "upgrade")

    def catalog_uninstall(self, agent_id):
        """同步卸载受管前缀（不触碰系统全局安装）。"""
        from agentfloat.services.catalog import installer
        spec = self._catalog_spec(agent_id)
        if spec is None:
            return {"ok": False, "error": "未知 Agent：%s" % (agent_id or "")}
        return installer.uninstall(spec)

    def catalog_launch(self, agent_id, mode=None, workdir=None):
        """启动已安装的 Agent CLI；未显式传入的字段从本机偏好读取。"""
        from agentfloat.services.catalog import installer, prefs
        spec = self._catalog_spec(agent_id)
        if spec is None:
            return {"ok": False, "reason": "unknown-agent"}
        cfg = getattr(self.widget, "config", None) if self.widget is not None else None
        pref = prefs.get_pref(agent_id, config=cfg if isinstance(cfg, dict) else None)
        if mode is None:
            mode = pref["mode"]
        if workdir is None:
            workdir = pref["workdir"]
        return installer.launch(spec, mode=mode, workdir=workdir)

    def catalog_job(self):
        """当前安装 / 卸载 / 升级任务快照。"""
        from agentfloat.services.catalog import jobs
        return jobs.status()

    def catalog_refresh_versions(self):
        """清空版本缓存并重查已安装条目（「检查更新」按钮）。"""
        from agentfloat.services.catalog.report import catalog_payload
        return catalog_payload(refresh_versions=True)

    def catalog_get_prefs(self, agent_id):
        """读取某个 Agent 的启动偏好（窗口/后台 + 工作区）。"""
        from agentfloat.services.catalog import prefs
        aid = str(agent_id or "").strip()
        if self._catalog_spec(aid) is None:
            return {"ok": False, "error": "未知 Agent：%s" % aid}
        cfg = self.get_config()
        return {"ok": True, "id": aid, "pref": prefs.get_pref(aid, config=cfg)}

    def catalog_set_prefs(self, agent_id, mode, workdir):
        """校验并保存启动偏好；同步更新 widget 内存配置，避免下次保存被旧值覆盖。"""
        from agentfloat.services.catalog import prefs
        aid = str(agent_id or "").strip()
        if self._catalog_spec(aid) is None:
            return {"ok": False, "error": "未知 Agent：%s" % aid}
        cfg = self.get_config()
        result = prefs.set_pref(aid, mode, workdir, config=cfg)
        if result.get("ok") and self.widget is not None:
            try:
                # 尽量就地更新，保持主程序持有的 config 对象引用不变
                current = getattr(self.widget, "config", None)
                if isinstance(current, dict):
                    current["catalog"] = cfg.get("catalog")
                else:
                    self.widget.config = cfg
            except Exception:  # noqa: BLE001
                pass
        return result

    def get_news_state(self, date=None):
        """AI 日报状态（B 线）：报告 + 源注册表 + 质量/批次 + 已读收藏 + 下次生成"""
        from agentfloat.webshell.server import _news_payload
        base = _news_payload(None, date)
        cfg = getattr(self.widget, "_news_cfg", None) or self.widget.config.get("news") or _NEWS_DEFAULTS
        base["cfg"] = cfg
        base["generating"] = bool(getattr(self.widget, "_news_generating", False))
        base["phase"] = self.bridge.get_snapshot("news_phase") or ""
        base["progress"] = self.bridge.get_snapshot("news_progress") or {}
        try:
            from agentfloat.services.news import fetcher as _nf
            report = base.get("report")
            if isinstance(report, dict):
                _nf.apply_state(report)
                base["unread"] = report.get("unread", 0)
                base["quality"] = report.get("quality") or {}
                base["batch"] = report.get("batch") or {}
                base["source_health"] = report.get("source_health") or _nf.source_health(
                    report.get("sources"))
            else:
                base["unread"] = 0
                base["quality"] = {}
                base["batch"] = {}
                base["source_health"] = _nf.source_health([])
            base["source_catalog"] = _nf.source_catalog(cfg.get("sources") or [])
            base["next_run"] = _nf.next_run_time(cfg)
            base["starred_count"] = len(_nf.load_state().get("starred") or [])
        except Exception:  # noqa: BLE001
            base.setdefault("unread", 0)
            base.setdefault("next_run", "")
            base.setdefault("source_catalog", [])
            base.setdefault("source_health", {})
        return base

    def news_mark_read(self, item_id=None, read=True):
        """标记单条已读/未读；item_id 为空表示整期已读"""
        from agentfloat.services.news import fetcher as _nf
        if item_id:
            _nf.mark_read(str(item_id), bool(read))
        else:
            _nf.mark_all_read()
        # 未读数同步到浮球/托盘角标
        try:
            if hasattr(self.widget, "refresh_news_unread"):
                self.widget.refresh_news_unread()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True}

    def news_star(self, item_id):
        """收藏/取消收藏某条"""
        from agentfloat.services.news import fetcher as _nf
        _st, starred = _nf.toggle_star(str(item_id))
        return {"ok": True, "starred": bool(starred)}

    def news_export(self, date=None):
        """导出某期快报为 Markdown，返回文件路径"""
        from agentfloat.services.news import fetcher as _nf
        path, err = _nf.export_markdown(date)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "path": path}

    def news_retry_source(self, source_id):
        """单源重试：重新抓取该源并并回当日报告（不重跑 AI）。

        B 线：合并逻辑下沉到 fetcher.merge_source_retry，重复/相似项挂到
        「相关来源」，并更新源健康、批次 retries 与质量统计。
        """
        from agentfloat.services.news import fetcher as _nf
        cfg = getattr(self.widget, "_news_cfg", None) or self.widget.config.get("news") or {}
        per = max(3, min(30, int(cfg.get("per_source") or 12)))
        return _nf.retry_source_report(str(source_id), per_source=per, cfg=cfg)

    def open_url(self, url):
        _open_url(url)


# ── Skills 发现（skills.sh 榜单，10 分钟缓存）────────────────

_SKILLSH_CACHE: Dict[str, Any] = {}


def skills_discover(view: str = "trending") -> Dict[str, Any]:
    """返回 skills.sh 公开榜单；失败时返回缓存（若有）。"""
    import time

    from agentfloat.services.skills import discovery as _discovery

    view = str(view or "trending").strip().lower()
    if view not in ("all-time", "trending", "hot"):
        view = "trending"
    cached = _SKILLSH_CACHE.get(view)
    now = time.time()
    if cached and now - cached.get("ts", 0) < 600:
        return cached["payload"]
    try:
        rows = _discovery.fetch_skills_sh(view=view, limit=60)
        payload = {
            "ok": True,
            "source": "skills.sh",
            "view": view,
            "entries": rows,
            "total": len(rows),
        }
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "source": "skills.sh",
            "view": view,
            "entries": (cached or {}).get("payload", {}).get("entries", []),
            "error": str(exc)[:200],
        }
    _SKILLSH_CACHE[view] = {"ts": now, "payload": payload}
    return payload


# ── Skills：启用/停用、发现详情、榜单安装（模块级，供路由调用）──────

def skills_toggle(body=None):
    from agentfloat.services.skills.report import toggle_skill

    body = body or {}
    try:
        return toggle_skill(str(body.get("id") or ""), str(body.get("target_id") or ""),
                            bool(body.get("enabled")))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def skills_discover_detail(source: str = "", slug: str = ""):
    from agentfloat.services.skills import skillsh

    try:
        return skillsh.fetch_detail(source, slug)
    except skillsh.SkillShError as exc:
        return {"ok": False, "error": exc.message, "code": exc.code}


def skills_discover_install(body=None):
    from agentfloat.services.skills import jobs

    body = body or {}
    source = str(body.get("source") or "").strip()
    slug = str(body.get("slug") or "").strip()
    name = str(body.get("name") or "").strip()
    targets = body.get("targets")
    eid = "skillssh:%s/%s" % (source, slug)

    def runner(_entry_id, _targets):
        from agentfloat.services.skills.report import install_discovered

        return install_discovered(source, slug, _targets, name=name)

    return jobs.start(eid, targets, runner=runner)


def skills_adopt(body=None):
    from agentfloat.services.skills.report import adopt_skill

    body = body or {}
    try:
        return adopt_skill(str(body.get("id") or ""), str(body.get("target_id") or ""))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def skills_check(body=None):
    from agentfloat.services.skills.report import check_updates

    try:
        return check_updates()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def integrations_status():
    from agentfloat.services import integrations

    try:
        return integrations.status()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "mcp": {}, "skills": []}


def integrations_install(body=None):
    from agentfloat.services import integrations

    body = body or {}
    try:
        return integrations.install_skills(str(body.get("target") or "agents"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def integrations_auto(body=None):
    from agentfloat.services import integrations

    body = body or {}
    try:
        return integrations.auto_connect(str(body.get("target") or "agents"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def reveal_path(body=None):
    """打开文件所在文件夹（仅允许用户主目录内）。"""
    import os

    body = body or {}
    path = os.path.abspath(str(body.get("path") or ""))
    home = os.path.abspath(os.path.expanduser("~"))
    if not path or not os.path.exists(path):
        return {"ok": False, "error": "路径不存在"}
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if os.path.commonpath([home, folder]) != home:
        return {"ok": False, "error": "不允许打开该路径"}
    try:
        os.startfile(folder)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "path": folder}


def skills_update(body=None):
    from agentfloat.services.skills import jobs

    body = body or {}
    eid = str(body.get("id") or "")
    targets = body.get("targets")

    def runner(_entry_id, _targets):
        from agentfloat.services.skills.report import update_skill

        return update_skill(eid, _targets)

    return jobs.start(eid, targets, runner=runner)


def skills_bundle(entry_id: str = "", target_id: str = ""):
    from agentfloat.services.skills.report import inspect_bundle

    try:
        return inspect_bundle(entry_id, target_id)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def skills_backups():
    from agentfloat.services.skills.report import list_backups

    try:
        return list_backups()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "backups": []}


def skills_restore(body=None):
    from agentfloat.services.skills.report import restore_backup

    body = body or {}
    try:
        return restore_backup(str(body.get("backup") or ""), str(body.get("target_id") or ""))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def skills_diff(entry_id: str = ""):
    from agentfloat.services.skills.report import update_diff

    try:
        return update_diff(entry_id)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
