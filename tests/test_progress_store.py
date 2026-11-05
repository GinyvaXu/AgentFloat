# -*- coding: utf-8 -*-
"""D 线 M1：进度总线文件协议 + CLI。"""
import json
import os
import subprocess
import sys

from agentfloat.services.progress import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_step_closes_previous_running(tmp_path, monkeypatch):
    """step 前进时收尾前面的步骤，不能同时多个 running（否则进度永远 0/N）。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    store.update("s2", {"action": "plan", "project": "AgentFloat",
                        "title": "体验测试", "steps": ["读取需求", "扫描代码", "写实现", "跑测试"]})
    store.update("s2", {"action": "step", "title": "扫描代码"})
    data = store.update("s2", {"action": "step", "title": "写实现"})
    running = [s["title"] for s in data["steps"] if s["status"] == "running"]
    assert running == ["写实现"], running
    assert data["steps"][0]["status"] == "done"
    assert data["steps"][1]["status"] == "done"
    assert data["steps"][2]["status"] == "running"
    assert data["steps"][2]["finishedAt"] == ""


def test_plan_step_done_and_eta(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    data = store.update("s1", {"action": "plan", "project": "AgentFloat",
                               "title": "D 线 M1", "steps": ["设计", "实现", "验证"]})
    assert data["status"] == "running"
    assert [s["title"] for s in data["steps"]] == ["设计", "实现", "验证"]

    data = store.update("s1", {"action": "step", "title": "设计"})
    assert data["currentStepId"] == "s1"
    assert data["steps"][0]["status"] == "running"

    # 手工补时间，验证 ETA 投影
    state = store.load("s1")
    state["steps"][0]["startedAt"] = "2026-10-28T10:00:00+08:00"
    state["steps"][0]["finishedAt"] = "2026-10-28T10:10:00+08:00"
    state["steps"][0]["status"] = "done"
    (tmp_path / "s1.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    data = store.load("s1")
    assert data["eta"]["etaSeconds"] == 1200
    assert data["eta"]["confidence"] == "low"

    data = store.update("s1", {"action": "next"})
    assert data["steps"][0]["status"] == "done"
    assert data["steps"][1]["status"] == "running"

    data = store.update("s1", {"action": "done"})
    assert data["status"] == "done"
    assert [s["status"] for s in data["steps"]].count("done") == 2


def test_need_input_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    store.update("a", {"action": "plan", "project": "A", "steps": ["x"]})
    store.update("b", {"action": "plan", "project": "B", "steps": ["y"]})
    store.update("b", {"action": "need_input", "question": "确认？"})
    rows = store.list_sessions()
    assert {r["sessionId"] for r in rows} == {"a", "b"}
    b = next(r for r in rows if r["sessionId"] == "b")
    assert b["status"] == "need_input" and b["needsInput"] is True


def test_plan_resets_session_timestamps(tmp_path, monkeypatch):
    """复用同一 session id 再 plan = 新任务：createdAt/finishedAt 必须重置（skill-install 固定 id）。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    store.update("skill-install", {"action": "plan", "title": "旧任务", "steps": ["a"]})
    path = tmp_path / "skill-install.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["createdAt"] = "2020-01-01T00:00:00+08:00"
    state["finishedAt"] = "2020-01-01T00:05:00+08:00"
    state["status"] = "done"
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    data = store.update("skill-install", {"action": "plan", "title": "新任务", "steps": ["b"]})
    assert data["createdAt"] != "2020-01-01T00:00:00+08:00"
    assert data["finishedAt"] == ""
    assert data["status"] == "running"
    assert data["currentStepId"] == ""
    assert [s["title"] for s in data["steps"]] == ["b"]


def test_terminal_actions_write_session_finished_at(tmp_path, monkeypatch):
    """done / fail / cancel 必须写 session 级 finishedAt，否则「已用」永远在涨。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    for action in ("done", "fail", "cancel"):
        sid = "t-" + action
        store.update(sid, {"action": "plan", "steps": ["a", "b"]})
        store.update(sid, {"action": "step", "title": "a"})
        state = store.load(sid)
        state["createdAt"] = "2020-01-01T00:00:00+08:00"
        (tmp_path / (sid + ".json")).write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
        data = store.update(sid, {"action": action})
        assert data["finishedAt"], action
        assert data["finishedAt"] != "2020-01-01T00:00:00+08:00"


def test_retry_reuses_failed_step_without_adding(tmp_path, monkeypatch):
    """驾驶舱「重试」不得追加「步骤 N」：复位原失败步骤并重新计时。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    store.update("r", {"action": "plan", "steps": ["a", "b", "c"]})
    store.update("r", {"action": "step", "title": "a"})
    failed = store.update("r", {"action": "fail", "error": "boom"})
    assert failed["steps"][0]["status"] == "failed"

    data = store.update("r", {"action": "retry"})
    assert len(data["steps"]) == 3, data["steps"]
    assert [s["status"] for s in data["steps"]] == ["running", "pending", "pending"]
    assert data["steps"][0]["finishedAt"] == ""
    assert data["currentStepId"] == data["steps"][0]["id"]
    assert data["status"] == "running"
    assert data["error"] == ""


def test_atomic_write_retries_transient_permission_error(tmp_path, monkeypatch):
    """两进程写同一 session 时 os.replace 可能短暂 PermissionError，需短重试。"""
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "locked by another writer")
        return real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", flaky)
    data = store.update("w", {"action": "plan", "steps": ["x"]})
    assert calls["n"] == 3
    assert data["sessionId"] == "w"
    assert store.load("w")["steps"][0]["title"] == "x"


def test_cli_reports_write_error_readably(monkeypatch, capsys):
    """写盘失败时 CLI 输出 {"ok": false} 而不是 traceback。"""
    from agentfloat.services.progress import cli

    def boom(*_a, **_k):
        raise PermissionError(5, "locked")

    monkeypatch.setattr(cli.store, "update", boom)
    rc = cli.main(["--session", "x", "plan", "--steps", "a"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 1
    assert payload["ok"] is False
    assert "写入失败" in payload["error"]
    assert "Traceback" not in out


def test_cli_plan_and_show(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTFLOAT_PROGRESS_DIR", str(tmp_path))
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(ROOT, "src")
    cmd = [sys.executable, "-m", "agentfloat.services.progress", "--session", "cli1",
           "plan", "--project", "Demo", "--steps", "a,b"]
    out = subprocess.check_output(cmd, env=env, text=True, encoding="utf-8")
    assert json.loads(out)["ok"] is True
    cmd = [sys.executable, "-m", "agentfloat.services.progress", "--session", "cli1", "show"]
    out = subprocess.check_output(cmd, env=env, text=True, encoding="utf-8")
    data = json.loads(out)["data"]
    assert data["project"] == "Demo"
    assert len(data["steps"]) == 2
