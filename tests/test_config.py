# -*- coding: utf-8 -*-
"""core/config.py 测试：首次生成 / 读写回环 / 损坏自愈 / 旧配置迁移 / 值校验 / 内置 Agent 迁移"""
import json

import pytest

from agentfloat.core import config as cfgmod


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    old = tmp_path / "launcher_config.json"
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", str(p))
    monkeypatch.setattr(cfgmod, "_OLD_CONFIG_PATH", str(old))
    return p, old


def test_first_run_creates_default_config(isolated_config):
    p, _ = isolated_config
    cfg = cfgmod.load_config()
    assert p.exists()
    assert cfg["theme"] in ("light", "dark")
    assert cfg["agents"] and any(a.get("primary") for a in cfg["agents"])
    assert cfg["radial_menu"]["enabled"] in (True, False)
    assert "api_monitor" in cfg and "news" in cfg and "water" in cfg


def test_save_load_roundtrip(isolated_config):
    p, _ = isolated_config
    cfg = cfgmod.load_config()
    cfg["theme"] = "dark"
    cfg["widget_size"] = 72
    cfg["hide_delay_ms"] = 1234
    cfgmod.save_config(cfg)
    cfg2 = cfgmod.load_config()
    assert cfg2["theme"] == "dark"
    assert cfg2["widget_size"] == 72
    assert cfg2["hide_delay_ms"] == 1234


def test_corrupt_config_backed_up_but_not_overwritten(isolated_config):
    """PATCH 3.1.0：解析失败只备份、绝不覆盖原文件（防误判损坏清空用户配置）"""
    p, _ = isolated_config
    p.write_text("{ not valid json", encoding="utf-8")
    cfg = cfgmod.load_config()
    backups = list(p.parent.glob("config.json.corrupt_*.bak"))
    assert backups, "解析失败应备份为 .corrupt_*.bak"
    assert p.read_text(encoding="utf-8") == "{ not valid json", "原文件不得被覆盖"
    assert cfg["agents"], "本次应回退到内存默认配置"


def test_atomic_save_leaves_no_tmp(isolated_config):
    p, _ = isolated_config
    cfg = cfgmod.load_config()
    cfgmod.save_config(cfg)
    assert p.exists() and json.loads(p.read_text(encoding="utf-8"))
    assert not (p.parent / "config.json.tmp").exists(), "临时文件应被 os.replace 清理"


def test_concurrent_save_load_no_false_corruption(isolated_config):
    """并发读写回归：过去非原子写入会让读取方解析失败并触发误判损坏"""
    import threading
    p, _ = isolated_config
    cfg = cfgmod.load_config()
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            cfg["hide_delay_ms"] = 800 + (i % 7)
            cfgmod.save_config(cfg)
            i += 1

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        for _ in range(40):
            data = cfgmod.load_config()
            assert isinstance(data, dict)
            assert data.get("agents"), "并发读取也必须拿到完整配置"
    finally:
        stop.set()
        t.join(timeout=2)
    assert not list(p.parent.glob("config.json.corrupt_*.bak")), "并发读写不得触发损坏备份"


def test_old_config_migration(isolated_config):
    p, old = isolated_config
    old.write_text(json.dumps({"theme": "dark", "widget_size": 66}), encoding="utf-8")
    cfg = cfgmod.load_config()
    assert cfg["theme"] == "dark"
    assert cfg["widget_size"] == 66
    assert p.exists(), "应迁移到新路径"
    assert not old.exists(), "迁移后应删除旧文件"


def test_value_clamps(isolated_config):
    p, _ = isolated_config
    cfg = cfgmod.load_config()
    cfg["widget_size"] = 9999
    cfg["opacity"] = 5.0
    cfg["theme"] = "neon"
    cfg["launch_mode"] = "whatever"
    cfgmod.save_config(cfg)
    cfg2 = cfgmod.load_config()
    assert cfg2["widget_size"] <= 200
    assert 0.1 <= cfg2["opacity"] <= 1.0
    assert cfg2["theme"] in ("light", "dark")
    assert cfg2["launch_mode"] in ("normal", "skip_permissions")


def test_builtin_agents_migration(isolated_config):
    p, _ = isolated_config
    p.write_text(json.dumps({
        "agents": [{"id": "claude", "name": "Claude Code", "command": "claude", "primary": True}],
    }), encoding="utf-8")
    cfg = cfgmod.load_config()
    ids = {a["id"] for a in cfg["agents"]}
    assert {"claude", "codex", "pi", "dsh"} <= ids, "升级后应自动补齐内置 Agent 预设"
    assert all(a.get("launcher") for a in cfg["agents"]), "旧配置应补全 launcher 字段"
