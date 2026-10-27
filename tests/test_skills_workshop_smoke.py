# -*- coding: utf-8 -*-
"""C 线服务层冒烟：import 完整性 + 临时 home 下可构造 + 只读 API 可调用。"""
from agentfloat.services.skills import discovery, installer, metadata, models, scoring, workshop


def test_modules_import():
    for mod in (models, metadata, discovery, scoring, installer, workshop):
        assert mod is not None


def test_default_workshop_in_temp_home(tmp_path):
    ws = workshop.default_workshop(home=str(tmp_path))
    assert isinstance(ws, workshop.SkillWorkshop)


def test_list_entries_returns_payload(tmp_path):
    ws = workshop.default_workshop(home=str(tmp_path))
    payload = ws.list_entries()
    assert isinstance(payload, dict) and payload.get("ok") is True
    assert any(isinstance(v, list) for v in payload.values())


def test_cache_info_and_targets_payload(tmp_path):
    ws = workshop.default_workshop(home=str(tmp_path))
    assert isinstance(ws.cache_info(), (dict, list))
    assert isinstance(ws.targets_payload(), (dict, list))


def test_missing_entry_does_not_crash(tmp_path):
    ws = workshop.default_workshop(home=str(tmp_path))
    try:
        got = ws.get_entry("definitely-not-installed")
    except workshop.SkillWorkshopError:
        got = None
    assert got is None or hasattr(got, "id")
