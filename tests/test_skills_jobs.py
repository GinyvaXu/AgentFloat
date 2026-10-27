# -*- coding: utf-8 -*-
"""Skill 安装任务状态机测试（注入 runner，不联网）。"""
import time

from agentfloat.services.skills import jobs


def _wait(timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = jobs.status()
        if not st["running"]:
            return st
        time.sleep(0.02)
    return jobs.status()


def test_start_and_done():
    jobs.reset()
    r = jobs.start("demo", runner=lambda eid, targets: {"ok": True})
    assert r["ok"] is True
    st = _wait()
    assert st["ok"] is True and st["phase"] == "done"


def test_error_path():
    jobs.reset()
    jobs.start("demo", runner=lambda eid, targets: {"ok": False, "error": "boom"})
    st = _wait()
    assert st["ok"] is False and "boom" in st["message"]


def test_busy_guard():
    jobs.reset()
    started = []

    def slow(eid, targets):
        started.append(eid)
        time.sleep(0.2)
        return {"ok": True}

    jobs.start("a", runner=slow)
    r2 = jobs.start("b", runner=slow)
    assert r2.get("busy") is True
    _wait()
