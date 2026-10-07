# -*- coding: utf-8 -*-
"""v3.8.0 性能回归测试

改造点：浮球每 3 秒检测一次「主 Agent 是否在跑」，此前 spawn 一次
``tasklist.exe``（实测约 320ms/次 + 控制台管道 + 杀软关注），
现改为 CreateToolhelp32Snapshot 进程快照（约 20ms，15 倍）。
"""
import inspect
import time

from agentfloat.core import sysutil


def test_list_process_names_contains_self():
    names = sysutil.list_process_names()
    assert isinstance(names, set) and names, "应能取到进程快照"
    assert all(n == n.lower() for n in names), "统一小写"
    assert any("python" in n for n in names), "当前进程应能在快照里找到"


def test_process_running_matches_self_and_absent():
    assert sysutil.process_running("python.exe") is True
    assert sysutil.process_running("python") is True          # 自动补 .exe
    assert sysutil.process_running("PYTHON.EXE") is True      # 大小写不敏感
    assert sysutil.process_running("agentfloat-not-a-real-process.exe") is False
    assert sysutil.process_running("") is False
    assert sysutil.process_running(None) is False


def test_snapshot_is_fast_enough():
    """快照必须显著快于 tasklist 子进程方式（否则等于没优化）"""
    sysutil.list_process_names()      # 预热
    t0 = time.perf_counter()
    sysutil.list_process_names()
    cost_ms = (time.perf_counter() - t0) * 1000
    assert cost_ms < 150, "进程快照耗时异常（%.0fms）" % cost_ms


def test_floatball_no_longer_spawns_tasklist():
    """回归防线：浮球不得再每 3 秒 spawn tasklist（文档里提及历史做法不算）"""
    from agentfloat.ui import floatball
    src = inspect.getsource(floatball)
    assert '"tasklist"' not in src, "不应再有 tasklist 调用参数"
    assert "subprocess.run" not in src, "不应再 spawn 子进程做进程检测"
    assert "process_running(" in src
    assert "import subprocess" not in src, "已无 subprocess 依赖"
