# -*- coding: utf-8 -*-
"""Agent 启动偏好（按条目保存到 config.json）。

数据形状（不扩展目录 schema，避免远程/用户目录覆盖本机偏好）::

    config["catalog"]["launch"]["<agent-id>"] = {"mode": "window", "workdir": ""}

- ``mode``：``window``（新控制台，默认）或 ``background``（无窗口后台运行）；
- ``workdir``：空串表示用户主目录；非空时必须是当前存在的目录。

本模块不依赖 Qt / FastAPI，方便单测；读写统一走 ``core.config`` 的原子保存。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from agentfloat.core.config import load_config, save_config

MODES = ("window", "background")
DEFAULT_PREF: Dict[str, str] = {"mode": "window", "workdir": ""}


def _launch_map(config: Dict[str, Any], create: bool = False) -> Dict[str, Any]:
    """取 ``config.catalog.launch``；损坏的非 dict 节点按空处理。"""
    catalog = config.get("catalog")
    if not isinstance(catalog, dict):
        if not create:
            return {}
        catalog = {}
        config["catalog"] = catalog
    launch = catalog.get("launch")
    if not isinstance(launch, dict):
        if not create:
            return {}
        launch = {}
        catalog["launch"] = launch
    return launch


def normalize_workdir(workdir: Optional[str]) -> str:
    """去空格并展开 ``~``；空值保持空串。"""
    raw = str(workdir or "").strip()
    return os.path.expanduser(raw) if raw else ""


def get_pref(agent_id: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """读取某个 Agent 的启动偏好；缺失 / 损坏时返回默认值。"""
    cfg = config if isinstance(config, dict) else load_config()
    launch = _launch_map(cfg)
    item = launch.get(str(agent_id or "").strip())
    if not isinstance(item, dict):
        return dict(DEFAULT_PREF)
    mode = str(item.get("mode") or "").strip().lower()
    if mode not in MODES:
        mode = DEFAULT_PREF["mode"]
    workdir = str(item.get("workdir") or "").strip()
    return {"mode": mode, "workdir": workdir}


def set_pref(agent_id: str, mode: str, workdir: Optional[str] = "",
             config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """校验并写入偏好。

    返回 ``{"ok": True, "pref": {...}}``；非法输入返回 ``{"ok": False, "error": "..."}``。
    传入 ``config`` 时就地修改该 dict（供 Web handler 同步内存态），否则自行读写文件。
    """
    aid = str(agent_id or "").strip()
    if not aid:
        return {"ok": False, "error": "缺少 Agent id"}

    chosen = str(mode or "").strip().lower()
    if chosen not in MODES:
        return {"ok": False, "error": "启动模式只能是 %s" % " / ".join(MODES)}

    path = normalize_workdir(workdir)
    if path and not os.path.isdir(path):
        return {"ok": False, "error": "工作区不存在：%s" % path}

    cfg = config if isinstance(config, dict) else load_config()
    launch = _launch_map(cfg, create=True)
    pref = {"mode": chosen, "workdir": path}
    launch[aid] = pref
    try:
        save_config(cfg)
    except Exception as exc:  # noqa: BLE001
        # save_config 自身会吞 IO 异常；这里兜底防止注入的保存函数抛错冒到 HTTP 层
        return {"ok": False, "error": "保存失败：%s" % str(exc)[:200]}
    return {"ok": True, "pref": dict(pref)}
