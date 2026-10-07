# -*- coding: utf-8 -*-
"""Agent 进程监控 / 控制 / 面板 测试（PATCH 3.5.0）"""


def test_match_agents_by_name_and_cmdline():
    from agentfloat.services import agents_monitor as am
    procs = [(1, 0, "explorer.exe"), (10, 5, "claude.exe"), (11, 5, "node.exe")]
    agents = [
        {"id": "claude", "name": "Claude Code", "command": "claude",
         "proc_names": ["claude.exe"], "cmd_tokens": ["claude"]},
        {"id": "codex", "name": "Codex", "command": "codex"},
    ]
    out = am.match_agents(agents, self_pid=999, procs=procs,
                          cmdlines={11: '"node" C:/npm/node_modules/claude.js'})
    ids = [m["agent"]["id"] for m in out]
    assert "claude" in ids and "codex" not in ids
    assert out[0]["pids"] == [10, 11]          # 进程名 + 命令行双重命中


def test_match_agents_self_excluded():
    from agentfloat.services import agents_monitor as am
    procs = [(7, 0, "agentfloat_debug.exe")]
    agents = [{"id": "af", "name": "AF", "command": "agentfloat_debug"}]
    assert am.match_agents(agents, self_pid=7, procs=procs, cmdlines={}) == []


def test_agent_proc_names_and_tokens():
    from agentfloat.services.agents_monitor import agent_cmd_tokens, agent_proc_names
    a = {"command": "opencode", "proc_names": ["OpenCode.exe"], "cmd_tokens": ["@opencode/cli"]}
    assert "opencode" in agent_proc_names(a) and "opencode.exe" in agent_proc_names(a)
    assert agent_cmd_tokens(a) == ["@opencode/cli"]


def test_format_runtime():
    from agentfloat.services.agents_monitor import format_runtime
    assert format_runtime(None) == "--"
    assert format_runtime(12) == "12s"
    assert format_runtime(200) == "3m 20s"
    assert format_runtime(3900) == "1h 05m"


def test_build_key_plan():
    from agentfloat.services.agent_control import build_key_plan
    assert build_key_plan("go") == [("char", "g"), ("char", "o"), ("enter",)]
    assert build_key_plan("") == [("enter",)]


def test_presets_carry_process_fields():
    from agentfloat.core.registry import default_agents
    by_id = {a["id"]: a for a in default_agents()}
    assert "claude.exe" in by_id["claude"]["proc_names"]
    assert by_id["claude"]["continue_text"] == "continue"
    assert by_id["opencode"]["cmd_tokens"]
    assert "proc_names" in by_id["opencode-desktop"]
    # PATCH 3.5.1：中断后恢复会话参数
    assert by_id["claude"]["resume_args"] == ["--continue"]
    assert by_id["codex"]["resume_args"] == ["resume", "--last"]


def test_api_monitor_defaults_have_badge_box():
    from agentfloat.services.api_monitor.config import DEFAULTS
    assert DEFAULTS["badge_position"] == "top"
    assert DEFAULTS["badge_dx"] == 0 and DEFAULTS["badge_dy"] == 0
    assert DEFAULTS["badge_rows"] == []


def test_normalize_keeps_process_fields():
    from agentfloat.core.registry import normalize_agents
    out = normalize_agents([{
        "id": "x", "command": "x", "proc_names": ["x.exe"],
        "cmd_tokens": ["x-cli"], "continue_text": "继续",
    }])
    assert out[0]["proc_names"] == ["x.exe"]
    assert out[0]["cmd_tokens"] == ["x-cli"]
    assert out[0]["continue_text"] == "继续"


def test_process_panel_construct_and_refresh(qapp):
    from agentfloat.ui.process_panel import ProcessPanel
    p = ProcessPanel(lambda: [], theme="dark")
    p.refresh()                                # 无 Agent：不应抛异常
    assert p.layout() is not None
    p.hide_panel()


def test_process_panel_empty_state_text(qapp):
    """v3.8.0：空态文案统一为「暂无…」（见 ui/states.py）"""
    from agentfloat.ui.process_panel import ProcessPanel
    p = ProcessPanel(lambda: [], theme="dark")
    p.refresh()
    texts = []
    for i in range(p._body.count()):
        w = p._body.itemAt(i).widget()
        if w is not None and hasattr(w, "text"):
            texts.append(w.text())
    assert any(t.startswith("暂无") for t in texts), texts
    assert any("运行中的 Agent 进程" in t for t in texts), texts
    p.hide_panel()


def test_process_panel_interrupted_has_continue_no_start(qapp):
    from PyQt5.QtWidgets import QPushButton
    from agentfloat.ui.process_panel import ProcessPanel
    agents = [{"id": "claude", "name": "Claude Code", "command": "claude",
               "proc_names": ["claude.exe"], "resume_args": ["--continue"]}]
    p = ProcessPanel(lambda: agents, theme="dark")
    p._interrupted["claude"] = {"ts": 0, "hard": True}
    p.refresh()
    labels = []
    for i in range(p._body.count()):
        w = p._body.itemAt(i).widget()
        if w is not None:
            labels += [b.text() for b in w.findChildren(QPushButton)]
    assert "继续任务" in labels
    assert "启动" not in labels
    p.hide_panel()
