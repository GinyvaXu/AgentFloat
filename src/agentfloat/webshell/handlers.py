# -*- coding: utf-8 -*-
"""AgentFloat — Web 壳后端适配层（只读状态 + 命令投递，不直接触碰 Qt）"""
import copy

from agentfloat.core.autostart import is_auto_start_enabled
from agentfloat.core.config import load_config, save_config
from agentfloat.core.sysutil import _open_url
from agentfloat.core.version import VERSION
from agentfloat.services.api_monitor.config import DEFAULTS as API_MONITOR_DEFAULTS
from agentfloat.services.dsh import is_running as dsh_running
from agentfloat.services.news.fetcher import DEFAULT_NEWS as _NEWS_DEFAULTS


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
