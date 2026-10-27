# -*- coding: utf-8 -*-
"""Skill 车间只读载荷（/api/skills/workshop）测试。"""
from agentfloat.services.skills.report import workshop_payload


def test_payload_shape(tmp_path):
    got = workshop_payload(home=str(tmp_path), config={})
    assert isinstance(got, dict)
    assert got.get("ok") is True
    assert isinstance(got.get("entries"), list)
    assert "tab" in got


def test_tab_and_query_passthrough(tmp_path):
    got = workshop_payload(tab="discover", query="browser", home=str(tmp_path), config={})
    assert got.get("tab") == "discover"
    assert got.get("query") == "browser"
