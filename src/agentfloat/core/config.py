# -*- coding: utf-8 -*-
"""AgentFloat — 配置加载/保存（含损坏自愈、旧配置迁移、默认值）

PATCH 3.1.0（配置安全）：
- 保存改为**原子写入**（同目录临时文件 + os.replace）：读取方永远看到完整文件；
- 读取失败自动重试（防读到正在写入的文件）；
- 只有「文件不存在」才算首次启动；解析失败只备份、**绝不覆盖**原文件，
  避免"保存与读取并发 → 误判损坏 → 用户配置被清空"（v3.0.x 真实事故）；
- 进程内读写加锁，串行化 Web 线程与 Qt 线程。
"""
import copy
import json
import os
import shutil
import threading
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

_LOCK = threading.RLock()          # 同进程读写串行化（Web 线程 / Qt 线程）
_READ_RETRIES = 3                  # 读取失败重试次数（防写读并发）
_READ_RETRY_DELAY = 0.06           # 重试间隔（秒）


def _read_json(path):
    """读取 JSON 文件；失败时短暂重试。返回 (data|None, error|"missing"|None)"""
    last_err = None
    for _attempt in range(_READ_RETRIES):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), None
        except FileNotFoundError:
            return None, "missing"
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            last_err = e
            time.sleep(_READ_RETRY_DELAY)
    return None, last_err



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
        # PATCH 3.5.0：Agent 进程面板（悬停浮球弹出）
        "process_panel": {"enabled": True, "hover_delay_ms": 250},
    }
    loaded = {}
    parse_error = False

    # 尝试从当前配置路径加载
    config_sources = [CONFIG_PATH]
    # 如果旧路径存在且不同于新路径，也尝试加载并迁移
    if os.path.exists(_OLD_CONFIG_PATH) and os.path.abspath(_OLD_CONFIG_PATH) != os.path.abspath(CONFIG_PATH):
        config_sources.insert(0, _OLD_CONFIG_PATH)

    with _LOCK:
        for src in config_sources:
            data, err = _read_json(src)
            if data is not None:
                loaded.update(data)
                _log().debug("配置加载自: %s", os.path.basename(src))
            elif err != "missing":
                parse_error = True
                _log().warning("配置解析失败: %s", os.path.basename(src))

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

    # ── 环绕菜单手感迁移（PATCH 3.2.0）：旧默认时延 → 灵敏档 + 按住选环 ──
    _rm = defaults.get("radial_menu")
    if isinstance(_rm, dict):
        try:
            if int(_rm.get("hover_delay_ms") or 0) == 400:       # 旧默认 → 新默认
                _rm["hover_delay_ms"] = 180
                _migrated = True
            if int(_rm.get("long_press_delay_ms") or 0) == 500:
                _rm["long_press_delay_ms"] = 300
                _migrated = True
        except (TypeError, ValueError):
            _rm["hover_delay_ms"] = 180
            _rm["long_press_delay_ms"] = 300
            _migrated = True
        if "hold_select" not in _rm:
            _rm["hold_select"] = True
            _migrated = True
        # PATCH 3.3.0：按住启动 / 轮盘 / 移动延迟（缺省补齐，不覆盖用户自定义）
        for _k, _v in (("hold_launch_ms", 2000), ("move_delay_ms", 350), ("wheel_enabled", True)):
            if _k not in _rm:
                _rm[_k] = _v
                _migrated = True

    # PATCH 3.5.1：进程面板配置补齐
    if not isinstance(defaults.get("process_panel"), dict):
        defaults["process_panel"] = {"enabled": True, "hover_delay_ms": 250}
        _migrated = True
    else:
        defaults["process_panel"].setdefault("enabled", True)
        defaults["process_panel"].setdefault("hover_delay_ms", 250)

    # PATCH 3.5.1：退出 AgentFloat 不再结束 Agent 进程（历史配置统一关闭，可在设置中重新开启）
    if defaults.get("cleanup_on_quit"):
        defaults["cleanup_on_quit"] = False
        _migrated = True

    # PATCH 3.5.1：余额显示框（位置 / 拖动偏移 / 模块化行）
    _am_cfg = defaults.get("api_monitor")
    if isinstance(_am_cfg, dict):
        for _k, _v in (("badge_position", "top"), ("badge_dx", 0),
                       ("badge_dy", 0), ("badge_rows", [])):
            if _k not in _am_cfg:
                _am_cfg[_k] = _v
                _migrated = True

    if _migrated and (loaded or not parse_error):
        save_config(defaults)
        _log().info("配置迁移完成：内置 Agent %d 个 / 菜单时延 %s+%sms（hold_select=%s）",
                    len(defaults["agents"]), (defaults.get("radial_menu") or {}).get("hover_delay_ms"),
                    (defaults.get("radial_menu") or {}).get("long_press_delay_ms"),
                    (defaults.get("radial_menu") or {}).get("hold_select"))

    # ── 值校验：防止损坏的配置导致不可恢复状态 ──
    defaults["widget_size"] = max(30, min(200, int(defaults.get("widget_size", DEFAULT_SIZE))))
    defaults["opacity"] = max(0.1, min(1.0, float(defaults.get("opacity", 0.88))))
    defaults["launch_mode"] = defaults["launch_mode"] if defaults["launch_mode"] in ("normal", "skip_permissions") else "normal"
    defaults["theme"] = defaults["theme"] if defaults.get("theme") in ("light", "dark") else "light"

    # 无有效数据时：区分「首次启动（文件缺失）」与「解析失败（文件存在但读不出）」
    if not loaded:
        # 检测 Windows 系统主题（两种情况都适用）
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

        if not os.path.exists(CONFIG_PATH):
            # 首次启动：自动生成默认配置文件（含示例端点），新用户开箱即用
            try:
                os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
                save_config(defaults)
                _log().info("首次启动，已生成默认配置: %s", CONFIG_PATH)
            except (IOError, OSError):
                pass
        elif parse_error:
            # PATCH 3.1.0：解析失败只备份、绝不覆盖原文件（可能只是写读并发/临时故障），
            # 本次使用默认值跑在内存里，等用户真正修改设置时才会写入
            try:
                _bak = CONFIG_PATH + ".corrupt_%s.bak" % time.strftime("%Y%m%d_%H%M%S")
                shutil.copy2(CONFIG_PATH, _bak)
                _log().warning("配置解析失败，已备份到 %s（保留原文件未覆盖，本次使用默认值）", _bak)
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
    """原子写入配置（PATCH 3.1.0）：同目录临时文件 + os.replace。

    读取方（设置页 / 启动 Agent / 其他线程）永远不会读到"写了一半"的文件，
    从根上消除「保存与读取并发 → 误判损坏 → 配置被清空」的事故。
    """
    with _LOCK:
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, CONFIG_PATH)
            _log().debug("配置已保存 (%d 键)", len(config))
        except (IOError, OSError) as e:
            _log().warning("配置保存失败: %s (%s)", CONFIG_PATH, e)
