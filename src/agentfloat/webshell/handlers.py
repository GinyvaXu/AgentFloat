# -*- coding: utf-8 -*-
"""AgentFloat — Web 壳后端适配层（只读状态 + 命令投递，不直接触碰 Qt）"""
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
        return load_config()

    def save_config(self, cfg):
        save_config(cfg)

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
        return {
            "version": VERSION,
            "config": cfg,
            "results": self.bridge.get_snapshot("api_results"),
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
