# -*- coding: utf-8 -*-
"""AgentFloat — Web 壳后端适配层（只读状态 + 命令投递，不直接触碰 Qt）"""
import copy
import os

from agentfloat.core.autostart import is_auto_start_enabled
from agentfloat.core.config import load_config, save_config
from agentfloat.core.sysutil import _open_url
from agentfloat.core.version import VERSION
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
            "theme": getattr(self.widget, "theme", "light"),
            "dsh_running": dsh_running(),
            "news_generating": bool(getattr(self.widget, "_news_generating", False)),
            "auto_start": is_auto_start_enabled(),
            "api_enabled": bool((self.widget.config.get("api_monitor") or {}).get("enabled")),
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

    def get_news_state(self, date=None):
        """AI 快报状态（v3.9.0）：报告 + 每源结果 + 统计 + 已读/收藏 + 下次生成时间"""
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
            else:
                base["unread"] = 0
            base["next_run"] = _nf.next_run_time(cfg)
            base["starred_count"] = len(_nf.load_state().get("starred") or [])
        except Exception:  # noqa: BLE001
            base.setdefault("unread", 0)
            base.setdefault("next_run", "")
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
        """单源重试：重新抓取该源并并回当日报告（不重跑 AI）"""
        from agentfloat.services.news import fetcher as _nf
        cfg = getattr(self.widget, "_news_cfg", None) or self.widget.config.get("news") or {}
        per = max(3, min(30, int(cfg.get("per_source") or 12)))
        items, err = _nf.fetch_one(str(source_id), per_source=per)
        if err:
            return {"ok": False, "error": err, "added": 0}
        report = _nf.load_latest() or {}
        existing = report.get("items") or []
        seen = {it.get("id") or _nf.item_id(it.get("url", ""), it.get("title", ""))
                for it in existing}
        added = 0
        for it in _nf.filter_blocked(items, cfg.get("blocked_keywords")):
            iid = _nf.item_id(it.get("url", ""), it.get("title", ""))
            if iid in seen:
                continue
            seen.add(iid)
            existing.append({
                "id": iid, "title": it.get("title", "?"), "url": it.get("url", "#"),
                "category": _nf.guess_category(it.get("title", ""), it.get("url", "")),
                "summary": "", "source": it.get("source", ""), "ts": it.get("ts", 0),
            })
            added += 1
        if added:
            report["items"] = existing
            report["count"] = len(existing)
            report["source_errors"] = [e for e in (report.get("source_errors") or [])
                                       if str(source_id) not in str(e)]
            srcs = report.get("sources") or []
            for s in srcs:
                if s.get("id") == source_id:
                    s["ok"] = True
                    s["error"] = ""
                    s["count"] = int(s.get("count") or 0) + added
            report["sources"] = srcs
            stats = report.get("stats") or {}
            stats["shown"] = len(existing)
            report["stats"] = stats
            import time as _time
            date = report.get("date") or _time.strftime("%Y-%m-%d")
            _nf.save_report(date, existing, report.get("raw_md") or "",
                            report.get("language") or "zh",
                            bool(report.get("used_ai")), report.get("source_errors") or [],
                            sources=srcs, stats=stats,
                            headline=report.get("headline") or "")
        return {"ok": True, "added": added, "error": ""}

    def open_url(self, url):
        _open_url(url)
