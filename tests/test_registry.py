# -*- coding: utf-8 -*-
"""core/registry.py 测试：Agent 注册表 / 校验归一 / 命令解析 / 参数构造"""
from pathlib import Path

from agentfloat.core import registry as reg


def test_default_agents_returns_copies():
    a = reg.default_agents()
    a[0]["name"] = "MUTATED"
    assert reg.default_agents()[0]["name"] != "MUTATED"


def test_normalize_agents_drops_invalid_and_fills_defaults():
    raw = [
        {"id": "a", "command": "cmd-a"},
        "not-a-dict",
        {"id": "b"},                       # 无 command → 剔除
        {"id": "a", "command": "cmd-dup"},  # id 重复 → 重新编号
    ]
    out = reg.normalize_agents(raw)
    assert all(isinstance(x, dict) for x in out)
    assert all(x["command"] for x in out)
    assert len({x["id"] for x in out}) == len(out)
    assert any(x["primary"] for x in out), "至少保证一个 primary"


def test_normalize_empty_returns_defaults():
    out = reg.normalize_agents([])
    assert out and any(a.get("builtin") for a in out)


def test_get_primary_and_find():
    agents = reg.default_agents()
    assert reg.get_primary_agent(agents)["id"] == "claude"
    assert reg.find_agent(agents, "codex")["name"] == "Codex CLI"
    assert reg.find_agent(agents, "nope") is None


def test_build_agent_args_modes():
    a = {"command": "claude", "args": ["-p"], "skip_permissions_arg": "--skip"}
    assert reg.build_agent_args(a, "normal") == ["claude", "-p"]
    assert reg.build_agent_args(a, "skip_permissions") == ["claude", "-p", "--skip"]
    b = {"command": "pi", "args": [], "skip_permissions_arg": ""}
    assert reg.build_agent_args(b, "skip_permissions") == ["pi"]


def test_resolve_command_absolute_path(tmp_path):
    f = tmp_path / "tool.exe"
    f.write_text("x", encoding="utf-8")
    path, err = reg.resolve_command({"command": str(f)})
    assert err is None and path and path.lower().endswith("tool.exe")


def test_resolve_command_missing_path():
    path, err = reg.resolve_command({"command": str(Path("C:/definitely-missing-xyz/tool.exe"))})
    assert path is None and "不存在" in err


def test_resolve_command_empty():
    path, err = reg.resolve_command({"command": ""})
    assert path is None and "未配置" in err


def test_resolve_command_path_lookup(tmp_path, monkeypatch):
    exe = tmp_path / "afcli.exe"
    exe.write_text("x", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path))
    path, err = reg.resolve_command({"command": "afcli"})
    assert err is None and path and "afcli" in path.lower()


def test_resolve_command_not_in_path(monkeypatch):
    monkeypatch.setenv("PATH", "")
    path, err = reg.resolve_command({"command": "definitely-not-a-real-cli-xyz"})
    assert path is None and "PATH" in err


def test_windows_apps_path_guard():
    assert reg._is_windows_apps_path("C:\\Program Files\\WindowsApps\\x\\y.exe")
    assert reg._is_windows_apps_path("c:/program files/windowsapps/x")
    assert not reg._is_windows_apps_path("C:\\Tools\\x.exe")
