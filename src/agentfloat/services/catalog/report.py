# -*- coding: utf-8 -*-
"""目录只读载荷（供 /api/catalog 与测试复用）。

版本检查说明（v3.17.3）：
- 只为**已安装**条目查询最新版，未安装条目的 ``latestVersion`` 留空，避免首屏拖慢；
- ``npm view`` 结果做进程内 TTL 缓存（10 分钟），普通目录刷新不会反复联网；
- ``/api/catalog/refresh_versions`` 调用 :func:`clear_version_cache` 后重查。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from . import installer
from .builtin import builtin_specs
from .merge import merge_layers

#: 最新版缓存有效期（秒）；与需求「TTL 10 分钟」一致
VERSION_TTL_SECONDS = 600

_latest_cache: Dict[str, Tuple[float, str]] = {}
_cache_lock = threading.Lock()


def clear_version_cache() -> None:
    """清空最新版缓存（「检查更新」按钮 / 单测用）。"""
    with _cache_lock:
        _latest_cache.clear()


def _cached_latest(spec: Any, fetcher: Optional[Callable[[Any], str]] = None) -> str:
    """读缓存；过期或缺失时执行一次 npm view 并写回（空结果也缓存）。"""
    sid = str(getattr(spec, "id", "") or "")
    now = time.time()
    with _cache_lock:
        hit = _latest_cache.get(sid)
        if hit is not None and now < hit[0]:
            return hit[1]

    try:
        value = (fetcher or installer.latest_version)(spec)
    except Exception:  # noqa: BLE001
        value = ""
    value = str(value or "").strip()
    with _cache_lock:
        _latest_cache[sid] = (now + VERSION_TTL_SECONDS, value)
    return value


def _version_fields(spec: Any, installed: bool, base: Optional[str],
                    version_fetcher: Optional[Callable[[Any], str]] = None) -> Dict[str, Any]:
    """已安装才查版本；任何异常都退化为空版本，不影响目录展示。"""
    empty = {"currentVersion": "", "latestVersion": "", "updateAvailable": False}
    if not installed:
        return empty
    try:
        latest = ""
        if installer.install_type(spec) == "npm":
            latest = _cached_latest(spec, version_fetcher)
        info = installer.update_info(spec, base=base, latest=latest)
        return {
            "currentVersion": info.get("current", "") or "",
            "latestVersion": info.get("latest", "") or "",
            "updateAvailable": bool(info.get("updateAvailable")),
        }
    except Exception:  # noqa: BLE001
        return empty


def catalog_payload(base: Optional[str] = None, refresh_versions: bool = False,
                    version_fetcher: Optional[Callable[[Any], str]] = None) -> Dict:
    """返回内置目录 + 本机检测状态（不安装、不改配置）。

    ``version_fetcher`` 仅用于测试注入（默认走 :func:`installer.latest_version`）。
    """
    if refresh_versions:
        clear_version_cache()

    specs = merge_layers(builtin_specs())
    items = []
    for raw in builtin_specs():
        sid = raw["id"]
        spec = specs.get(sid)
        if spec is None:
            continue
        det = installer.detect(spec, base=base)
        installed = bool(det.get("installed"))
        versions = _version_fields(spec, installed, base, version_fetcher)
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
            "installed": installed,
            "installSource": det.get("source", ""),
            "currentVersion": versions["currentVersion"],
            "latestVersion": versions["latestVersion"],
            "updateAvailable": versions["updateAvailable"],
            "status": spec.status,
            "verifiedAt": spec.verified_at or "",
            "sourceUrl": spec.source or "",
        })
    return {"ok": True, "count": len(items), "items": items}
