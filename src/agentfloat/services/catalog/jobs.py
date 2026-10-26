# -*- coding: utf-8 -*-
"""Agent 安装 / 卸载后台任务（全局单任务）。

设计（对应「安装可能 1-3 分钟」的体验要求）：
- HTTP 只负责 ``start`` 拉起线程，然后立即返回；前端轮询 ``status``；
- 同一时刻只允许一个任务，重复启动返回 ``busy``（不排队，避免用户连点）；
- 任务函数可注入，单测不联网、不真的执行 npm/pip；
- ``status`` 返回深拷贝，避免调用方读到后台线程正在修改的中间态。

本模块不依赖 Qt / FastAPI，便于单测与 Web 后端复用。
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from . import installer
from .schema import AgentSpec

#: 注入的任务函数：接收 spec，返回 installer.install / uninstall 同形状的 dict
TaskRunner = Callable[[AgentSpec], Dict[str, Any]]

_ACTIONS = ("install", "uninstall")
_lock = threading.RLock()
_job: Optional[Dict[str, Any]] = None
_thread: Optional[threading.Thread] = None


def _idle_job() -> Dict[str, Any]:
    """没有任务时的稳定快照（phase=idle 表示「从未启动 / 已 reset」）。"""
    return {
        "id": "",
        "action": "",
        "running": False,
        "phase": "idle",
        "message": "",
        "log": [],
        "startedAt": None,
        "finishedAt": None,
    }


def _set(job: Dict[str, Any], **fields: Any) -> None:
    """只更新当前任务，避免 reset 之后旧线程回写新任务。"""
    with _lock:
        if _job is not job:
            return
        job.update(fields)


def _append_log(job: Dict[str, Any], line: Any) -> None:
    """追加一行日志；保留最近 100 行，防止长安装把内存撑大。"""
    text = str(line or "").strip()
    if not text:
        return
    with _lock:
        if _job is not job:
            return
        job["log"].append(text[:500])
        if len(job["log"]) > 100:
            del job["log"][: len(job["log"]) - 100]


def status() -> Dict[str, Any]:
    """返回当前任务快照；没有任务时 phase=idle。"""
    with _lock:
        return copy.deepcopy(_job) if _job is not None else _idle_job()


def start(spec: AgentSpec, action: str = "install",
          runner: Optional[TaskRunner] = None) -> Dict[str, Any]:
    """启动任务并立即返回。

    返回 ``{ok, busy, job}``：
    - 启动成功：``ok=True, busy=False``，``job`` 为初始快照；
    - 已有任务在跑：``ok=False, busy=True``，附当前任务快照；
    - action 非法：``ok=False, busy=False``，附 error。
    """
    global _job, _thread
    action = str(action or "install")
    if action not in _ACTIONS:
        return {"ok": False, "busy": False, "error": "不支持的操作：%s" % action}

    with _lock:
        if _job is not None and _job.get("running"):
            return {
                "ok": False,
                "busy": True,
                "error": "已有安装任务正在执行，请等待完成",
                "job": copy.deepcopy(_job),
            }

        job: Dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "action": action,
            "running": True,
            "phase": "queued",
            "message": "排队中…",
            "log": [],
            "startedAt": time.time(),
            "finishedAt": None,
        }
        _job = job
        thread = threading.Thread(
            target=_work,
            args=(job, spec, action, runner),
            daemon=True,
            name="catalog-%s" % action,
        )
        _thread = thread
        thread.start()
        return {"ok": True, "busy": False, "job": copy.deepcopy(job)}


def reset() -> None:
    """清空任务状态（单测 / 排障用；不会中断已经启动的线程）。"""
    global _job, _thread
    with _lock:
        _job = None
        _thread = None


def _work(job: Dict[str, Any], spec: AgentSpec, action: str,
          runner: Optional[TaskRunner]) -> None:
    verb = "安装" if action == "install" else "卸载"
    target = "%s %s" % (verb, spec.name)
    _set(job, phase="running", message="%s中…" % target)
    _append_log(job, "开始%s（%s）" % (target, spec.id))

    try:
        fn = runner or (installer.install if action == "install" else installer.uninstall)
        result = fn(spec)
        if not isinstance(result, dict):
            result = {"ok": bool(result)}

        # 安装器内部各步骤的失败输出可能包含 npm/pip 的真实原因，带到日志末尾
        for step in result.get("log") or []:
            if not isinstance(step, dict):
                continue
            if step.get("rc") not in (0, None):
                _append_log(job, "步骤失败 rc=%s：%s" % (
                    step.get("rc"), str(step.get("out") or "")[-200:]))

        if result.get("ok"):
            if action == "uninstall":
                message = "卸载完成" if result.get("removed", True) else "受管目录不存在，无需卸载"
            else:
                seconds = result.get("seconds")
                suffix = "（%.1fs）" % float(seconds) if isinstance(seconds, (int, float)) else ""
                message = "安装完成%s" % suffix
            _append_log(job, message)
            _set(job, phase="done", message=message, running=False,
                 finishedAt=time.time())
        else:
            reason = str(result.get("reason") or result.get("error") or "未知错误").strip()
            message = "%s失败：%s" % (target, reason)
            _append_log(job, message)
            _set(job, phase="error", message=message, running=False,
                 finishedAt=time.time())
    except Exception as exc:  # noqa: BLE001
        reason = str(exc).strip() or exc.__class__.__name__
        message = "%s异常：%s" % (target, reason[:300])
        _append_log(job, message)
        _set(job, phase="error", message=message, running=False,
             finishedAt=time.time())
