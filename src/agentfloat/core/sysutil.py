# -*- coding: utf-8 -*-
"""AgentFloat — 系统小工具（浏览器打开 / UTF-8 控制台）"""
import io
import logging
import sys


def _open_url(url):
    """在默认浏览器中打开链接"""
    import webbrowser
    try:
        webbrowser.open(url)
    except Exception:
        logging.getLogger("AgentFloat").warning("打开链接失败: %s", url)


def ensure_utf8_stdio():
    """Debug（console）构建下让 stdout/stderr 以 UTF-8 输出，避免中文乱码。"""
    if sys.platform != "win32":
        return
    try:
        if sys.stdout and hasattr(sys.stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        if sys.stderr and hasattr(sys.stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass


# ── 进程快照（v3.8.0 性能：替代每 3 秒 spawn 一次 tasklist.exe）──────
_TH32CS_SNAPPROCESS = 0x00000002


def list_process_names():
    """返回当前所有进程的可执行文件名（小写，含 .exe）；失败返回空集合。

    纯 ctypes 走 CreateToolhelp32Snapshot：实测约 20ms / 158 个进程，
    对比 ``tasklist`` 子进程方式约 320ms（且会弹控制台、易被杀软关注）。
    """
    import ctypes
    from ctypes import wintypes

    class _PROCESSENTRY32W(ctypes.Structure):
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

    names = set()
    try:
        k32 = ctypes.windll.kernel32
    except AttributeError:      # 非 Windows（测试环境）
        return names
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return names
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile:
                names.add(entry.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return names


def process_running(exe_name):
    """按可执行文件名判断是否有进程在运行（大小写不敏感，自动补 .exe）"""
    name = str(exe_name or "").strip().lower()
    if not name:
        return False
    if not name.endswith(".exe"):
        name += ".exe"
    return name in list_process_names()
