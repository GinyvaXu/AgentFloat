# -*- coding: utf-8 -*-
"""杂项：自启路径转义 / 自启状态检测 / 浏览器打开 / UTF-8 控制台安全调用"""
from agentfloat.core import autostart
from agentfloat.core import sysutil


def test_escape_vbs_path():
    assert autostart._escape_vbs_path('a"b') == 'a""b'
    assert autostart._escape_vbs_path("plain") == "plain"


def test_is_auto_start_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "STARTUP_FOLDER", str(tmp_path))
    assert autostart.is_auto_start_enabled() is False
    (tmp_path / autostart.STARTUP_LNK_NAME).write_text("x", encoding="utf-8")
    assert autostart.is_auto_start_enabled() is True


def test_open_url(monkeypatch):
    calls = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: calls.append(u) or True)
    sysutil._open_url("https://example.com/x")
    assert calls == ["https://example.com/x"]


def test_ensure_utf8_stdio_subprocess():
    # 在 pytest 进程内包裹 sys.stdout 会破坏捕获流；用子进程隔离验证
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=os.path.join(root, "src"))
    r = subprocess.run(
        [sys.executable, "-c",
         "from agentfloat.core.sysutil import ensure_utf8_stdio; "
         "ensure_utf8_stdio(); print('ok')"],
        capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "ok" in r.stdout
