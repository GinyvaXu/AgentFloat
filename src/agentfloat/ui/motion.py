# -*- coding: utf-8 -*-
"""AgentFloat — 弹簧动效引擎与动效 token（对齐 ProjectDock web/spring.js 的手感）

设计要点：
- SpringState：纯数值弹簧（无 Qt 依赖，可单测）；数值积分 a = ((goal-v)*k - v*c)/m
- MotionDriver：单一 60fps 定时器驱动所有活动弹簧（避免每个动画各占一个 QTimer）
- 从当前值起步、可随时打断重定向（速度继承）——「跟手」的关键
- reduced-motion 开关（降级为直接跳变）
"""
import time as _time

try:
    from PyQt5.QtCore import QObject, QTimer
except Exception:  # 纯逻辑测试环境（无 Qt）降级
    QObject = object

    class QTimer(object):  # type: ignore
        def __init__(self, *a, **k):
            raise RuntimeError("Qt 不可用")


# ── 动效 token（统一时长/阻尼，供全项目引用）────────────
class Tokens(object):
    TICK_MS = 16                  # 60fps 驱动
    # 弹簧参数（刚度 k / 阻尼 c）——k 越大越快、c 越大越"稳"
    RING_OPEN = (420.0, 28.0)     # 环菜单展开：快而稳（PATCH 3.2.1，约 0.25s）
    RING_CLOSE = (460.0, 34.0)    # 环菜单收拢：干脆不过冲
    SLIDE = (340.0, 34.0)         # 贴边滑入/滑出：快而稳
    PRESS = (480.0, 30.0)         # 按压回弹：快、微过冲
    QUIT = (300.0, 28.0)          # 退出收拢
    SPEED = (300.0, 26.0)         # 通用速度感


SNAP_EPS = 0.0015        # 到位判定：值差
SNAP_VEL = 0.02          # 到位判定：速度
MAX_DT = 1.0 / 30.0      # 积分步长上限（避免卡顿后跳变）
_REDUCED = False


def set_reduced_motion(flag):
    global _REDUCED
    _REDUCED = bool(flag)


def reduced_motion():
    return _REDUCED


class SpringState(object):
    """纯数值弹簧。用法：state.to(goal)；每帧 state.step(dt) → 是否仍在运动。"""
    __slots__ = ("value", "velocity", "goal", "stiffness", "damping", "mass")

    def __init__(self, initial=0.0, stiffness=220.0, damping=26.0, mass=1.0):
        self.value = float(initial)
        self.velocity = 0.0
        self.goal = float(initial)
        self.stiffness = float(stiffness)
        self.damping = float(damping)
        self.mass = max(0.01, float(mass))

    def set_params(self, stiffness=None, damping=None, mass=None):
        if stiffness is not None:
            self.stiffness = float(stiffness)
        if damping is not None:
            self.damping = float(damping)
        if mass is not None:
            self.mass = max(0.01, float(mass))
        return self

    def to(self, goal):
        """重定向到目标（从当前值起步、保留速度 → 可打断/速度继承）"""
        self.goal = float(goal)
        return self

    def jump(self, value):
        """立即设值（同时清除速度）"""
        self.value = float(value)
        self.velocity = 0.0
        self.goal = float(value)
        return self

    def step(self, dt):
        """推进一帧；返回是否仍在运动"""
        if _REDUCED:
            self.jump(self.goal)
            return False
        dt = min(max(float(dt), 0.0), MAX_DT) or (1.0 / 60.0)
        acc = ((self.goal - self.value) * self.stiffness
               - self.velocity * self.damping) / self.mass
        self.velocity += acc * dt
        self.value += self.velocity * dt
        if abs(self.goal - self.value) <= SNAP_EPS and abs(self.velocity) <= SNAP_VEL:
            self.jump(self.goal)
            return False
        return True


class MotionDriver(QObject):
    """全局弹簧驱动器：单一定时器批量推进所有活动弹簧。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []            # [state, on_change, on_done]
        self._last = None
        self._timer = QTimer(self)
        self._timer.setInterval(Tokens.TICK_MS)
        self._timer.timeout.connect(self._tick)

    def animate(self, state, on_change, on_done=None):
        """注册弹簧；返回「取消」函数。on_change(value) 每帧回调。"""
        item = [state, on_change, on_done]
        self._items.append(item)
        self._last = _time.monotonic() - Tokens.TICK_MS / 1000.0
        if not self._timer.isActive():
            self._timer.start()
        return lambda: self._cancel(item)

    def animate_to(self, state, goal, on_change, on_done=None):
        state.to(goal)
        return self.animate(state, on_change, on_done)

    def stop_all(self):
        self._items = []
        self._timer.stop()

    def _cancel(self, item):
        try:
            self._items.remove(item)
        except ValueError:
            pass

    def _tick(self):
        now = _time.monotonic()
        dt = now - (self._last if self._last is not None else now)
        self._last = now
        for item in list(self._items):
            state, on_change, on_done = item
            moving = state.step(dt)
            try:
                on_change(state.value)
            except Exception:  # noqa: BLE001
                pass
            if not moving:
                self._items.remove(item)
                if on_done is not None:
                    try:
                        on_done()
                    except Exception:  # noqa: BLE001
                        pass
        if not self._items:
            self._timer.stop()


_motion = None


def motion():
    """全局 MotionDriver 单例（惰性创建；需 QApplication 已存在）"""
    global _motion
    if _motion is None:
        _motion = MotionDriver()
    return _motion


def spring(initial=0.0, params=None):
    """快捷创建：spring(0.0, Tokens.SPEED)"""
    p = params or (Tokens.SPEED[0], Tokens.SPEED[1])
    return SpringState(initial, p[0], p[1])
