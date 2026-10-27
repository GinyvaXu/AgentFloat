# -*- coding: utf-8 -*-
"""Skill 车间只读载荷（供 Web /api/skills/workshop 与测试复用）。"""
from __future__ import annotations

from typing import Any, Dict, Optional


def workshop_payload(tab: str = "installed", query: str = "", category: str = "",
                     config: Optional[Dict[str, Any]] = None,
                     home: Optional[str] = None) -> Dict[str, Any]:
    from agentfloat.services.skills.workshop import default_workshop
    if config is None:
        from agentfloat.core.config import load_config
        config = load_config()
    ws = default_workshop(config=config, home=home) if home else default_workshop(config=config)
    return ws.list_entries(tab=tab, query=query, category=category)


def _workshop(config=None):
    from agentfloat.services.skills.workshop import default_workshop
    if config is None:
        from agentfloat.core.config import load_config
        config = load_config()
    return default_workshop(config=config)


def install_skill(entry_id: str, targets=None, config=None) -> Dict[str, Any]:
    """安装 skill（同步执行；调用方负责确认）。"""
    eid = str(entry_id or "").strip()
    if not eid:
        return {"ok": False, "error": "缺少 entry_id"}
    try:
        return _workshop(config).install(eid, targets)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def uninstall_skill(entry_id: str, target_id=None, config=None) -> Dict[str, Any]:
    """卸载 skill；未指定 target 时尝试解析条目上的已装目标。"""
    eid = str(entry_id or "").strip()
    if not eid:
        return {"ok": False, "error": "缺少 entry_id"}
    ws = _workshop(config)
    if target_id:
        return ws.uninstall(eid, str(target_id))
    try:
        entry = ws.get_entry(eid) or {}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    targets = []
    inst = entry.get("installed")
    if isinstance(inst, list):
        for t in inst:
            if isinstance(t, dict):
                tid = t.get("targetId") or t.get("target_id") or t.get("id")
                if tid:
                    targets.append(str(tid))
    if not targets:
        return {"ok": False, "error": "未找到安装目标（该条目可能不是由本机安装）"}
    results = [ws.uninstall(eid, t) for t in targets]
    return {"ok": all((not isinstance(r, dict)) or r.get("ok", True) for r in results),
            "results": results}
