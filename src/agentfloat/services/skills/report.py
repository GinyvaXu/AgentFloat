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
