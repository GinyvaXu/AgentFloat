# -*- coding: utf-8 -*-
"""单实例守卫（PATCH 3.0.1）

命名互斥体判断是否已有实例；重复启动时通过自定义窗口消息请求既有实例
把浮窗收回可见区域并置顶，然后本进程退出。

不依赖 QtNetwork（打包已裁剪 QtNetwork 模块），纯 ctypes / Win32 实现。
"""
import ctypes
from ctypes import wintypes

_MUTEX_NAME = "Local\\AgentFloat_SingleInstance_Mutex"
_ACTIVATE_MSG_NAME = "AgentFloat.ActivateExisting"
_BALL_TITLE = "AgentFloat"
ERROR_ALREADY_EXISTS = 183

TH32CS_SNAPPROCESS = 0x00000002
_AGENTFLOAT_EXES = ("agentfloat.exe", "agentfloat_debug.exe")

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32

_mutex_handle = None     # 进程存活期间保持互斥体句柄，防止被回收
_activate_msg = 0


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


def other_instances():
    """枚举其他 AgentFloat 进程（含旧版 / 调试版），返回 [(pid, exe_name), ...]

    旧版程序与本版共用 %APPDATA%/AgentFloat/config.json，同时运行会互相
    覆盖设置（PATCH 3.0.2 增加提醒）。
    """
    import os
    result = []
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return result
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile
            if name.lower() in _AGENTFLOAT_EXES and int(entry.th32ProcessID) != os.getpid():
                result.append((int(entry.th32ProcessID), name))
            ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return result


def activate_message_id():
    """注册（或获取）自定义窗口消息 ID；同名消息在所有进程内一致"""
    global _activate_msg
    if not _activate_msg:
        _activate_msg = int(_user32.RegisterWindowMessageW(_ACTIVATE_MSG_NAME))
    return _activate_msg


def acquire_single_instance():
    """尝试成为唯一实例。

    返回 True 表示本进程可以继续启动；False 表示已有实例在运行。
    互斥体创建失败时返回 True（宁可重复启动，也不误伤正常启动）。
    """
    global _mutex_handle
    if _mutex_handle:
        return True
    handle = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return True
    if _kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def activate_existing():
    """请求既有实例显示浮窗（浮窗离线时也会被收回可见区域）。

    返回是否至少向一个候选窗口投递成功。
    """
    msg = activate_message_id()
    if not msg:
        return False
    hwnds = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == _BALL_TITLE:
            hwnds.append(hwnd)
        return True

    _user32.EnumWindows(_cb, 0)
    ok = False
    for hwnd in hwnds:
        if _user32.PostMessageW(hwnd, msg, 0, 0):
            ok = True
    return ok
