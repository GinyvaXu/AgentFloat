# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — 喝水助手计时核心

独立的循环计时器管理器（喝水 / 久坐 / 护眼），每个计时器独立循环，
可暂停 / 跳过 / 重置 / 稍后提醒；倒计时结束发出 timer_finished 信号，
由主程序决定提醒形态（全屏遮罩 / 居中弹窗 / 托盘气泡）。

支持前台进程豁免名单：例如游戏进行中时静默或降级为托盘气泡，
避免打断用户操作。统计仅记录今日杯数（轻量，跨日自动重置）。
"""
import copy
import json
import os
import random
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

# ── 内置计时器规格 ──
TIMER_SPECS = [
    {
        "id": "drink", "name": "喝水", "char": "水", "color": "#00A6A6",
        "default_min": 60,
        "messages": [
            "该喝水啦 💧",
            "喝口水，休息一下吧",
            "水分补给时间到",
            "身体在呼唤水分",
            "别忘了喝水哦",
        ],
    },
    {
        "id": "sit", "name": "久坐", "char": "坐", "color": "#E67E22",
        "default_min": 45,
        "messages": [
            "久坐提醒：起身活动一下",
            "站起来走一走，伸展筋骨",
            "活动一下肩颈，放松腰椎",
        ],
    },
    {
        "id": "eye", "name": "护眼", "char": "眼", "color": "#8E44AD",
        "default_min": 60,
        "messages": [
            "护眼时间：远眺 20 秒",
            "看看远处，放松双眼",
            "做一次眼保健操吧",
        ],
    },
]

STATE_CN = {
    "idle": "未启用",
    "running": "进行中",
    "paused": "已暂停",
    "snoozed": "稍后提醒",
    "ringing": "待确认",
}


def _default_timers():
    out = []
    for spec in TIMER_SPECS:
        out.append({
            "id": spec["id"],
            "name": spec["name"],
            "char": spec["char"],
            "color": spec["color"],
            "enabled": spec["id"] == "drink",
            "interval_min": spec["default_min"],
            "messages": list(spec["messages"]),
        })
    return out


# 默认配置（load_config 引用；用户可在「设置 → 喝水助手」修改）
DEFAULT_WATER = {
    "enabled": True,               # 喝水助手总开关
    "reminder_mode": "fullscreen", # fullscreen=全屏遮罩 / popup=居中弹窗 / tray=仅托盘气泡
    "screen_index": -1,            # -1=跟随浮窗所在屏幕；0..n=指定屏幕
    "sound": True,                 # 提醒时播放系统提示音
    "target_cups": 8,              # 每日目标杯数
    "snooze_minutes": 5,           # 「稍后提醒」顺延分钟数
    "exempt_processes": [],        # 前台进程豁免名单（如 notepad.exe）
    "exempt_behavior": "tray",     # 豁免时降级：tray=托盘气泡 / silent=完全静默
    "timers": _default_timers(),
}


def foreground_process_name():
    """返回当前前台窗口的进程名（小写）；失败返回空字符串"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        import psutil
        return (psutil.Process(pid.value).name() or "").lower()
    except Exception:
        return ""


def is_exempt_process(exempt_list):
    """当前前台进程是否命中豁免名单"""
    name = foreground_process_name()
    if not name:
        return False
    names = {str(x).strip().lower() for x in (exempt_list or []) if str(x).strip()}
    return name in names


class WaterTimerManager(QObject):
    """多个独立循环计时器 + 今日杯数统计"""

    timer_finished = pyqtSignal(str)   # timer id：该轮倒计时结束
    timers_changed = pyqtSignal()      # 任一计时器状态变化（面板刷新）
    cups_changed = pyqtSignal(int)     # 今日杯数变化

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._cfg = copy.deepcopy(config or DEFAULT_WATER)
        self._timers = {}
        self._load_stats()
        self._build_timers()
        self._last_tick = time.time()
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)

    # ── 初始化 ──
    def _build_timers(self):
        specs = {t["id"]: t for t in (self._cfg.get("timers") or _default_timers())}
        for spec in TIMER_SPECS:
            s = specs.get(spec["id"]) or {}
            interval = max(1, int(s.get("interval_min") or spec["default_min"]))
            enabled = bool(s.get("enabled", spec["id"] == "drink"))
            self._timers[spec["id"]] = {
                "id": spec["id"],
                "name": s.get("name") or spec["name"],
                "char": s.get("char") or spec["char"],
                "color": s.get("color") or spec["color"],
                "interval_min": interval,
                "messages": list(s.get("messages") or spec["messages"]),
                "enabled": enabled,
                "state": "running" if enabled else "idle",
                "remaining": interval * 60,
                "total": interval * 60,
            }

    # ── 心跳 ──
    def _tick(self):
        now = time.time()
        dt = now - self._last_tick
        self._last_tick = now
        if dt <= 0 or dt > 5:
            dt = 1.0
        fired = False
        alive = False
        for t in self._timers.values():
            if not t["enabled"]:
                continue
            if t["state"] in ("running", "snoozed"):
                alive = True
                t["remaining"] = max(0, t["remaining"] - dt)
                if t["remaining"] <= 0:
                    t["state"] = "ringing"
                    fired = True
                    self.timer_finished.emit(t["id"])
        # 每秒实时刷新（面板倒计时显示依赖此信号）
        if alive or fired:
            self.timers_changed.emit()

    # ── 只读 ──
    def timers(self):
        return list(self._timers.values())

    def timer_info(self, tid):
        return self._timers.get(tid)

    def config(self):
        return copy.deepcopy(self._cfg)

    # ── 控制 ──
    def start_timer(self, tid):
        t = self._timers.get(tid)
        if not t:
            return
        if t["state"] in ("paused", "idle"):
            if not t["enabled"]:
                t["enabled"] = True
            if t["remaining"] <= 0:
                self._reset_round(t)
            t["state"] = "running"
            self.timers_changed.emit()

    def pause_timer(self, tid):
        t = self._timers.get(tid)
        if t and t["state"] in ("running", "snoozed"):
            t["state"] = "paused"
            self.timers_changed.emit()

    def skip_timer(self, tid):
        """跳过本轮，直接进入下一轮"""
        t = self._timers.get(tid)
        if not t:
            return
        self._reset_round(t)

    def reset_timer(self, tid):
        """重置当前轮"""
        t = self._timers.get(tid)
        if not t:
            return
        t["remaining"] = t["total"] = int(t["interval_min"] * 60)
        t["state"] = "running" if t["enabled"] else "idle"
        self.timers_changed.emit()

    def _reset_round(self, t):
        t["remaining"] = t["total"] = int(t["interval_min"] * 60)
        t["state"] = "running" if t["enabled"] else "idle"
        self.timers_changed.emit()

    def confirm_timer(self, tid):
        """已喝水 / 知道了：drink +1 杯，然后进入下一轮"""
        t = self._timers.get(tid)
        if not t:
            return
        if tid == "drink":
            self.add_cup(1)
        self._reset_round(t)

    def snooze_timer(self, tid):
        """稍后提醒：顺延 snooze_minutes 后再次提醒"""
        t = self._timers.get(tid)
        if not t:
            return
        minutes = max(1, int(self._cfg.get("snooze_minutes") or 5))
        t["remaining"] = t["total"] = minutes * 60
        t["state"] = "snoozed"
        self.timers_changed.emit()

    def pick_message(self, tid):
        t = self._timers.get(tid)
        if not t or not t["messages"]:
            return "该休息一下啦"
        return random.choice(t["messages"])

    def apply_config(self, cfg):
        self._cfg = copy.deepcopy(cfg or DEFAULT_WATER)
        specs = {t["id"]: t for t in (self._cfg.get("timers") or _default_timers())}
        for tid, t in self._timers.items():
            s = specs.get(tid)
            if s is None:
                continue
            old_interval = t["interval_min"]
            old_enabled = t["enabled"]
            t["name"] = s.get("name") or t["name"]
            t["char"] = s.get("char") or t["char"]
            t["color"] = s.get("color") or t["color"]
            t["interval_min"] = max(1, int(s.get("interval_min") or old_interval))
            t["messages"] = list(s.get("messages") or t["messages"])
            t["enabled"] = bool(s.get("enabled", old_enabled))
            if t["enabled"] != old_enabled:
                self._reset_round(t)          # 开关变化 → 按新状态重置
            elif t["interval_min"] != old_interval and t["state"] not in ("running", "snoozed"):
                self.reset_timer(tid)         # 未在跑时应用新间隔
        self.timers_changed.emit()

    # ── 今日杯数统计 ──
    @staticmethod
    def _stats_path():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "AgentFloat", "water_stats.json")

    def _load_stats(self):
        self._today = time.strftime("%Y-%m-%d")
        self._cups = 0
        self._history = {}
        try:
            with open(self._stats_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            self._history = data.get("history") or {}
            if data.get("date") == self._today:
                self._cups = max(0, int(data.get("cups") or 0))
        except Exception:
            pass

    def _save_stats(self):
        try:
            path = self._stats_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"date": self._today, "cups": self._cups,
                           "history": self._history}, f,
                          ensure_ascii=False, indent=2)
        except Exception:
            pass

    def today_cups(self):
        if self._today != time.strftime("%Y-%m-%d"):
            self._load_stats()
        return self._cups

    def add_cup(self, n=1):
        self._today = time.strftime("%Y-%m-%d")
        self._cups = self.today_cups() + int(n)
        self._history[self._today] = self._cups
        self._save_stats()
        self.cups_changed.emit(self._cups)
