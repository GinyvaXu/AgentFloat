# -*- coding: utf-8 -*-
"""Skill 安装后台任务（全局单任务 + 状态轮询）。"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

_LOCK = threading.Lock()
_JOB: Dict[str, Any] = {
    "id": "", "running": False, "phase": "idle", "message": "",
    "ok": None, "startedAt": 0.0, "finishedAt": 0.0, "action": "install",
}


def status() -> Dict[str, Any]:
    with _LOCK:
        return dict(_JOB)


def reset() -> None:
    with _LOCK:
        _JOB.update({"id": "", "running": False, "phase": "idle", "message": "",
                     "ok": None, "startedAt": 0.0, "finishedAt": 0.0, "action": "install"})


def start(entry_id: str, targets=None,
          runner: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """启动安装任务；已有任务在跑时返回 busy。"""
    with _LOCK:
        if _JOB["running"]:
            return {"ok": False, "busy": True, "job": dict(_JOB)}
        _JOB.update({"id": entry_id, "running": True, "phase": "running",
                     "message": "安装中…", "ok": None,
                     "startedAt": time.time(), "finishedAt": 0.0, "action": "install"})

    def _work():
        try:
            if runner is not None:
                res = runner(entry_id, targets)
            else:
                from agentfloat.services.skills.report import install_skill
                res = install_skill(entry_id, targets)
            ok = (not isinstance(res, dict)) or res.get("ok", True)
            msg = "已安装" if ok else ("安装失败：" + str((res or {}).get("error") or res))
        except Exception as e:  # noqa: BLE001
            ok, msg = False, "安装失败：%s" % e
        with _LOCK:
            _JOB.update({"running": False, "phase": "done" if ok else "error",
                         "message": msg, "ok": ok, "finishedAt": time.time()})

    threading.Thread(target=_work, daemon=True).start()
    return {"ok": True, "job": status()}
