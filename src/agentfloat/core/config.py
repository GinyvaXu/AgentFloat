# -*- coding: utf-8 -*-
"""AgentFloat — 配置加载/保存（含损坏自愈、旧配置迁移、默认值）"""
import copy
import json
import os
import shutil
import time

from agentfloat.core.logging_setup import _log
from agentfloat.core.paths import CONFIG_PATH, _OLD_CONFIG_PATH
from agentfloat.core.registry import (
    DEFAULT_RADIAL_MENU, DEFAULT_SKILLS, default_agents,
)
from agentfloat.core.theme import DEFAULT_SIZE
from agentfloat.services.api_monitor.config import (
    DEFAULTS as API_MONITOR_DEFAULTS, SAMPLE_ENDPOINT,
)
from agentfloat.services.news.fetcher import DEFAULT_NEWS as _NEWS_DEFAULTS
from agentfloat.services.water.reminder import DEFAULT_WATER


def _default_api_monitor():
    """内置默认 API 监控配置：含脱敏示例端点，新用户开箱即用（默认不启用）"""
    cfg = copy.deepcopy(API_MONITOR_DEFAULTS)
    cfg.setdefault("endpoints", [])
    if not cfg["endpoints"]:
        cfg["endpoints"] = [copy.deepcopy(SAMPLE_ENDPOINT)]
    return cfg

def load_config():
    defaults = {
        "window_x": -1, "window_y": -1,
        "auto_start": False,
        "launch_mode": "normal",
        "widget_size": DEFAULT_SIZE,
        "opacity": 0.88,
        "working_directory": "",
        "snap_enabled": True,
        "snap_edge": "right",
        "snap_hidden": True,
        "hide_delay_ms": 800,
        "cleanup_on_quit": False,
        "check_updates": True,
        "theme": "light",
        "agents": default_agents(),
        "radial_menu": copy.deepcopy(DEFAULT_RADIAL_MENU),
        "skills": copy.deepcopy(DEFAULT_SKILLS),
        "api_monitor": _default_api_monitor(),
        "services": {"ai_first_run_done": False, "last_run": ""},
        "news": copy.deepcopy(_NEWS_DEFAULTS),
        "water": copy.deepcopy(DEFAULT_WATER),
    }
    loaded = {}

    # 尝试从当前配置路径加载
    config_sources = [CONFIG_PATH]
    # 如果旧路径存在且不同于新路径，也尝试加载并迁移
    if os.path.exists(_OLD_CONFIG_PATH) and os.path.abspath(_OLD_CONFIG_PATH) != os.path.abspath(CONFIG_PATH):
        config_sources.insert(0, _OLD_CONFIG_PATH)

    for src in config_sources:
        try:
            with open(src, "r", encoding="utf-8") as f:
                loaded.update(json.load(f))
            _log().debug("配置加载自: %s", os.path.basename(src))
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, IOError):
            _log().warning("配置加载失败: %s", os.path.basename(src))

    defaults.update(loaded)

    # ── 内置 Agent 迁移：新版本新增的内置预设自动追加（不覆盖用户已有自定义）──
    _def_agents = default_agents()
    _agents_cfg = defaults.get("agents")
    _migrated = False
    if isinstance(_agents_cfg, list):
        _have_ids = {str(a.get("id")) for a in _agents_cfg if isinstance(a, dict)}
        for _a in _def_agents:
            if _a.get("builtin") and _a.get("id") not in _have_ids:
                _agents_cfg.append(_a)
                _migrated = True
        # 旧配置补全 launcher 字段（terminal/web）
        for _a in _agents_cfg:
            if isinstance(_a, dict) and not _a.get("launcher"):
                _a["launcher"] = "terminal"
                _migrated = True
    else:
        defaults["agents"] = _def_agents
        _migrated = True
    if _migrated:
        save_config(defaults)
        _log().info("内置 Agent 迁移完成：新增 %d 个预设", len(defaults["agents"]))

    # ── 值校验：防止损坏的配置导致不可恢复状态 ──
    defaults["widget_size"] = max(30, min(200, int(defaults.get("widget_size", DEFAULT_SIZE))))
    defaults["opacity"] = max(0.1, min(1.0, float(defaults.get("opacity", 0.88))))
    defaults["launch_mode"] = defaults["launch_mode"] if defaults["launch_mode"] in ("normal", "skip_permissions") else "normal"
    defaults["theme"] = defaults["theme"] if defaults.get("theme") in ("light", "dark") else "light"

    # 首次启动时检测 Windows 系统主题
    if not loaded:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            apps_use_light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            if apps_use_light == 0:
                defaults["theme"] = "dark"
                _log().info("检测到 Windows 深色主题，自动设置为暗色模式")
        except Exception:
            pass

        # 若文件存在但解析失败，先备份损坏文件，避免覆盖导致数据丢失
        if os.path.exists(CONFIG_PATH):
            try:
                _bak = CONFIG_PATH + ".corrupt_%s.bak" % time.strftime("%Y%m%d_%H%M%S")
                shutil.copy2(CONFIG_PATH, _bak)
                _log().warning("检测到损坏配置，已备份到 %s", _bak)
            except (IOError, OSError):
                pass

        # 首次启动：自动生成默认配置文件（含示例端点），新用户开箱即用
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(defaults, f, ensure_ascii=False, indent=2)
            _log().info("首次启动，已生成默认配置: %s", CONFIG_PATH)
        except (IOError, OSError):
            pass

    # 如果从旧路径加载了数据，迁移到新路径
    if config_sources[0] == _OLD_CONFIG_PATH and loaded:
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(defaults, f, ensure_ascii=False, indent=2)
            os.remove(_OLD_CONFIG_PATH)
            _log().info("配置已迁移: %s → %s", _OLD_CONFIG_PATH, CONFIG_PATH)
        except (IOError, OSError):
            pass

    return defaults

def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        _log().debug("配置已保存 (%d 键)", len(config))
    except (IOError, OSError):
        _log().warning("配置保存失败: %s", CONFIG_PATH)
