# -*- coding: utf-8 -*-
"""统一进度总线：任务状态文件（原子写，可被 Qt / CLI / MCP 共用）。"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

STATUSES = ("plan", "running", "need_input", "failed", "done", "cancelled")
DEFAULT_SESSION = "default"
TERMINAL_STATUSES = ("done", "failed", "cancelled")
_WRITE_RETRIES = 3
_WRITE_RETRY_DELAY = 0.02


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def progress_dir() -> str:
    override = os.environ.get("AGENTFLOAT_PROGRESS_DIR")
    if override:
        path = os.path.abspath(os.path.expanduser(override))
    else:
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
        path = os.path.join(base, "AgentFloat", "progress")
    os.makedirs(path, exist_ok=True)
    return path


def _path(session_id: str) -> str:
    sid = str(session_id or DEFAULT_SESSION).strip()
    if not sid or any(ch in sid for ch in "\\/:*?\"<>|"):
        sid = DEFAULT_SESSION
    return os.path.join(progress_dir(), sid + ".json")


def _atomic_write(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".progress-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        # Windows 上目标文件可能正被另一写者/读者短暂占用：os.replace 会抛
        # PermissionError（WinError 5）。短重试后仍失败再用 shutil.move 兜底，
        # 避免两个进程写同一 session 时直接崩掉一方并丢步。
        last_error = None
        for attempt in range(_WRITE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(_WRITE_RETRY_DELAY * (attempt + 1))
        try:
            shutil.move(tmp, path)
            return
        except OSError:
            pass
        raise last_error or OSError("progress write failed: %s" % path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _eta(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    done = [s for s in steps if s.get("startedAt") and s.get("finishedAt")]
    durations = []
    for step in done:
        try:
            start = datetime.fromisoformat(step["startedAt"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(step["finishedAt"].replace("Z", "+00:00"))
            durations.append(max(0.0, (end - start).total_seconds()))
        except (ValueError, TypeError):
            continue
    remaining = [s for s in steps if s.get("status") in ("pending", "running")]
    if not durations or not remaining:
        return {"etaSeconds": None, "etaText": "待估", "confidence": "none"}
    avg = sum(durations) / len(durations)
    eta = avg * len(remaining)
    low, high = max(30, eta * 0.7), max(60, eta * 1.3)
    text = "~%d–%dm" % (max(1, round(low / 60)), max(2, round(high / 60)))
    conf = "high" if len(durations) >= 3 else ("medium" if len(durations) == 2 else "low")
    return {"etaSeconds": int(eta), "etaText": text, "confidence": conf}


def compute(data: Dict[str, Any]) -> Dict[str, Any]:
    data["eta"] = _eta(data.get("steps") or [])
    data["updatedAt"] = data.get("updatedAt") or now_iso()
    return data


def load(session_id: str = DEFAULT_SESSION) -> Optional[Dict[str, Any]]:
    try:
        with open(_path(session_id), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return compute(data)
    except (OSError, ValueError):
        return None
    return None


def list_sessions() -> List[Dict[str, Any]]:
    root = progress_dir()
    rows = []
    for name in os.listdir(root):
        if not name.endswith(".json"):
            continue
        data = load(name[:-5])
        if data:
            rows.append(data)
    rows.sort(key=lambda d: d.get("updatedAt") or "", reverse=True)
    return rows


def _find_step(steps: List[Dict[str, Any]], step_id: str = "", title: str = "") -> Optional[Dict[str, Any]]:
    for step in steps:
        if step_id and step.get("id") == step_id:
            return step
    for step in steps:
        if title and step.get("title") == title:
            return step
    return None


def update(session_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
    """应用一个协议事件并原子落盘。"""
    sid = session_id or DEFAULT_SESSION
    action = str(event.get("action") or "").strip()
    data = load(sid) or {
        "sessionId": sid, "project": "", "title": "", "status": "plan",
        "steps": [], "currentStepId": "", "needsInput": False,
        "createdAt": now_iso(), "updatedAt": now_iso(), "source": "cli",
    }
    steps: List[Dict[str, Any]] = list(data.get("steps") or [])

    if action == "plan":
        raw_steps = event.get("steps") or []
        steps = []
        for idx, item in enumerate(raw_steps):
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("name") or "步骤 %d" % (idx + 1))
                step_id = str(item.get("id") or "s%d" % (idx + 1))
                estimate = float(item.get("estimateMinutes") or item.get("estimate") or 0)
            else:
                title = str(item or "步骤 %d" % (idx + 1))
                step_id = "s%d" % (idx + 1)
                estimate = 0
            steps.append({"id": step_id, "title": title, "status": "pending",
                          "startedAt": "", "finishedAt": "", "note": "",
                          "estimateMinutes": float(estimate or 0)})
        data.update({
            "project": str(event.get("project") or data.get("project") or ""),
            "title": str(event.get("title") or data.get("title") or ""),
            "window": str(event.get("window") or data.get("window") or ""),
            "status": "running", "steps": steps, "currentStepId": "",
            "needsInput": False, "error": "", "question": "",
            # 复用 session id 再 plan = 新一轮任务：时间/终态必须重置，
            # 否则 2 分钟门槛与「已用」会跨历史（skill-install 是固定 id）。
            "createdAt": now_iso(), "finishedAt": "", "updatedAt": now_iso(),
            "source": str(event.get("source") or "cli"),
        })
    elif action == "step":
        title = str(event.get("title") or "")
        step = _find_step(steps, str(event.get("id") or ""), title)
        if step is None:
            step = {"id": "s%d" % (len(steps) + 1), "title": title or "步骤 %d" % (len(steps) + 1),
                    "status": "running", "startedAt": now_iso(), "finishedAt": "", "note": ""}
            steps.append(step)
        if not step.get("startedAt"):
            step["startedAt"] = now_iso()
        # 进入第 N 步时，把排在它前面的步骤收尾；否则会同时出现多个 running、进度永远 0/N
        try:
            target_idx = steps.index(step)
        except ValueError:
            target_idx = len(steps) - 1
        for idx, item in enumerate(steps):
            if item is step:
                continue
            if item.get("status") == "running":
                item["status"] = "done"
                item["finishedAt"] = item.get("finishedAt") or now_iso()
            elif idx < target_idx and item.get("status") == "pending":
                item["status"] = "done"
                item["finishedAt"] = item.get("finishedAt") or now_iso()
        step["status"] = "running"
        step["finishedAt"] = ""
        data["currentStepId"] = step["id"]
        data["status"] = "running"
        data["needsInput"] = False
        data["finishedAt"] = ""
    elif action == "next":
        current = _find_step(steps, str(data.get("currentStepId") or ""))
        if current and current.get("status") == "running":
            current["status"] = "done"
            current["finishedAt"] = current.get("finishedAt") or now_iso()
        nxt = next((s for s in steps if s.get("status") == "pending"), None)
        if nxt:
            nxt["status"] = "running"
            nxt["startedAt"] = nxt.get("startedAt") or now_iso()
            data["currentStepId"] = nxt["id"]
            data["status"] = "running"
        data["finishedAt"] = ""
    elif action == "retry":
        # 重试 = 复用原步骤重跑，绝不新增「步骤 N」：先按 currentStepId，
        # 再退回首个 failed / running 步骤，复位状态与计时。
        current = _find_step(steps, str(data.get("currentStepId") or ""))
        if current is None or current.get("status") in ("done", "pending"):
            current = next((s for s in steps if s.get("status") == "failed"), None)
        if current is None:
            current = next((s for s in steps if s.get("status") == "running"), None)
        if current is not None:
            current["status"] = "running"
            current["startedAt"] = now_iso()
            current["finishedAt"] = ""
            current["note"] = ""
            data["currentStepId"] = current["id"]
        data["status"] = "running"
        data["needsInput"] = False
        data["error"] = ""
        data["question"] = ""
        data["finishedAt"] = ""
    elif action == "done":
        current = _find_step(steps, str(data.get("currentStepId") or ""))
        if current and current.get("status") == "running":
            current["status"] = "done"
            current["finishedAt"] = now_iso()
        data["status"] = "done"
        data["currentStepId"] = ""
        data["needsInput"] = False
        data["finishedAt"] = now_iso()
    elif action == "fail":
        current = _find_step(steps, str(data.get("currentStepId") or ""))
        if current and current.get("status") == "running":
            current["status"] = "failed"
            current["finishedAt"] = now_iso()
        data["status"] = "failed"
        data["error"] = str(event.get("error") or "")
        data["finishedAt"] = now_iso()
    elif action == "need_input":
        data["status"] = "need_input"
        data["needsInput"] = True
        data["question"] = str(event.get("question") or event.get("message") or "需要确认")
        data["finishedAt"] = ""
    elif action == "cancel":
        data["status"] = "cancelled"
        data["finishedAt"] = now_iso()
    else:
        raise ValueError("unknown action: %s" % action)

    data["steps"] = steps
    data["updatedAt"] = now_iso()
    data["source"] = str(event.get("source") or data.get("source") or "cli")
    data = compute(data)
    _atomic_write(_path(sid), data)
    return data
