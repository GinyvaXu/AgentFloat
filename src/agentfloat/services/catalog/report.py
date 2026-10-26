# -*- coding: utf-8 -*-
"""目录只读载荷（供 /api/catalog 与测试复用）。"""
from __future__ import annotations

from typing import Dict, Optional

from . import installer
from .builtin import builtin_specs
from .merge import merge_layers


def catalog_payload(base: Optional[str] = None) -> Dict:
    """返回内置目录 + 本机检测状态（不安装、不改配置）。"""
    specs = merge_layers(builtin_specs())
    items = []
    for raw in builtin_specs():
        sid = raw["id"]
        spec = specs.get(sid)
        if spec is None:
            continue
        det = installer.detect(spec, base=base)
        items.append({
            "id": sid,
            "name": spec.name,
            "vendor": spec.vendor,
            "group": spec.group,
            "description": spec.description,
            "installType": installer.install_type(spec),
            "package": spec.install[0].package_or_url if spec.install else "",
            "command": spec.launch.command,
            "modes": list(getattr(spec.launch, "modes", []) or []),
            "headless": bool(getattr(spec.capability, "headless", False)),
            "installed": bool(det.get("installed")),
            "installSource": det.get("source", ""),
            "status": spec.status,
            "verifiedAt": spec.verified_at or "",
            "sourceUrl": spec.source or "",
        })
    return {"ok": True, "count": len(items), "items": items}
