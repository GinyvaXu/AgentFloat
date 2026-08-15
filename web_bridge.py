# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Web 壳通信桥

连接 FastAPI 后端线程（uvicorn）与 Qt 主线程的线程安全事件总线：

- to_app : Web → Qt 主线程命令队列（apply / preview / generate_news / check_update ...）
- to_web : Qt 主线程 → Web 事件队列（news_done / news_failed / api_updated / theme_changed ...），
           由 web_server 的 SSE 接口消费推送
- snapshot: Qt 主线程维护的只读状态快照（API 最近结果 / 快报报告 / 生成中标记），供 API 查询
"""
import copy
import queue
import threading
import time


class WebBridge(object):
    """线程安全事件总线（进程内单例由主程序创建并注入）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._to_app = queue.Queue()
        self._to_web = queue.Queue()
        self._snapshot = {
            "version": "",
            "api_results": [],
            "news_report": None,
            "news_generating": False,
            "dsh_running": False,
        }

    # ── Web → App（命令）──────────────────────────────
    def command(self, kind, payload=None):
        """投递一条命令给 Qt 主线程（由主线程定时器 drain 执行）。"""
        self._to_app.put((kind, copy.deepcopy(payload) if payload is not None else {}))

    def drain_commands(self):
        """取出所有待处理命令（Qt 主线程调用）。"""
        out = []
        while True:
            try:
                out.append(self._to_app.get_nowait())
            except queue.Empty:
                return out

    # ── App → Web（事件）──────────────────────────────
    def publish(self, event, payload=None):
        """Qt 主线程发布一条事件（SSE 推送）。"""
        ev = {
            "event": event,
            "payload": copy.deepcopy(payload) if payload is not None else {},
            "ts": time.strftime("%H:%M:%S"),
        }
        self._to_web.put(ev)

    def iter_events(self, timeout=15.0):
        """SSE 生成器：阻塞读取事件；超时返回心跳（保活）。"""
        while True:
            try:
                yield self._to_web.get(timeout=timeout)
            except queue.Empty:
                yield {"event": "ping", "payload": {}, "ts": time.strftime("%H:%M:%S")}

    # ── 状态快照 ──────────────────────────────────────
    def set_snapshot(self, key, value):
        with self._lock:
            self._snapshot[key] = copy.deepcopy(value)

    def get_snapshot(self, key=None):
        with self._lock:
            snap = copy.deepcopy(self._snapshot)
        if key is not None:
            return snap.get(key)
        return snap