# -*- coding: utf-8 -*-
"""安装 / 卸载后台任务状态机单测（注入假任务，不联网、不执行 npm/pip）。"""
import threading
import time

import pytest

from agentfloat.services.catalog import jobs
from agentfloat.services.catalog.builtin import BUILTIN_SPECS
from agentfloat.services.catalog.merge import merge_layers


def spec():
    return merge_layers(BUILTIN_SPECS).get("gemini")


def wait_until(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = jobs.status()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise AssertionError("任务未在 %.1fs 内进入预期状态：%r" % (timeout, jobs.status()))


@pytest.fixture(autouse=True)
def clean_jobs():
    jobs.reset()
    yield
    jobs.reset()


def test_install_runs_to_done():
    started = jobs.start(spec(), "install", runner=lambda s: {"ok": True, "seconds": 1.2})
    assert started["ok"] is True and started["busy"] is False
    assert started["job"]["action"] == "install"
    assert started["job"]["phase"] == "queued"

    state = wait_until(lambda s: not s["running"])
    assert state["phase"] == "done"
    assert state["id"] == started["job"]["id"]
    assert state["action"] == "install"
    assert state["message"].startswith("安装完成")
    assert state["startedAt"] and state["finishedAt"]
    assert state["log"] and "安装完成" in state["log"][-1]


def test_failure_result_sets_error_and_reason():
    jobs.start(spec(), "install", runner=lambda s: {"ok": False, "reason": "boom"})
    state = wait_until(lambda s: not s["running"])
    assert state["phase"] == "error"
    assert "boom" in state["message"]
    assert any("boom" in line for line in state["log"])


def test_exception_sets_error():
    def broken(_spec):
        raise RuntimeError("网络断了")

    jobs.start(spec(), "install", runner=broken)
    state = wait_until(lambda s: not s["running"])
    assert state["phase"] == "error"
    assert "网络断了" in state["message"]


def test_second_start_returns_busy():
    entered = threading.Event()
    gate = threading.Event()

    def slow(_spec):
        entered.set()
        assert gate.wait(2.0)
        return {"ok": True, "seconds": 0}

    first = jobs.start(spec(), "install", runner=slow)
    assert first["ok"] is True
    try:
        assert entered.wait(2.0), "后台任务没有启动"
        running = jobs.status()
        assert running["running"] is True and running["phase"] == "running"

        second = jobs.start(spec(), "install", runner=slow)
        assert second["ok"] is False and second["busy"] is True
        assert second["job"]["id"] == first["job"]["id"]
    finally:
        gate.set()

    state = wait_until(lambda s: not s["running"])
    assert state["phase"] == "done"


def test_uninstall_action_done():
    jobs.start(spec(), "uninstall", runner=lambda s: {"ok": True, "removed": False})
    state = wait_until(lambda s: not s["running"])
    assert state["action"] == "uninstall"
    assert state["phase"] == "done"
    assert "无需卸载" in state["message"]


def test_reset_returns_idle():
    jobs.start(spec(), "install", runner=lambda s: {"ok": True})
    wait_until(lambda s: not s["running"])

    jobs.reset()
    state = jobs.status()
    assert state["phase"] == "idle"
    assert state["running"] is False
    assert state["id"] == "" and state["log"] == []


def test_status_is_copy():
    jobs.start(spec(), "install", runner=lambda s: {"ok": True})
    wait_until(lambda s: not s["running"])

    snapshot = jobs.status()
    snapshot["log"].append("外部篡改")
    snapshot["message"] = "被改"
    fresh = jobs.status()
    assert "外部篡改" not in fresh["log"]
    assert fresh["message"] != "被改"


def test_upgrade_action_done():
    jobs.start(spec(), "upgrade", runner=lambda s: {"ok": True, "seconds": 0.5})
    state = wait_until(lambda s: not s["running"])
    assert state["action"] == "upgrade"
    assert state["phase"] == "done"
    assert state["message"].startswith("升级完成")


def test_unknown_action_rejected_without_starting():
    result = jobs.start(spec(), "explode")
    assert result["ok"] is False and result["busy"] is False
    assert "explode" in result["error"]
    assert jobs.status()["phase"] == "idle"
