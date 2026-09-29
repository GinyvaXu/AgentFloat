# -*- coding: utf-8 -*-
"""Agent 进程控制（PATCH 3.5.0）：窗口定位/聚焦 · 软中断（Esc）· 继续任务（键盘注入）

安全约束：
- 注入前必须确认目标窗口已是前台窗口（GetForegroundWindow），否则放弃并返回失败原因
- 软中断（Esc）/ 继续（continue）都只作用于明确匹配到的窗口
"""
import ctypes
import time
from ctypes import wintypes

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

VK_ESCAPE = 0x1B
VK_RETURN = 0x0D
SW_RESTORE = 9
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]


WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def list_windows():
    """返回 [(hwnd, pid, title, class_name, visible, width*height)]（顶层窗口）"""
    out = []

    def cb(hwnd, _lp):
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(512)
        _user32.GetWindowTextW(hwnd, buf, 512)
        cls = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, cls, 256)
        r = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        w = max(0, int(r.right - r.left))
        h = max(0, int(r.bottom - r.top))
        out.append({
            "hwnd": int(hwnd), "pid": int(pid.value), "title": buf.value,
            "cls": cls.value, "visible": bool(_user32.IsWindowVisible(hwnd)),
            "area": w * h,
        })
        return True

    _user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def find_agent_window(agent, pids, tokens=None):
    """定位 Agent 的主窗口：优先同进程窗口，其次按标题匹配 Windows Terminal 窗口"""
    pids = set(int(p) for p in (pids or []))
    tokens = [str(t).lower() for t in (tokens or []) if str(t).strip()]
    wins = [w for w in list_windows() if w["visible"] and w["area"] > 8000]

    own = [w for w in wins if w["pid"] in pids]
    if own:
        own.sort(key=lambda w: -w["area"])
        return own[0]

    # Windows Terminal（CLI 在 ConPTY 中运行，窗口属于 WindowsTerminal.exe）
    term = [w for w in wins if "cascadia" in w["cls"].lower()]
    if term and tokens:
        matched = [w for w in term
                   if any(t in (w["title"] or "").lower() for t in tokens)]
        if matched:
            matched.sort(key=lambda w: -w["area"])
            return matched[0]
    # cmd.exe 兜底窗口（ConsoleWindowClass）同样按标题匹配
    console = [w for w in wins if "consolewindowclass" in w["cls"].lower()]
    if console and tokens:
        matched = [w for w in console
                   if any(t in (w["title"] or "").lower() for t in tokens)]
        if matched:
            matched.sort(key=lambda w: -w["area"])
            return matched[0]
    return None


def focus_window(hwnd):
    """聚焦窗口；返回是否成功成为前台"""
    try:
        _user32.ShowWindow(int(hwnd), SW_RESTORE)
        cur_tid = _kernel32.GetCurrentThreadId()
        tgt_tid = _user32.GetWindowThreadProcessId(int(hwnd), None)
        attached = False
        if tgt_tid and tgt_tid != cur_tid:
            attached = bool(_user32.AttachThreadInput(cur_tid, tgt_tid, True))
        try:
            _user32.SetForegroundWindow(int(hwnd))
            _user32.BringWindowToTop(int(hwnd))
        finally:
            if attached:
                _user32.AttachThreadInput(cur_tid, tgt_tid, False)
        time.sleep(0.12)
        return int(_user32.GetForegroundWindow()) == int(hwnd)
    except Exception:  # noqa: BLE001
        return False


def _send_key(vk=0, scan=0, flags=0):
    item = INPUT()
    item.type = INPUT_KEYBOARD
    item.u.ki = KEYBDINPUT(vk, scan, flags, 0, None)
    _user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))


def _send_unicode_char(ch):
    _send_key(0, ord(ch), KEYEVENTF_UNICODE)
    _send_key(0, ord(ch), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


def build_key_plan(text):
    """纯函数（可单测）：文本 → 按键计划 [("char", c) / ("enter",)]"""
    plan = [("char", ch) for ch in str(text or "")]
    plan.append(("enter",))
    return plan


def _run_plan(plan, per_key_delay=0.02):
    for step in plan:
        if step[0] == "char":
            _send_unicode_char(step[1])
        else:
            _send_key(VK_RETURN)
            _send_key(VK_RETURN, 0, KEYEVENTF_KEYUP)
        time.sleep(per_key_delay)


def send_interrupt(agent, pids, tokens=None):
    """软中断：聚焦窗口后发送 Esc（不结束进程）。返回 (ok, message)"""
    w = find_agent_window(agent, pids, tokens)
    if not w:
        return False, "未找到可聚焦窗口（可在窗口内手动按 Esc）"
    if not focus_window(w["hwnd"]):
        return False, "窗口聚焦失败（可能被系统限制）"
    if int(_user32.GetForegroundWindow()) != int(w["hwnd"]):
        return False, "目标窗口不在前台，已取消发送"
    _send_key(VK_ESCAPE)
    _send_key(VK_ESCAPE, 0, KEYEVENTF_KEYUP)
    return True, "已发送中断（Esc）"


def send_continue(agent, pids, tokens=None, text=None):
    """继续任务：聚焦窗口后注入「continue/继续」+ 回车。返回 (ok, message)"""
    w = find_agent_window(agent, pids, tokens)
    if not w:
        return False, "未找到可聚焦窗口（可在窗口内手动输入 continue）"
    if not focus_window(w["hwnd"]):
        return False, "窗口聚焦失败（可能被系统限制）"
    if int(_user32.GetForegroundWindow()) != int(w["hwnd"]):
        return False, "目标窗口不在前台，已取消注入"
    txt = text if text is not None else (agent.get("continue_text") or "continue")
    _run_plan(build_key_plan(txt))
    return True, "已注入：%s" % txt
