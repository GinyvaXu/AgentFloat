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
        from agentfloat.webshell.server import _news_payload
        base = _news_payload(None, date)
        cfg = getattr(self.widget, "_news_cfg", None) or self.widget.config.get("news") or _NEWS_DEFAULTS
        base["cfg"] = cfg
        base["generating"] = bool(getattr(self.widget, "_news_generating", False))
        base["phase"] = self.bridge.get_snapshot("news_phase") or ""
        return base

    def open_url(self, url):
        _open_url(url)
