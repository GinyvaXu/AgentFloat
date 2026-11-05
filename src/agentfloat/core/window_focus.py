# -*- coding: utf-8 -*-
"""按窗口标题把目标窗口拉到前台（Windows）。"""
from __future__ import annotations

import os


def focus_window(title: str) -> bool:
    title = str(title or "").strip()
    if os.name != "nt" or not title:
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, title)
        if not hwnd:
            found = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            def _enum(handle, _lparam):
                length = user32.GetWindowTextLengthW(handle)
                if length:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(handle, buf, length + 1)
                    if title.lower() in buf.value.lower():
                        found.append(handle)
                        return False
                return True

            user32.EnumWindows(_enum, 0)
            hwnd = found[0] if found else 0
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False
