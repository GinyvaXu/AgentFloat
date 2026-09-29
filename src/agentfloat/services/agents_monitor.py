# -*- coding: utf-8 -*-
"""Agent 进程监控（PATCH 3.5.0）

- 进程枚举：ctypes Toolhelp32（毫秒级，不依赖 PowerShell）
- 命令行匹配：按需调用一次 PowerShell CIM（node 类 CLI 通过 .cmd shim 启动，
  进程名是 node.exe，只能靠命令行特征识别；结果缓存 2.5s）
- 运行时长：GetProcessTimes 进程创建时间
- 最近活动：按 Agent 适配器读取本地日志尾部（Claude Code jsonl / dsh 日志等）
"""
import ctypes
import glob
import json
import os
import subprocess
import time
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_INVALID = ctypes.c_void_p(-1).value

_kernel32 = ctypes.windll.kernel32

_CMDLINE_TTL_S = 2.5
_cmdline_cache = {"ts": 0.0, "map": {}}


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def list_processes():
    """返回 [(pid, ppid, exe_name)]（Toolhelp32，快速）"""
    out = []
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == _INVALID:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID),
                        str(entry.szExeFile)))
            ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return out


def process_start_ts(pid):
    """进程创建时间（unix 秒）；失败返回 None"""
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_t = wintypes.FILETIME()
        kernel_t = wintypes.FILETIME()
        user_t = wintypes.FILETIME()
        if not _kernel32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_t),
                                        ctypes.byref(kernel_t), ctypes.byref(user_t)):
            return None
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return ticks / 1e7 - 11644473600.0
    finally:
        _kernel32.CloseHandle(h)


def _cmdline_map():
    """PID → 命令行（PowerShell CIM，缓存；失败返回空 dict）"""
    now = time.time()
    if now - _cmdline_cache["ts"] < _CMDLINE_TTL_S:
        return _cmdline_cache["map"]
    data = {}
    try:
        cmd = ("Get-CimInstance Win32_Process | "
               "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=8,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        raw = (r.stdout or "").strip()
        if raw:
            items = json.loads(raw)
            if isinstance(items, dict):
                items = [items]
            for it in items:
                pid = it.get("ProcessId")
                cl = it.get("CommandLine")
                if pid is not None and cl:
                    data[int(pid)] = str(cl)
    except Exception:  # noqa: BLE001
        data = {}
    _cmdline_cache["ts"] = now
    _cmdline_cache["map"] = data
    return data


def agent_proc_names(agent):
    """Agent 可匹配的进程名集合（小写，去扩展名）"""
    names = set()
    for n in (agent.get("proc_names") or []):
        n = str(n).strip().lower()
        if n:
            names.add(n)
    cmd = os.path.basename(str(agent.get("command") or "").strip().strip('"'))
    if cmd:
        names.add(cmd.lower())
        base, ext = os.path.splitext(cmd.lower())
        if ext in (".exe", ".cmd", ".bat") and base:
            names.add(base)
    return names


def agent_cmd_tokens(agent):
    """命令行特征（用于 node 类 CLI：进程名不匹配时按命令行识别）"""
    return [str(t).lower() for t in (agent.get("cmd_tokens") or []) if str(t).strip()]


def match_agents(agents, self_pid=None, procs=None, cmdlines=None):
    """为每个 Agent 匹配进程。

    返回 [{agent, pids, start_ts, runtime_s, names}]（仅含匹配到的 Agent）。
    """
    procs = procs if procs is not None else list_processes()
    if cmdlines is None:
        has_tokens = any(agent_cmd_tokens(a) for a in (agents or []))
        cmdlines = _cmdline_map() if has_tokens else {}
    self_pid = self_pid if self_pid is not None else os.getpid()
    out = []
    for a in agents or []:
        names = agent_proc_names(a)
        tokens = agent_cmd_tokens(a)
        if not names and not tokens:
            continue
        hits = []
        for pid, _ppid, exe in procs:
            if pid == self_pid:
                continue
            exe_l = exe.lower()
            matched = exe_l in names
            if not matched and tokens:
                cl = cmdlines.get(pid, "").lower()
                matched = bool(cl) and any(t in cl for t in tokens)
            if matched:
                hits.append(pid)
        if not hits:
            continue
        starts = [t for t in (process_start_ts(p) for p in hits) if t]
        start_ts = min(starts) if starts else None
        out.append({
            "agent": a,
            "pids": hits,
            "start_ts": start_ts,
            "runtime_s": (time.time() - start_ts) if start_ts else None,
            "names": sorted({p[2] for p in procs if p[0] in hits}),
        })
    return out


def format_runtime(seconds):
    """秒 → 人类可读（1h 05m / 3m 20s / 12s）"""
    if seconds is None:
        return "--"
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%dh %02dm" % (h, m)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


# ── 最近活动（阶段 1：日志尾部适配器）──────────────────────────
def _tail(path, limit=1):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-limit:]
    except Exception:  # noqa: BLE001
        return []


def _claude_activity():
    """Claude Code 最新会话 jsonl 的最后一条活动摘要"""
    try:
        base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
        files = glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True)
        if not files:
            return ""
        newest = max(files, key=lambda p: os.path.getmtime(p))
        tail = _tail(newest, 1)
        if not tail:
            return ""
        rec = json.loads(tail[0])
        typ = rec.get("type") or ""
        msg = rec.get("message") or {}
        if isinstance(msg, dict):
            content = msg.get("content")
            text = ""
            if isinstance(content, list) and content:
                c0 = content[-1]
                if isinstance(c0, dict):
                    text = str(c0.get("text") or c0.get("name") or "")
            elif isinstance(content, str):
                text = content
            if text:
                return "%s · %s" % (typ or "activity", text.replace("\n", " ")[:60])
        return typ
    except Exception:  # noqa: BLE001
        return ""


def _dsh_activity():
    try:
        from agentfloat.core.paths import config_dir
        logs = glob.glob(os.path.join(config_dir(), "logs", "dsh_*.log"))
        if not logs:
            return ""
        newest = max(logs, key=lambda p: os.path.getmtime(p))
        tail = _tail(newest, 1)
        return (tail[0].strip()[:80] if tail else "")
    except Exception:  # noqa: BLE001
        return ""


_ACTIVITY = {"claude": _claude_activity, "dsh": _dsh_activity}


def recent_activity(agent_id):
    """按 Agent 取最近活动文本（无适配器/失败返回空串）"""
    fn = _ACTIVITY.get(str(agent_id or ""))
    if fn is None:
        return ""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return ""
