# -*- coding: utf-8 -*-
"""内置 Agent 目录的校验测试（v3.16.5）。

目的：保证随包目录一定能通过 schema 校验，且每条都有可追溯的核实来源。
"""
from agentfloat.services.catalog.builtin import BUILTIN_SPECS, builtin_specs
from agentfloat.services.catalog.merge import merge_layers

EXPECTED = {s["id"] for s in BUILTIN_SPECS}


def test_builtin_specs_validate():
    result = merge_layers(builtin_specs())
    for spec in BUILTIN_SPECS:
        got = result.get(spec["id"])
        assert got is not None, "内置条目未通过校验: %s" % spec["id"]
        assert got.launch.command == spec["launch"]["command"]
        assert got.status in ("active", "deprecated")


def test_builtin_covers_verified_agents():
    ids = {s["id"] for s in BUILTIN_SPECS}
    assert len(EXPECTED) >= 19 and EXPECTED <= ids


def test_builtin_entries_are_traceable():
    for spec in BUILTIN_SPECS:
        assert spec.get("verifiedAt"), "%s 缺 verifiedAt" % spec["id"]
        assert spec.get("source"), "%s 缺 source" % spec["id"]
        assert spec["install"], "%s 缺安装方式" % spec["id"]
        if spec["group"] != "desktop":
            assert spec["health"].get("versionCmd"), "%s 缺版本检测命令" % spec["id"]


def test_builtin_specs_are_copies():
    first = builtin_specs()
    first[0]["name"] = "被改动"
    assert BUILTIN_SPECS[0]["name"] != "被改动"
