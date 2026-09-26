# -*- coding: utf-8 -*-
"""喝水助手测试：默认计时器 / 豁免判定 / 管理器状态机与杯数统计（offscreen Qt）"""
from agentfloat.services.water import reminder as wt


def test_default_timers_shape():
    timers = wt._default_timers()
    ids = {t["id"] for t in timers}
    assert {"drink", "eye", "sit"} <= ids
    assert all(t["interval_min"] >= 1 for t in timers)
    assert all(t["messages"] for t in timers)


def test_default_water_config_shape():
    assert wt.DEFAULT_WATER["target_cups"] >= 1
    assert wt.DEFAULT_WATER["reminder_mode"] in ("fullscreen", "popup", "tray")
    assert wt.DEFAULT_WATER["exempt_behavior"] in ("tray", "silent")


def test_is_exempt_process_false_for_empty():
    assert wt.is_exempt_process([]) is False
    assert wt.is_exempt_process(None) is False


def test_manager_flow(qapp, tmp_path, monkeypatch):
    stats = tmp_path / "water_stats.json"
    monkeypatch.setattr(
        wt.WaterTimerManager, "_stats_path", staticmethod(lambda: str(stats)))
    mgr = wt.WaterTimerManager(wt.DEFAULT_WATER)
    try:
        assert mgr.today_cups() == 0

        mgr.start_timer("drink")
        assert mgr.timer_info("drink")["state"] == "running"

        mgr.pause_timer("drink")
        assert mgr.timer_info("drink")["state"] == "paused"

        mgr.snooze_timer("drink")
        assert mgr.timer_info("drink")["state"] == "snoozed"
        assert mgr.timer_info("drink")["remaining"] == 5 * 60

        mgr.confirm_timer("drink")          # +1 杯，并进入下一轮
        assert mgr.today_cups() == 1
        assert mgr.timer_info("drink")["state"] == "running"

        mgr.add_cup(2)
        assert mgr.today_cups() == 3
        assert stats.exists(), "杯数应落盘"

        assert isinstance(mgr.pick_message("drink"), str)
        assert mgr.pick_message("nope")     # 未知 id 也有兜底文案

        cfg = mgr.config()
        cfg["timers"][0]["interval_min"] = 99
        mgr.apply_config(cfg)
        assert mgr.timer_info(cfg["timers"][0]["id"])["interval_min"] == 99

        mgr.reset_timer("drink")
        assert mgr.timer_info("drink")["remaining"] == 99 * 60
    finally:
        mgr._tick_timer.stop()


def test_manager_unknown_timer_noop(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(
        wt.WaterTimerManager, "_stats_path", staticmethod(lambda: str(tmp_path / "s.json")))
    mgr = wt.WaterTimerManager(wt.DEFAULT_WATER)
    try:
        for fn in (mgr.start_timer, mgr.pause_timer, mgr.skip_timer,
                   mgr.reset_timer, mgr.confirm_timer, mgr.snooze_timer):
            fn("does-not-exist")            # 不应抛异常
        assert mgr.timer_info("does-not-exist") is None
    finally:
        mgr._tick_timer.stop()
