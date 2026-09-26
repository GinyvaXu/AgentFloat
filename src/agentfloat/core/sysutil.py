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
