# -*- coding: utf-8 -*-
"""Content Catalog — 三层合并单测（P1 第一刀）

关键约束：远程只能改易变层、不能新增；用户覆盖优先；坏补丁回退内置。
"""
import copy

from agentfloat.services.catalog.merge import diff_specs, merge_layers
from agentfloat.services.catalog.schema import AgentSpec


def base_opencode():
    return {
        "schemaVersion": 1,
        "id": "opencode",
        "name": "OpenCode",
        "vendor": "Anomaly",
        "group": "intl-cli",
        "icon": "opencode.svg",
        "description": "终端里的 AI 编程代理",
        "platforms": {"windows": "native", "macos": "native", "linux": "native"},
        "install": [{"type": "npm", "packageOrUrl": "@opencode/cli"}],
        "launch": {"command": "opencode", "modes": ["interactive"]},
        "capability": {"headless": True},
        "health": {"versionCmd": "opencode --version", "versionPattern": r"(\d+\.\d+\.\d+)"},
        "status": "active",
        "verifiedAt": "2026-10-01",
        "source": "https://opencode.ai",
    }


def base_claude():
    return {
        "schemaVersion": 1,
        "id": "claude",
        "name": "Claude Code",
        "group": "intl-cli",
        "install": [{"type": "winget", "packageOrUrl": "Anthropic.ClaudeCode"}],
        "launch": {"command": "claude", "modes": ["interactive", "headless"]},
        "status": "active",
        "verifiedAt": "2026-10-02",
    }


def test_remote_patches_volatile_layer():
    remote = [{
        "id": "opencode",
        "install": [{"type": "winget", "packageOrUrl": "SST.OpenCode"}],
        "launch": {"command": "opencode2", "modes": ["interactive", "headless"]},
        "status": "deprecated",
        "verifiedAt": "2026-10-20",
    }]
    result = merge_layers([base_opencode()], remote)
    spec = result.get("opencode")
    assert result.patched == ["opencode"]
    assert spec.install[0].type == "winget"          # 远程换了安装方式
    assert spec.launch.command == "opencode2"        # 命令名属易变层
    assert spec.status == "deprecated"
    assert spec.name == "OpenCode"                   # 稳定层不动
    assert spec.description == "终端里的 AI 编程代理"


def test_remote_cannot_touch_stable_fields():
    remote = [{
        "id": "opencode",
        "name": "远程改名",
        "icon": "evil.png",
        "group": "cn-cli",
        "status": "active",
    }]
    result = merge_layers([base_opencode()], remote)
    spec = result.get("opencode")
    assert spec.name == "OpenCode"
    assert spec.icon == "opencode.svg"
    assert spec.group == "intl-cli"
    ignored = dict(result.ignored_fields)
    assert ignored["opencode"]  # 至少记录了一个被忽略的稳定字段
    assert "name" in str(result.ignored_fields)


def test_remote_cannot_add_new_agent():
    remote = [{"id": "brand-new", "name": "New", "group": "intl-cli"}]
    result = merge_layers([base_opencode()], remote)
    assert [spec.id for spec in result.agents] == ["opencode"]
    assert result.dropped and result.dropped[0][0] == "brand-new"


def test_broken_remote_patch_falls_back_to_bundled():
    remote = [{"id": "opencode", "install": []}]     # install 空了 → 非法
    result = merge_layers([base_opencode()], remote)
    spec = result.get("opencode")
    assert spec.install[0].package_or_url == "@opencode/cli"
    assert any(agent_id == "opencode" for agent_id, _ in result.dropped)


def test_user_override_wins_even_on_stable_fields():
    user = [{"id": "opencode", "name": "我的 OpenCode", "launch": {"command": "oc"}}]
    result = merge_layers([base_opencode()], None, user)
    spec = result.get("opencode")
    assert spec.name == "我的 OpenCode"
    assert spec.launch.command == "oc"


def test_user_can_add_private_agent():
    user = [{
        "schemaVersion": 1,
        "id": "my-agent",
        "name": "内部 Agent",
        "group": "cn-cli",
        "install": [{"type": "pip", "packageOrUrl": "internal-agent"}],
        "launch": {"command": "internal"},
        "status": "active",
    }]
    result = merge_layers([base_opencode()], None, user)
    assert result.added == ["my-agent"]
    assert result.get("my-agent").group == "cn-cli"


def test_invalid_user_entry_is_dropped_not_fatal():
    user = [{"id": "opencode", "platforms": {"windows": "maybe"}}]
    result = merge_layers([base_opencode()], None, user)
    assert result.get("opencode").support("windows") == "native"
    assert any("用户覆盖非法" in reason for _, reason in result.dropped)


def test_invalid_bundled_entry_is_dropped():
    broken = copy.deepcopy(base_opencode())
    broken["id"] = "broken"
    broken["group"] = "nope"
    result = merge_layers([base_opencode(), broken])
    assert [spec.id for spec in result.agents] == ["opencode"]
    assert any(agent_id == "broken" for agent_id, _ in result.dropped)


def test_result_is_sorted_by_group_then_id():
    desktop = {
        "schemaVersion": 1, "id": "cursor-desktop", "name": "Cursor", "group": "desktop",
        "install": [{"type": "winget", "packageOrUrl": "Anysphere.Cursor"}],
        "launch": {"command": "desktop", "modes": ["desktop"]}, "status": "active",
    }
    cn = {
        "schemaVersion": 1, "id": "qwen", "name": "Qwen Code", "group": "cn-cli",
        "install": [{"type": "npm", "packageOrUrl": "@qwen-code/qwen-code"}],
        "launch": {"command": "qwen"}, "status": "active",
    }
    result = merge_layers([desktop, base_opencode(), cn, base_claude()])
    assert [spec.id for spec in result.agents] == ["claude", "opencode", "qwen", "cursor-desktop"]
    assert list(result.by_group()) == ["intl-cli", "cn-cli", "desktop"]


def test_empty_layers_are_safe():
    result = merge_layers(None, None, None)
    assert result.agents == []
    assert result.dropped == []


def test_diff_specs_reports_added_removed_changed():
    old = [AgentSpec.from_dict(base_opencode()), AgentSpec.from_dict(base_claude())]
    changed_raw = base_opencode()
    changed_raw["status"] = "deprecated"
    new = [AgentSpec.from_dict(changed_raw)]
    diff = diff_specs(old, new)
    assert diff["removed"] == ["claude"]
    assert diff["changed"] == ["opencode"]
    assert diff["added"] == []
